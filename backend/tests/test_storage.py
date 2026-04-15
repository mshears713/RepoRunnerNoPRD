"""Tests for the JSON file storage layer."""

import json
import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect all storage operations to a temp directory."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-import settings so the env var is picked up
    import importlib
    import config
    importlib.reload(config)
    import storage
    importlib.reload(storage)
    return tmp_path


def _storage():
    import storage
    return storage


def test_create_and_get_scan():
    s = _storage()
    data = {"status": "pending", "repo_url": "https://github.com/foo/bar"}
    result = s.create_scan("abc123", data)
    assert result["id"] == "abc123"
    assert result["status"] == "pending"
    assert "created_at" in result

    fetched = s.get_scan("abc123")
    assert fetched["repo_url"] == "https://github.com/foo/bar"


def test_create_scan_duplicate_raises():
    s = _storage()
    s.create_scan("dup1", {"status": "pending"})
    with pytest.raises(FileExistsError):
        s.create_scan("dup1", {"status": "pending"})


def test_get_scan_missing_returns_none():
    s = _storage()
    assert s.get_scan("nonexistent") is None


def test_update_scan_flat_field():
    s = _storage()
    s.create_scan("upd1", {"status": "pending"})
    updated = s.update_scan("upd1", status="running")
    assert updated["status"] == "running"
    assert s.get_scan("upd1")["status"] == "running"


def test_update_scan_nested_field():
    s = _storage()
    s.create_scan("upd2", {"status": "pending", "timeline": {}})
    s.update_scan("upd2", **{"timeline.forked_at": "2026-01-01T00:00:00Z"})
    fetched = s.get_scan("upd2")
    assert fetched["timeline"]["forked_at"] == "2026-01-01T00:00:00Z"


def test_update_scan_creates_nested_dict_if_missing():
    s = _storage()
    s.create_scan("upd3", {"status": "pending"})
    s.update_scan("upd3", **{"cleanup.codespace_deleted": True})
    fetched = s.get_scan("upd3")
    assert fetched["cleanup"]["codespace_deleted"] is True


def test_update_scan_missing_raises():
    s = _storage()
    with pytest.raises(FileNotFoundError):
        s.update_scan("ghost", status="running")


def test_list_scans_returns_all():
    s = _storage()
    for i in range(3):
        s.create_scan(f"scan{i}", {"status": "completed"})
    results = s.list_scans()
    assert len(results) == 3


def test_list_scans_filters_by_status():
    s = _storage()
    s.create_scan("s1", {"status": "completed"})
    s.create_scan("s2", {"status": "failed"})
    s.create_scan("s3", {"status": "completed"})
    completed = s.list_scans(status="completed")
    assert len(completed) == 2
    failed = s.list_scans(status="failed")
    assert len(failed) == 1


def test_list_scans_pagination():
    s = _storage()
    for i in range(5):
        s.create_scan(f"pg{i}", {"status": "pending"})
    page1 = s.list_scans(limit=2, offset=0)
    page2 = s.list_scans(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # No overlap
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert ids1.isdisjoint(ids2)


def test_delete_scan():
    s = _storage()
    s.create_scan("del1", {"status": "pending"})
    assert s.delete_scan("del1") is True
    assert s.get_scan("del1") is None


def test_delete_scan_nonexistent_returns_false():
    s = _storage()
    assert s.delete_scan("nope") is False


def test_append_and_get_logs():
    s = _storage()
    s.create_scan("log1", {"status": "running"})
    s.append_log("log1", "fork", "system", "Forking repo...")
    s.append_log("log1", "execute", "stdout", "Server started on :8000")
    logs = s.get_logs("log1")
    assert len(logs) == 2
    assert logs[0]["stage"] == "fork"
    assert logs[1]["line"] == "Server started on :8000"


def test_get_logs_missing_scan_returns_empty():
    s = _storage()
    assert s.get_logs("nobody") == []
