"""
GitHub Codespaces API client (raw httpx — not covered by PyGithub).
Handles the full Codespace lifecycle: create → poll → read file → delete.
"""

import asyncio
import time

import httpx

from config import settings

_BASE = "https://api.github.com"


class CodespacesClient:
    def __init__(self, token: str | None = None):
        self._token = token or settings.github_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _client(self) -> httpx.Client:
        return httpx.Client(headers=self._headers, timeout=30)

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_codespace(self, fork_full_name: str, machine: str = "basicLinux32gb") -> dict:
        """
        Create a new Codespace on the given forked repo.
        Returns the Codespace object dict (includes 'name', 'state', etc.).
        """
        owner, repo = fork_full_name.split("/", 1)
        with self._client() as c:
            resp = c.post(
                f"{_BASE}/repos/{owner}/{repo}/codespaces",
                json={
                    "machine": machine,
                    "devcontainer_path": ".devcontainer/devcontainer.json",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Poll until available
    # ------------------------------------------------------------------

    def poll_until_available(
        self, codespace_name: str, timeout: int | None = None
    ) -> dict:
        """
        Poll the Codespace state until it reaches 'Available' or times out.
        Returns the final Codespace dict.
        Raises TimeoutError if the timeout is reached.
        """
        timeout = timeout or settings.codespace_ready_timeout
        deadline = time.time() + timeout
        interval = 5

        while time.time() < deadline:
            cs = self._get_codespace(codespace_name)
            state = cs.get("state", "")
            if state == "Available":
                return cs
            if state in ("Failed", "Deleted"):
                raise RuntimeError(f"Codespace entered terminal state: {state}")
            time.sleep(interval)

        raise TimeoutError(f"Codespace {codespace_name} did not become Available within {timeout}s")

    def _get_codespace(self, name: str) -> dict:
        with self._client() as c:
            resp = c.get(f"{_BASE}/user/codespaces/{name}")
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Port forwarding URL
    # ------------------------------------------------------------------

    def get_forwarded_port_url(self, codespace_name: str, port: int) -> str | None:
        """
        Return the public port-forwarding URL for a given port.
        GitHub formats these as https://{codespace_name}-{port}.app.github.dev
        """
        # The URL pattern for Codespaces port forwarding
        return f"https://{codespace_name}-{port}.app.github.dev"

    # ------------------------------------------------------------------
    # Read file from Codespace filesystem
    # ------------------------------------------------------------------

    def read_file_from_codespace(self, codespace_name: str, file_path: str) -> str | None:
        """
        Attempt to read a file from inside the Codespace via the content proxy API.
        Returns file content as string, or None if not accessible.

        Note: This uses the Codespaces content API endpoint. The file_path should be
        an absolute path inside the Codespace (e.g. '/tmp/scanner_result.json').
        """
        with self._client() as c:
            try:
                resp = c.get(
                    f"{_BASE}/user/codespaces/{codespace_name}/content",
                    params={"path": file_path},
                    timeout=15,
                )
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                pass
        return None

    def poll_for_result_file(
        self,
        codespace_name: str,
        result_path: str = "/tmp/scanner_result.json",
        timeout: int | None = None,
    ) -> str | None:
        """
        Poll the Codespace filesystem for the result JSON file written by run.sh.
        Returns file content when found, or None on timeout.
        """
        timeout = timeout or settings.execution_timeout
        deadline = time.time() + timeout
        interval = 8

        while time.time() < deadline:
            content = self.read_file_from_codespace(codespace_name, result_path)
            if content:
                return content
            time.sleep(interval)

        return None

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_codespace(self, codespace_name: str) -> bool:
        """Delete a Codespace. Returns True on success."""
        with self._client() as c:
            try:
                resp = c.delete(f"{_BASE}/user/codespaces/{codespace_name}")
                return resp.status_code in (202, 204)
            except Exception:
                return False
