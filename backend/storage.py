"""
JSON file-based storage layer.
All scan data lives in:
  {DATA_DIR}/scans/{scan_id}.json
  {DATA_DIR}/logs/{scan_id}.jsonl
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings


def _scans_dir() -> Path:
    p = Path(settings.data_dir) / "scans"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _logs_dir() -> Path:
    p = Path(settings.data_dir) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _scan_path(scan_id: str) -> Path:
    return _scans_dir() / f"{scan_id}.json"


def _log_path(scan_id: str) -> Path:
    return _logs_dir() / f"{scan_id}.jsonl"


def create_scan(scan_id: str, data: dict) -> dict:
    """Write a new scan JSON file. Raises if it already exists."""
    path = _scan_path(scan_id)
    if path.exists():
        raise FileExistsError(f"Scan {scan_id} already exists")
    now = datetime.now(timezone.utc).isoformat()
    data = {"id": scan_id, "created_at": now, "updated_at": now, **data}
    path.write_text(json.dumps(data, indent=2))
    return data


def get_scan(scan_id: str) -> dict | None:
    """Return parsed scan dict, or None if not found."""
    path = _scan_path(scan_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def update_scan(scan_id: str, **fields: Any) -> dict:
    """
    Merge fields into the existing scan JSON and persist.
    Supports nested updates via dot-notation keys like 'timeline.forked_at'.
    """
    scan = get_scan(scan_id)
    if scan is None:
        raise FileNotFoundError(f"Scan {scan_id} not found")

    for key, value in fields.items():
        if "." in key:
            parts = key.split(".", 1)
            if parts[0] not in scan or not isinstance(scan[parts[0]], dict):
                scan[parts[0]] = {}
            scan[parts[0]][parts[1]] = value
        else:
            scan[key] = value

    scan["updated_at"] = datetime.now(timezone.utc).isoformat()
    _scan_path(scan_id).write_text(json.dumps(scan, indent=2))
    return scan


def list_scans(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """
    Return scans sorted by created_at descending.
    Optionally filter by status.
    """
    scans_dir = _scans_dir()
    paths = sorted(scans_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    results = []
    for path in paths:
        try:
            scan = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if status is None or scan.get("status") == status:
            results.append(scan)

    return results[offset : offset + limit]


def delete_scan(scan_id: str) -> bool:
    """Delete scan JSON and log files. Returns True if scan existed."""
    scan_path = _scan_path(scan_id)
    log_path = _log_path(scan_id)
    existed = scan_path.exists()
    if scan_path.exists():
        scan_path.unlink()
    if log_path.exists():
        log_path.unlink()
    return existed


def append_log(scan_id: str, stage: str, stream: str, line: str) -> None:
    """Append a single log entry to the scan's .jsonl file."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "stream": stream,
        "line": line,
    }
    with open(_log_path(scan_id), "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_logs(scan_id: str) -> list[dict]:
    """Return all log lines for a scan."""
    path = _log_path(scan_id)
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return lines


def find_scans_for_cleanup(older_than_seconds: int = 3600) -> list[dict]:
    """Return completed scans where codespace hasn't been deleted yet."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    results = []
    for scan in list_scans(limit=1000):
        if scan.get("status") not in ("completed", "failed"):
            continue
        cleanup = scan.get("cleanup", {})
        if cleanup.get("codespace_deleted"):
            continue
        if not scan.get("codespace_name"):
            continue
        created = scan.get("created_at", "")
        try:
            ts = datetime.fromisoformat(created)
            if ts < cutoff:
                results.append(scan)
        except ValueError:
            continue
    return results
