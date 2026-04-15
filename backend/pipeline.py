"""
ScanPipeline — orchestrates the 4-stage scan process.

Stages:
  1. FORK          — fork repo + commit devcontainer/run.sh
  2. CODESPACE     — create Codespace and wait for it to be ready
  3. EXECUTE       — wait for run.sh to finish and collect result
  4. ANALYZE       — Gemini summary + failure diagnosis; cleanup

Each stage:
  - Adds structured timeline steps via storage.add_timeline_step()
  - Appends log lines via storage.append_log()
  - Emits structured logs: [SCAN_ID] [STEP_NAME] [STATUS] message
  - On failure: sets status=failed, error (non-empty), and failure object; re-raises

Mock mode (SCANNER_MOCK_MODE=full): all external calls are bypassed with fixture data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import storage
from codespaces_client import CodespacesClient
from config import settings
from fork_preparer import prepare_fork
from github_client import GitHubClient, GitHubDiagnosticsError
from result_analyzer import analyze
from result_fetcher import fetch_result

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(scan_id: str, step: str, status: str, message: str) -> None:
    """Record a timeline step, append a log entry, and emit a structured log line."""
    storage.add_timeline_step(scan_id, step, status, message)
    storage.append_log(scan_id, step, "system", f"[{status}] {message}")
    logger.info("[%s] [%s] [%s] %s", scan_id, step, status, message)


def _log(scan_id: str, step: str, status: str, message: str, stream: str = "system") -> None:
    """Append a raw log line (no timeline entry) and emit a structured log."""
    storage.append_log(scan_id, step, stream, message)
    logger.info("[%s] [%s] [%s] %s", scan_id, step, status, message)


def _github_timeline(
    scan_id: str,
    step: str,
    status: str,
    message: str,
    details: dict | None = None,
) -> None:
    storage.add_timeline_step(scan_id, step, status, message, details=details)


class _PipelineError(RuntimeError):
    """
    Raised by pipeline stages after they have already recorded failure in storage.
    Caught by ScanPipeline.run() to mark execution_start as failed without
    double-writing status/error/failure.
    """


class ScanPipeline:
    def __init__(
        self,
        github: GitHubClient | None = None,
        codespaces: CodespacesClient | None = None,
    ):
        # Defer real client creation to avoid failures when token is empty in mock mode
        self._github_override = github
        self._codespaces_override = codespaces

    @property
    def _github(self) -> GitHubClient:
        if self._github_override is None:
            self._github_override = GitHubClient()
        return self._github_override

    @property
    def _codespaces(self) -> CodespacesClient:
        if self._codespaces_override is None:
            self._codespaces_override = CodespacesClient()
        return self._codespaces_override

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self, scan_id: str) -> None:
        scan = storage.get_scan(scan_id)
        if scan is None:
            logger.error("[%s] [pipeline_start] [failed] Scan not found", scan_id)
            return

        storage.update_scan(scan_id, status="in_progress")
        _step(scan_id, "execution_start", "started", "Pipeline execution starting")

        if settings.scanner_mock_mode == "full":
            self._run_mocked(scan_id, scan)
            return

        try:
            self._stage_fork(scan_id, scan)
            scan = storage.get_scan(scan_id)  # refresh after each stage
            self._stage_codespace(scan_id, scan)
            scan = storage.get_scan(scan_id)
            self._stage_execute(scan_id, scan)
            scan = storage.get_scan(scan_id)
            self._stage_analyze(scan_id, scan)
        except _PipelineError as exc:
            # Stage already set status/error/failure — just close the execution_start step
            _step(scan_id, "execution_start", "failed", str(exc))
        except Exception as exc:
            # Unhandled exception that bypassed stage-level handling
            error_msg = str(exc) or "Unhandled pipeline error"
            logger.exception("[%s] [execution_start] [failed] %s", scan_id, error_msg)
            _step(scan_id, "execution_start", "failed", error_msg)
            storage.update_scan(
                scan_id,
                status="failed",
                error=error_msg,
                failure={
                    "step": "unknown",
                    "reason": error_msg,
                    "raw_error": repr(exc),
                },
            )
        else:
            _step(scan_id, "execution_start", "completed", "Pipeline completed successfully")

    # ------------------------------------------------------------------
    # Stage 1: Fork
    # ------------------------------------------------------------------

    def _stage_fork(self, scan_id: str, scan: dict) -> None:
        _step(scan_id, "fork", "started", f"Forking {scan['repo_owner']}/{scan['repo_name']}")
        try:
            _github_timeline(scan_id, "github_init", "completed", "GitHub client initialized")
            _github_timeline(scan_id, "github_auth", "completed", "GitHub authentication verified")
            _github_timeline(
                scan_id,
                "fork_start",
                "started",
                f"Starting fork for {scan['repo_owner']}/{scan['repo_name']}",
            )
            fork_name = self._github.fork_repo(
                scan["repo_owner"],
                scan["repo_name"],
                scan_id=scan_id,
            )
            _log(scan_id, "fork", "in_progress", f"Fork created: {fork_name}")

            ready = self._github.wait_for_fork(fork_name)
            if not ready:
                raise RuntimeError("Fork did not become ready within timeout")

            _log(scan_id, "fork", "in_progress", "Committing devcontainer and run.sh")
            prepare_fork(self._github, fork_name, scan["repo_name"])

            storage.update_scan(scan_id, fork_repo_name=fork_name)
            _github_timeline(scan_id, "fork_complete", "completed", f"Fork ready: {fork_name}")
            _step(scan_id, "fork", "completed", f"Fork ready: {fork_name}")
        except GitHubDiagnosticsError as exc:
            _github_timeline(scan_id, "fork_failed", "failed", exc.reason, details=exc.details)
            _step(scan_id, "fork", "failed", f"Fork stage: {exc.reason}")
            storage.update_scan(
                scan_id,
                status="failed",
                error=f"Fork failed: {exc.reason}",
                failure=exc.to_failure(),
            )
            raise _PipelineError(f"Fork failed: {exc.reason}") from exc
        except Exception as exc:
            import traceback

            error_message = str(exc) or repr(exc)
            stack_trace = traceback.format_exc()
            logger.error("[%s] fork failed: %s", scan_id, error_message)
            logger.error(stack_trace)
            _step(scan_id, "fork", "failed", f"Fork stage: {error_message}")
            storage.update_scan(
                scan_id,
                status="failed",
                error=f"Fork failed: {error_message}",
                failure={"step": "fork", "reason": error_message, "raw_error": stack_trace},
            )
            raise _PipelineError(f"Fork failed: {error_message}") from exc

    # ------------------------------------------------------------------
    # Stage 2: Codespace
    # ------------------------------------------------------------------

    def _stage_codespace(self, scan_id: str, scan: dict) -> None:
        fork_name = scan.get("fork_repo_name")
        if not fork_name:
            raise _PipelineError("No fork_repo_name set — fork stage may have failed")

        _step(scan_id, "codespace_create", "started", f"Creating Codespace for {fork_name}")
        try:
            cs = self._codespaces.create_codespace(fork_name)
            cs_name = cs["name"]
            msg = f"Codespace '{cs_name}' created, polling until Available"
            _log(scan_id, "codespace_create", "in_progress", msg)

            storage.update_scan(scan_id, codespace_name=cs_name)

            self._codespaces.poll_until_available(cs_name)
            _step(scan_id, "codespace_create", "completed", f"Codespace '{cs_name}' is Available")
        except Exception as exc:
            error_msg = f"Codespace stage: {exc}"
            _step(scan_id, "codespace_create", "failed", error_msg)
            storage.update_scan(
                scan_id,
                status="failed",
                error=error_msg,
                failure={"step": "codespace_create", "reason": str(exc), "raw_error": repr(exc)},
            )
            raise _PipelineError(error_msg) from exc

    # ------------------------------------------------------------------
    # Stage 3: Execute
    # ------------------------------------------------------------------

    def _stage_execute(self, scan_id: str, scan: dict) -> None:
        cs_name = scan.get("codespace_name")
        fork_name = scan.get("fork_repo_name")

        _step(scan_id, "execute", "started", "Waiting for run.sh to push results")

        try:
            execution = fetch_result(
                github_client=self._github,
                fork_full_name=fork_name,
                codespace_client=self._codespaces,
                codespace_name=cs_name,
            )
        except Exception as exc:
            _log(scan_id, "execute", "failed", f"fetch_result raised: {exc}", stream="stderr")
            execution = {
                "stage_reached": "cloned",
                "port": None,
                "health_check_url": None,
                "stdout_tail": "",
                "stderr_tail": str(exc),
                "exit_code": 1,
                "duration_sec": 0,
            }

        # Capture preview URL if app started
        preview_url = None
        if execution.get("stage_reached") == "started" and execution.get("port"):
            preview_url = self._codespaces.get_forwarded_port_url(cs_name, execution["port"])

        storage.update_scan(scan_id, execution=execution, preview_url=preview_url)

        stage_reached = execution.get("stage_reached")
        exit_code = execution.get("exit_code")
        exec_status = "completed" if stage_reached == "started" else "failed"
        _step(
            scan_id, "execute", exec_status,
            f"stage_reached={stage_reached} exit_code={exit_code}",
        )

        # Log stdout/stderr tails
        for line in execution.get("stdout_tail", "").splitlines()[-20:]:
            storage.append_log(scan_id, "execute", "stdout", line)
        for line in execution.get("stderr_tail", "").splitlines()[-20:]:
            storage.append_log(scan_id, "execute", "stderr", line)

    # ------------------------------------------------------------------
    # Stage 4: Analyze + cleanup
    # ------------------------------------------------------------------

    def _stage_analyze(self, scan_id: str, scan: dict) -> None:
        _step(scan_id, "analyze", "started", "Running AI analysis")
        try:
            repo_metadata = self._github.get_repo_metadata(
                scan["repo_owner"], scan["repo_name"]
            )
            file_tree = self._github.get_file_tree(scan["repo_owner"], scan["repo_name"])
            scan = storage.get_scan(scan_id)  # re-fetch to get execution data
            ai_result = analyze(scan, repo_metadata, file_tree)

            storage.update_scan(
                scan_id,
                status="completed",
                analysis=ai_result.get("analysis"),
                failure=ai_result.get("failure"),
            )
            _step(scan_id, "analyze", "completed", "Analysis complete")
        except Exception as exc:
            _log(scan_id, "analyze", "failed", f"Analysis failed (non-fatal): {exc}", "stderr")
            # Analysis failure does not fail the whole scan
            storage.update_scan(scan_id, status="completed", analysis=None)
            _step(scan_id, "analyze", "failed", f"Analysis skipped: {exc}")
        finally:
            self._cleanup(scan_id)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self, scan_id: str) -> None:
        scan = storage.get_scan(scan_id)
        if not scan:
            return

        cs_name = scan.get("codespace_name")
        fork_name = scan.get("fork_repo_name")

        if cs_name and not scan.get("cleanup", {}).get("codespace_deleted"):
            _log(scan_id, "cleanup", "in_progress", f"Deleting Codespace {cs_name}")
            deleted = self._codespaces.delete_codespace(cs_name)
            storage.update_scan(scan_id, **{"cleanup.codespace_deleted": deleted})

        if fork_name and not scan.get("cleanup", {}).get("fork_deleted"):
            _log(scan_id, "cleanup", "in_progress", f"Deleting fork {fork_name}")
            deleted = self._github.delete_fork(fork_name)
            storage.update_scan(scan_id, **{"cleanup.fork_deleted": deleted})

    # ------------------------------------------------------------------
    # Mock mode
    # ------------------------------------------------------------------

    def _run_mocked(self, scan_id: str, scan: dict) -> None:
        """Run a simulated pipeline with fixture data. Used in tests and CI."""
        import time

        repo_name = scan["repo_name"]

        _step(scan_id, "fork", "started", "[MOCK] Forking repo")
        time.sleep(0.05)
        fork_name = f"mock-owner/{repo_name}"
        storage.update_scan(scan_id, fork_repo_name=fork_name)
        _step(scan_id, "fork", "completed", f"[MOCK] Fork ready: {fork_name}")

        _step(scan_id, "codespace_create", "started", "[MOCK] Creating Codespace")
        time.sleep(0.05)
        storage.update_scan(scan_id, codespace_name="mock-codespace-abc123")
        _step(scan_id, "codespace_create", "completed", "[MOCK] Codespace is Available")

        _step(scan_id, "execute", "started", "[MOCK] Executing run.sh")
        time.sleep(0.05)
        mock_execution = {
            "stage_reached": "started",
            "port": 8000,
            "health_check_url": "http://localhost:8000",
            "stdout_tail": "INFO: Uvicorn running on http://0.0.0.0:8000",
            "stderr_tail": "",
            "exit_code": 0,
            "duration_sec": 12.3,
        }
        storage.update_scan(
            scan_id,
            execution=mock_execution,
            preview_url="https://mock-codespace-abc123-8000.app.github.dev",
        )
        _step(scan_id, "execute", "completed", "[MOCK] stage_reached=started exit_code=0")

        _step(scan_id, "analyze", "started", "[MOCK] Running AI analysis")
        time.sleep(0.05)
        storage.update_scan(
            scan_id,
            status="completed",
            analysis={
                "what_it_does": "A mock FastAPI application used for scanner testing.",
                "use_case": "Testing the Repo Viability Scanner pipeline.",
                "tech_stack": ["Python", "FastAPI"],
                "caveats": [],
            },
            failure=None,
            **{"cleanup.codespace_deleted": True, "cleanup.fork_deleted": True},
        )
        _step(scan_id, "analyze", "completed", "[MOCK] Analysis complete")
        _step(scan_id, "execution_start", "completed", "[MOCK] Pipeline complete")
