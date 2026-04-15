"""
Integration tests for the FastAPI API layer.
Uses TestClient and a temp data directory. No Redis required.
"""

import importlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def tmp_data_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCANNER_MOCK_MODE", "full")
    import config
    importlib.reload(config)
    import storage
    importlib.reload(storage)


@pytest.fixture
def client():
    # Patch _run_pipeline so no real background thread is started during tests
    with patch("routes.scan._run_pipeline", new=AsyncMock()):
        import importlib

        import main
        importlib.reload(main)
        from main import app
        with TestClient(app) as c:
            yield c


def test_health_check(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_submit_scan_minimal(client):
    resp = client.post("/api/scan", json={"repo_url": "https://github.com/owner/repo"})
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "pending"


def test_submit_scan_enriched(client):
    resp = client.post(
        "/api/scan",
        json={
            "repo_url": "https://github.com/tiangolo/fastapi",
            "summary": "FastAPI framework",
            "reason_selected": "Popular Python API framework",
            "tags": ["python", "api"],
            "priority": "high",
        },
    )
    assert resp.status_code == 201


def test_submit_scan_invalid_url(client):
    resp = client.post("/api/scan", json={"repo_url": "not-a-url"})
    assert resp.status_code == 422


def test_submit_scan_non_github_url(client):
    resp = client.post("/api/scan", json={"repo_url": "https://gitlab.com/owner/repo"})
    assert resp.status_code == 422


def test_submit_scan_url_missing_repo(client):
    resp = client.post("/api/scan", json={"repo_url": "https://github.com/owner"})
    assert resp.status_code == 422


def test_get_scan(client):
    resp = client.post("/api/scan", json={"repo_url": "https://github.com/foo/bar"})
    scan_id = resp.json()["id"]

    resp = client.get(f"/api/scan/{scan_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == scan_id
    assert data["repo_owner"] == "foo"
    assert data["repo_name"] == "bar"


def test_get_scan_not_found(client):
    resp = client.get("/api/scan/nonexistent-id")
    assert resp.status_code == 404


def test_list_scans(client):
    client.post("/api/scan", json={"repo_url": "https://github.com/a/repo1"})
    client.post("/api/scan", json={"repo_url": "https://github.com/b/repo2"})

    resp = client.get("/api/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2


def test_list_scans_status_filter(client):
    client.post("/api/scan", json={"repo_url": "https://github.com/c/repo3"})

    resp = client.get("/api/scan?status=pending")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(s["status"] == "pending" for s in items)


def test_delete_scan(client):
    resp = client.post("/api/scan", json={"repo_url": "https://github.com/d/repo4"})
    scan_id = resp.json()["id"]

    resp = client.delete(f"/api/scan/{scan_id}")
    assert resp.status_code == 204

    resp = client.get(f"/api/scan/{scan_id}")
    assert resp.status_code == 404


def test_delete_scan_not_found(client):
    resp = client.delete("/api/scan/does-not-exist")
    assert resp.status_code == 404


def test_dedup_same_repo_within_24h(client):
    url = "https://github.com/dedup/testrepo"
    resp1 = client.post("/api/scan", json={"repo_url": url})
    assert resp1.status_code == 201

    resp2 = client.post("/api/scan", json={"repo_url": url})
    assert resp2.status_code == 409
