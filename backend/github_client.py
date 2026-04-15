"""
GitHub REST API client.
Wraps PyGithub for repo operations and raw httpx for anything PyGithub doesn't cover.
"""

import asyncio
import base64
import time
from typing import Any

import httpx
from github import Github, GithubException

from config import settings


class GitHubClient:
    def __init__(self, token: str | None = None, fork_owner: str | None = None):
        self._token = token or settings.github_token
        self._fork_owner = fork_owner or settings.github_fork_owner
        self._gh = Github(self._token)
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ------------------------------------------------------------------
    # Repo metadata
    # ------------------------------------------------------------------

    def get_repo_metadata(self, owner: str, repo: str) -> dict:
        """Return basic repo metadata: description, language, topics, README excerpt."""
        gh_repo = self._gh.get_repo(f"{owner}/{repo}")
        try:
            readme = gh_repo.get_readme()
            readme_content = base64.b64decode(readme.content).decode("utf-8", errors="replace")[:3000]
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
        gh_repo = self._gh.get_repo(f"{owner}/{repo}")
        try:
            tree = gh_repo.get_git_tree(gh_repo.default_branch, recursive=True)
            return [item.path for item in tree.tree if item.type == "blob"][:max_files]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Forking
    # ------------------------------------------------------------------

    def fork_repo(self, owner: str, repo: str) -> str:
        """
        Fork owner/repo into self._fork_owner account.
        If fork_owner is a GitHub organization, forks into it.
        If fork_owner is a personal account (or unset), forks into the authenticated user.
        Returns the forked repo's full_name (e.g. 'scanner-bot/repo').
        """
        gh_repo = self._gh.get_repo(f"{owner}/{repo}")

        if self._fork_owner:
            try:
                # Try as an organization first
                org = self._gh.get_organization(self._fork_owner)
                fork = gh_repo.create_fork(organization=org.login)
            except GithubException:
                # Not an org — fork into the authenticated user's account
                fork = gh_repo.create_fork()
        else:
            fork = gh_repo.create_fork()

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
