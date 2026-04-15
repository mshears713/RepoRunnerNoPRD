"""
ScanPipeline — orchestrates the 4-stage scan process.

Stages:
  1. FORK          — fork repo + commit devcontainer/run.sh
  2. CODESPACE     — create Codespace and wait for it to be ready
  3. EXECUTE       — wait for run.sh to finish and collect result
  4. ANALYZE       — Gemini summary + failure diagnosis; cleanup

Each stage:
  - Updates the scan JSON via storage.update_scan()
  - Appends log lines via storage.append_log()
  - On failure, sets status=failed and records error; does not re-raise

Mock mode (SCANNER_MOCK_MODE=full): all external calls are bypassed with fixture data.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import storage
from codespaces_client import CodespacesClient
from config import settings
from fork_preparer import prepare_fork
from github_client import GitHubClient
from result_analyzer import analyze
from result_fetcher import fetch_result

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(scan_id: str, stage: str, message: str, stream: str = "system") -> None:
    storage.append_log(scan_id, stage, stream, message)
    logger.info("[%s][%s] %s", scan_id, stage, message)


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
            logger.error("Scan %s not found", scan_id)
            return

        storage.update_scan(scan_id, status="running")

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
        except Exception as exc:
            logger.exception("Unhandled error in pipeline for scan %s", scan_id)
            storage.update_scan(scan_id, status="failed", error=str(exc))

    # ------------------------------------------------------------------
    # Stage 1: Fork
    # ------------------------------------------------------------------

    def _stage_fork(self, scan_id: str, scan: dict) -> None:
        _log(scan_id, "fork", f"Forking {scan['repo_owner']}/{scan['repo_name']}...")
        try:
            fork_name = self._github.fork_repo(scan["repo_owner"], scan["repo_name"])
            _log(scan_id, "fork", f"Fork created: {fork_name}")

            ready = self._github.wait_for_fork(fork_name)
            if not ready:
                raise RuntimeError("Fork did not become ready within timeout")

            _log(scan_id, "fork", "Committing devcontainer and run.sh...")
            prepare_fork(self._github, fork_name, scan["repo_name"])

            storage.update_scan(
                scan_id,
                fork_repo_name=fork_name,
                **{"timeline.forked_at": _now()},
            )
            _log(scan_id, "fork", "Fork stage complete.")
        except Exception as exc:
            _log(scan_id, "fork", f"Fork failed: {exc}", stream="stderr")
            storage.update_scan(scan_id, status="failed", error=f"Fork stage: {exc}")
            raise

    # ------------------------------------------------------------------
    # Stage 2: Codespace
    # ------------------------------------------------------------------

    def _stage_codespace(self, scan_id: str, scan: dict) -> None:
        fork_name = scan.get("fork_repo_name")
        if not fork_name:
            raise RuntimeError("No fork_repo_name set — fork stage may have failed")

        _log(scan_id, "codespace", f"Creating Codespace for {fork_name}...")
        try:
            cs = self._codespaces.create_codespace(fork_name)
            cs_name = cs["name"]
            _log(scan_id, "codespace", f"Codespace '{cs_name}' created, polling for Available state...")

            storage.update_scan(scan_id, codespace_name=cs_name)

            cs = self._codespaces.poll_until_available(cs_name)
            _log(scan_id, "codespace", "Codespace is Available.")

            storage.update_scan(
                scan_id,
                **{"timeline.codespace_ready_at": _now()},
            )
        except Exception as exc:
            _log(scan_id, "codespace", f"Codespace stage failed: {exc}", stream="stderr")
            storage.update_scan(scan_id, status="failed", error=f"Codespace stage: {exc}")
            raise

    # ------------------------------------------------------------------
    # Stage 3: Execute
    # ------------------------------------------------------------------

    def _stage_execute(self, scan_id: str, scan: dict) -> None:
        cs_name = scan.get("codespace_name")
        if not cs_name:
            raise RuntimeError("No codespace_name set")

        fork_name = scan.get("fork_repo_name")
        _log(scan_id, "execute", "Waiting for run.sh to push results...")
        storage.update_scan(scan_id, **{"timeline.started_at": _now()})

        try:
            execution = fetch_result(
                github_client=self._github,
                fork_full_name=fork_name,
                codespace_client=self._codespaces,
                codespace_name=cs_name,
            )
        except Exception as exc:
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

        storage.update_scan(
            scan_id,
            execution=execution,
            preview_url=preview_url,
            **{"timeline.finished_at": _now()},
        )
        _log(
            scan_id, "execute",
            f"Execution complete. stage_reached={execution.get('stage_reached')}, "
            f"exit_code={execution.get('exit_code')}",
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
        _log(scan_id, "analyze", "Running AI analysis...")
        try:
            repo_metadata = self._github.get_repo_metadata(
                scan["repo_owner"], scan["repo_name"]
            )
            file_tree = self._github.get_file_tree(scan["repo_owner"], scan["repo_name"])
            # Re-fetch scan to get execution data
            scan = storage.get_scan(scan_id)
            ai_result = analyze(scan, repo_metadata, file_tree)

            storage.update_scan(
                scan_id,
                status="completed",
                analysis=ai_result.get("analysis"),
                failure=ai_result.get("failure"),
            )
            _log(scan_id, "analyze", "Analysis complete.")
        except Exception as exc:
            _log(scan_id, "analyze", f"Analysis failed (non-fatal): {exc}", stream="stderr")
            # Analysis failure should not mark the whole scan as failed
            storage.update_scan(scan_id, status="completed", analysis=None, failure=None)
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
            _log(scan_id, "analyze", f"Deleting Codespace {cs_name}...")
            deleted = self._codespaces.delete_codespace(cs_name)
            storage.update_scan(scan_id, **{"cleanup.codespace_deleted": deleted})

        if fork_name and not scan.get("cleanup", {}).get("fork_deleted"):
            _log(scan_id, "analyze", f"Deleting fork {fork_name}...")
            deleted = self._github.delete_fork(fork_name)
            storage.update_scan(scan_id, **{"cleanup.fork_deleted": deleted})

    # ------------------------------------------------------------------
    # Mock mode
    # ------------------------------------------------------------------

    def _run_mocked(self, scan_id: str, scan: dict) -> None:
        """Run a simulated pipeline with fixture data. Used in tests and CI."""
        import time

        _log(scan_id, "fork", "[MOCK] Forking repo...")
        time.sleep(0.1)
        storage.update_scan(
            scan_id,
            fork_repo_name=f"mock-owner/{scan['repo_name']}",
            **{"timeline.forked_at": _now()},
        )

        _log(scan_id, "codespace", "[MOCK] Creating Codespace...")
        time.sleep(0.1)
        storage.update_scan(
            scan_id,
            codespace_name="mock-codespace-abc123",
            **{"timeline.codespace_ready_at": _now()},
        )

        _log(scan_id, "execute", "[MOCK] Executing...")
        time.sleep(0.1)
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
            **{"timeline.started_at": _now(), "timeline.finished_at": _now()},
        )

        _log(scan_id, "analyze", "[MOCK] Analyzing...")
        time.sleep(0.1)
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
        _log(scan_id, "analyze", "[MOCK] Pipeline complete.")
