"""GitHub client with explicit diagnostics for every GitHub operation."""

import base64
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from github import Github, GithubException

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class GitHubDiagnosticsError(RuntimeError):
    """Structured GitHub error that can be returned directly in API failure payloads."""

    step: str
    reason: str
    details: dict
    cause: Exception | None = None

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.reason

    def to_failure(self) -> dict:
        return {
            "step": self.step,
            "reason": self.reason,
            "details": self.details or {"error_message": "Unknown GitHub error"},
        }


class GitHubClient:
    def __init__(self, token: str | None = None, fork_owner: str | None = None):
        self._token = token or settings.github_token
        self._fork_owner = fork_owner or settings.github_fork_owner
        self._validate_token()
        self._gh = Github(self._token)
        self._authenticated_user = ""
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._authenticate()

    def _emit(
        self,
        step: str,
        status: str,
        message: str,
        details: dict | None = None,
        scan_id: str | None = None,
    ) -> None:
        details_str = f" | details={details}" if details else ""
        sid = scan_id or "no-scan-id"
        logger.info("[%s] [GITHUB] [%s] [%s] %s%s", sid, step, status, message, details_str)

    def _validate_token(self) -> None:
        exists = self._token is not None
        normalized = (self._token or "").strip()
        details = {"exists": bool(normalized and exists), "length": len(normalized)}
        if not normalized or not normalized.startswith(("ghp_", "github_pat_")):
            raise GitHubDiagnosticsError(
                step="github_auth",
                reason="GITHUB_TOKEN missing or invalid",
                details=details,
            )

    def _authenticate(self) -> None:
        try:
            user = self._gh.get_user()
            self._authenticated_user = user.login
            self._emit("auth", "success", f"Authenticated as user={self._authenticated_user}")
        except Exception as exc:
            failure = self._as_github_error(
                step="github_auth",
                reason="GitHub authentication failed",
                error=exc,
                details={
                    "error": str(exc) or repr(exc),
                    "likely_causes": [
                        "invalid token",
                        "expired token",
                        "insufficient permissions",
                    ],
                },
            )
            self._emit("auth", "failed", failure.reason, failure.details)
            raise failure from exc

    def _as_github_error(
        self,
        step: str,
        reason: str,
        error: Exception,
        details: dict | None = None,
        likely_causes: list[str] | None = None,
    ) -> GitHubDiagnosticsError:
        d = dict(details or {})
        d.setdefault("error_type", type(error).__name__)
        d.setdefault("error_message", str(error) or repr(error))
        status = getattr(error, "status", None)
        d.setdefault("http_status", status if status is not None else "unknown")
        if likely_causes:
            d.setdefault("likely_causes", likely_causes)
        return GitHubDiagnosticsError(step=step, reason=reason, details=d, cause=error)

    def github_step(
        self,
        step_name: str,
        func: Callable[[], object],
        *,
        scan_id: str | None = None,
        details: dict | None = None,
        reason: str = "GitHub operation failed",
        likely_causes: list[str] | None = None,
    ):
        self._emit(step_name, "start", "GitHub operation started", details, scan_id=scan_id)
        try:
            result = func()
            self._emit(step_name, "success", "GitHub operation completed", details, scan_id=scan_id)
            return result
        except GitHubDiagnosticsError:
            raise
        except Exception as exc:
            failure = self._as_github_error(
                step=step_name,
                reason=reason,
                error=exc,
                details=details,
                likely_causes=likely_causes,
            )
            self._emit(step_name, "failed", failure.reason, failure.details, scan_id=scan_id)
            raise failure from exc

    # ------------------------------------------------------------------
    # Repo metadata
    # ------------------------------------------------------------------

    def get_repo_metadata(self, owner: str, repo: str) -> dict:
        """Return basic repo metadata: description, language, topics, README excerpt."""
        gh_repo = self.github_step(
            "repo_metadata",
            lambda: self._gh.get_repo(f"{owner}/{repo}"),
            details={"repo": f"{owner}/{repo}", "user": self._authenticated_user},
            reason="GitHub metadata lookup failed",
        )
        try:
            readme = gh_repo.get_readme()
            raw = base64.b64decode(readme.content).decode("utf-8", errors="replace")
            readme_content = raw[:3000]
        except Exception:
            readme_content = ""

        return {
            "full_name": gh_repo.full_name,
            "description": gh_repo.description or "",
            "language": gh_repo.language or "",
            "topics": gh_repo.get_topics(),
            "stars": gh_repo.stargazers_count,
            "readme_excerpt": readme_content,
        }

    def get_file_tree(self, owner: str, repo: str, max_files: int = 80) -> list[str]:
        """Return a flat list of file paths from the default branch (up to max_files)."""
        gh_repo = self.github_step(
            "file_tree",
            lambda: self._gh.get_repo(f"{owner}/{repo}"),
            details={"repo": f"{owner}/{repo}", "user": self._authenticated_user},
            reason="GitHub file tree lookup failed",
        )
        try:
            tree = gh_repo.get_git_tree(gh_repo.default_branch, recursive=True)
            return [item.path for item in tree.tree if item.type == "blob"][:max_files]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------

    def fork_repo(self, owner: str, repo: str, scan_id: str | None = None) -> str:
        """
        Fork owner/repo into self._fork_owner account.
        If fork_owner is a GitHub organization, forks into it.
        If fork_owner is a personal account (or unset), forks into the authenticated user.
        Returns the forked repo's full_name (e.g. 'scanner-bot/repo').
        """
        repo_name = f"{owner}/{repo}"
        gh_repo = self.github_step(
            "fork",
            lambda: self._gh.get_repo(repo_name),
            scan_id=scan_id,
            details={"repo": repo_name, "user": self._authenticated_user},
            reason="GitHub fork failed",
            likely_causes=["missing repo permissions", "private repo access issue", "rate limit"],
        )

        if self._fork_owner:
            try:
                # Try as an organization first
                org = self._gh.get_organization(self._fork_owner)
                fork = self.github_step(
                    "fork",
                    lambda: gh_repo.create_fork(organization=org.login),
                    scan_id=scan_id,
                    details={"repo": repo_name, "user": self._authenticated_user},
                    reason="GitHub fork failed",
                    likely_causes=[
                        "missing repo permissions",
                        "private repo access issue",
                        "rate limit",
                    ],
                )
            except GithubException:
                # Not an org — fork into the authenticated user's account
                fork = self.github_step(
                    "fork",
                    lambda: gh_repo.create_fork(),
                    scan_id=scan_id,
                    details={"repo": repo_name, "user": self._authenticated_user},
                    reason="GitHub fork failed",
                    likely_causes=[
                        "missing repo permissions",
                        "private repo access issue",
                        "rate limit",
                    ],
                )
        else:
            fork = self.github_step(
                "fork",
                lambda: gh_repo.create_fork(),
                scan_id=scan_id,
                details={"repo": repo_name, "user": self._authenticated_user},
                reason="GitHub fork failed",
                likely_causes=[
                    "missing repo permissions",
                    "private repo access issue",
                    "rate limit",
                ],
            )

        return fork.full_name

    def wait_for_fork(self, fork_full_name: str, timeout: int | None = None) -> bool:
        """Poll until the fork is accessible. Returns True on success."""
        timeout = timeout or settings.fork_poll_timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._gh.get_repo(fork_full_name)
                return True
            except GithubException:
                time.sleep(3)
        return False

    def commit_files_to_fork(
        self, fork_full_name: str, files: dict[str, str], message: str = "Add scanner devcontainer"
    ) -> None:
        """
        Commit one or more files to the fork's default branch.
        files: { "path/in/repo": "file content as string" }
        """
        fork = self._gh.get_repo(fork_full_name)
        branch = fork.default_branch

        for path, content in files.items():
            try:
                existing = fork.get_contents(path, ref=branch)
                fork.update_file(
                    path=path,
                    message=message,
                    content=content,
                    sha=existing.sha,
                    branch=branch,
                )
            except GithubException:
                fork.create_file(
                    path=path,
                    message=message,
                    content=content,
                    branch=branch,
                )

    def get_file_from_fork(self, fork_full_name: str, file_path: str) -> str | None:
        """
        Read a file from the fork via the GitHub Contents API.
        Returns decoded file content as a string, or None if the file doesn't exist yet.
        This is used to poll for scanner_result.json written by run.sh.
        """
        try:
            fork = self._gh.get_repo(fork_full_name)
            contents = fork.get_contents(file_path)
            return base64.b64decode(contents.content).decode("utf-8", errors="replace")
        except GithubException:
            return None

    def delete_fork(self, fork_full_name: str) -> bool:
        """Delete the forked repo. Returns True on success."""
        try:
            fork = self._gh.get_repo(fork_full_name)
            fork.delete()
            return True
        except GithubException:
            return False

    def get_debug_status(self) -> dict:
        rate = self._gh.get_rate_limit().core
        return {
            "token_loaded": True,
            "token_length": len((self._token or "").strip()),
            "authenticated_user": self._authenticated_user,
            "rate_limit": {"remaining": rate.remaining, "limit": rate.limit},
        }

    # ------------------------------------------------------------------
    # Retry helper for rate limits
    # ------------------------------------------------------------------

    def _with_retry(self, fn, retries: int = 3, backoff: float = 5.0):
        for attempt in range(retries):
            try:
                return fn()
            except GithubException as e:
                if e.status == 429 and attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise
