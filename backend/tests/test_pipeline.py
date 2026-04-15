"""
Tests for ScanPipeline.
Uses SCANNER_MOCK_MODE=full so no external calls are made.
"""

import importlib
import os
import pytest


@pytest.fixture(autouse=True)
def tmp_data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCANNER_MOCK_MODE", "full")
    # Reload config + storage so env vars are picked up
    import config
    importlib.reload(config)
    import storage
    importlib.reload(storage)
    import pipeline
    importlib.reload(pipeline)


def _create_test_scan(scan_id: str) -> dict:
    import storage
    return storage.create_scan(
        scan_id,
        {
            "status": "pending",
            "repo_url": "https://github.com/testowner/testrepo",
            "repo_owner": "testowner",
            "repo_name": "testrepo",
            "input_metadata": {},
            "fork_repo_name": None,
            "codespace_name": None,
            "preview_url": None,
            "timeline": {},
            "execution": None,
            "analysis": None,
            "failure": None,
            "cleanup": {"codespace_deleted": False, "fork_deleted": False},
        },
    )


def test_mock_pipeline_completes():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-001")
    ScanPipeline().run("scan-001")

    scan = storage.get_scan("scan-001")
    assert scan["status"] == "completed"


def test_mock_pipeline_sets_timeline():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-002")
    ScanPipeline().run("scan-002")

    scan = storage.get_scan("scan-002")
    timeline = scan.get("timeline", {})
    assert timeline.get("forked_at")
    assert timeline.get("codespace_ready_at")
    assert timeline.get("started_at")
    assert timeline.get("finished_at")


def test_mock_pipeline_sets_execution():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-003")
    ScanPipeline().run("scan-003")

    scan = storage.get_scan("scan-003")
    execution = scan.get("execution", {})
    assert execution.get("stage_reached") == "started"
    assert execution.get("exit_code") == 0
    assert execution.get("port") == 8000


def test_mock_pipeline_sets_analysis():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-004")
    ScanPipeline().run("scan-004")

    scan = storage.get_scan("scan-004")
    analysis = scan.get("analysis", {})
    assert analysis is not None
    assert "what_it_does" in analysis


def test_mock_pipeline_sets_preview_url():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-005")
    ScanPipeline().run("scan-005")

    scan = storage.get_scan("scan-005")
    assert scan.get("preview_url") is not None


def test_mock_pipeline_marks_cleanup():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-006")
    ScanPipeline().run("scan-006")

    scan = storage.get_scan("scan-006")
    cleanup = scan.get("cleanup", {})
    assert cleanup.get("codespace_deleted") is True
    assert cleanup.get("fork_deleted") is True


def test_pipeline_handles_missing_scan_gracefully():
    """Running pipeline with a non-existent scan_id should not raise."""
    from pipeline import ScanPipeline
    ScanPipeline().run("nonexistent-scan-id")  # should not raise


def test_mock_pipeline_logs_are_written():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-007")
    ScanPipeline().run("scan-007")

    logs = storage.get_logs("scan-007")
    assert len(logs) > 0
    stages = {log["stage"] for log in logs}
    assert "fork" in stages
    assert "codespace" in stages
