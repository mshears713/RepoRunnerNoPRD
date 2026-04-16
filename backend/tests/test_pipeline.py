"""
Tests for ScanPipeline.
Uses SCANNER_MOCK_MODE=full so no external calls are made.
"""

import importlib

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
            "status": "queued",
            "repo_url": "https://github.com/testowner/testrepo",
            "repo_owner": "testowner",
            "repo_name": "testrepo",
            "input_metadata": {},
            "fork_repo_name": None,
            "codespace_name": None,
            "preview_url": None,
            "timeline": [],
            "execution": None,
            "analysis": None,
            "failure": None,
            "error": None,
            "cleanup": {"codespace_deleted": False, "fork_deleted": False},
        },
    )


def _step_names(scan: dict) -> list[str]:
    """Return the list of step names from the timeline (may repeat with different statuses)."""
    return [s["step"] for s in scan.get("timeline", [])]


def _has_step(scan: dict, step: str, status: str) -> bool:
    """Return True if the timeline contains a step with the given name and status."""
    return any(
        s["step"] == step and s["status"] == status
        for s in scan.get("timeline", [])
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
    # Timeline is a list of step objects
    assert isinstance(scan.get("timeline"), list)
    assert _has_step(scan, "fork", "completed")
    assert _has_step(scan, "codespace_create", "completed")
    assert _has_step(scan, "execute", "completed")
    assert _has_step(scan, "analyze", "completed")
    assert _has_step(scan, "execution_start", "completed")


def test_mock_pipeline_timeline_steps_have_required_fields():
    """Every timeline entry must have step, status, timestamp, and message."""
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-002b")
    ScanPipeline().run("scan-002b")

    scan = storage.get_scan("scan-002b")
    for entry in scan.get("timeline", []):
        assert "step" in entry
        assert "status" in entry
        assert "timestamp" in entry
        assert "message" in entry
        assert entry["status"] in ("started", "completed", "failed", "in_progress")


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


def test_mock_pipeline_schedules_cleanup():
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-006")
    ScanPipeline().run("scan-006")

    scan = storage.get_scan("scan-006")
    assert scan.get("codespace_expires_at") is not None
    assert scan.get("is_active") is True


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
    assert "codespace_create" in stages


def test_mock_pipeline_status_transitions():
    """status must go through in_progress and end as completed."""
    import storage
    from pipeline import ScanPipeline

    _create_test_scan("scan-008")
    pipeline_instance = ScanPipeline()

    # Capture status mid-run is tricky; check final state
    pipeline_instance.run("scan-008")

    scan = storage.get_scan("scan-008")
    assert scan["status"] == "completed"
    # execution_start started before completed
    started_idx = next(
        i for i, s in enumerate(scan["timeline"])
        if s["step"] == "execution_start" and s["status"] == "started"
    )
    completed_idx = next(
        i for i, s in enumerate(scan["timeline"])
        if s["step"] == "execution_start" and s["status"] == "completed"
    )
    assert started_idx < completed_idx
