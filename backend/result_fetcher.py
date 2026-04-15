"""
Fetches the execution result from a running Codespace.
Polls /tmp/scanner_result.json written by run.sh.
Falls back to an HTTP health check on the forwarded port.
"""

import json
import time

import httpx

from codespaces_client import CodespacesClient
from config import settings


def fetch_result(
    client: CodespacesClient,
    codespace_name: str,
    timeout: int | None = None,
) -> dict:
    """
    Poll until run.sh writes /tmp/scanner_result.json, then parse and return it.
    Falls back to health-check probe if the file API is unavailable.
    Returns a dict matching the execution schema.
    """
    timeout = timeout or settings.execution_timeout
    raw = client.poll_for_result_file(codespace_name, timeout=timeout)

    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    # Fallback: try a plain HTTP health check on common ports
    for port in (8000, 3000, 8080, 5000):
        url = client.get_forwarded_port_url(codespace_name, port)
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
        "stderr_tail": "Result file not found and no port responded.",
        "exit_code": 1,
        "duration_sec": 0,
    }


def _http_reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return resp.status_code < 500
    except Exception:
        return False
