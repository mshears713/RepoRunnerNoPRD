"""
Fetches the execution result from a running Codespace.

Strategy: run.sh writes scanner_result.json and then git-commits it back to the
fork. The backend polls the GitHub Contents API for that file — a real, reliable
endpoint that doesn't require Codespace filesystem access.

Fallback: if the result file never appears (e.g., repo blocked git push), attempt
an HTTP health check on the forwarded port.
"""

import json
import time

import httpx

from config import settings


RESULT_FILE_PATH = "scanner_result.json"


def fetch_result(
    github_client,  # GitHubClient instance
    fork_full_name: str,
    codespace_client=None,  # CodespacesClient instance (for fallback)
    codespace_name: str | None = None,
    timeout: int | None = None,
) -> dict:
    """
    Poll the fork's GitHub Contents API for scanner_result.json.
    Falls back to HTTP health-check probe if file never appears.
    Returns a dict matching the execution schema.
    """
    timeout = timeout or settings.execution_timeout
    deadline = time.time() + timeout
    interval = 10

    while time.time() < deadline:
        raw = github_client.get_file_from_fork(fork_full_name, RESULT_FILE_PATH)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        time.sleep(interval)

    # Fallback: try HTTP health check on common ports via Codespaces port forwarding
    if codespace_client and codespace_name:
        for port in (8000, 3000, 8080, 5000):
            url = codespace_client.get_forwarded_port_url(codespace_name, port)
            if url and _http_reachable(url):
                return {
                    "stage_reached": "started",
                    "port": port,
                    "health_check_url": url,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "exit_code": 0,
                    "duration_sec": 0,
                }

    return {
        "stage_reached": "cloned",
        "port": None,
        "health_check_url": None,
        "stdout_tail": "",
        "stderr_tail": "Result file was not pushed to fork within the timeout.",
        "exit_code": 1,
        "duration_sec": 0,
    }


def _http_reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return resp.status_code < 500
    except Exception:
        return False
