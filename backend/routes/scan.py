"""
/api/scan  — scan submission, retrieval, deletion, and SSE stream.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

import storage
from cleanup import cleanup_scan_resources
from config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------

class ScanRequest(BaseModel):
    repo_url: str
    summary: str | None = None
    reason_selected: str | None = None
    tags: list[str] | None = None
    priority: str | None = None

    @field_validator("repo_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("repo_url must be an http/https URL")
        if "github.com" not in parsed.netloc:
            raise ValueError("repo_url must be a github.com URL")
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2 or not parts[1]:
            raise ValueError("repo_url must include owner and repo name")
        return v.rstrip("/")


class TTLRequest(BaseModel):
    ttl_seconds: int

    @field_validator("ttl_seconds")
    @classmethod
    def validate_ttl(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("ttl_seconds must be > 0")
        return v


class RerunRequest(BaseModel):
    ttl_seconds: int | None = None

    @field_validator("ttl_seconds")
    @classmethod
    def validate_optional_ttl(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("ttl_seconds must be > 0")
        return v


def _parse_github_url(url: str) -> tuple[str, str]:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0], parts[1]


def _tl(scan_id: str, step: str, status: str, message: str) -> None:
    """Add a timeline step and emit a structured log line."""
    storage.add_timeline_step(scan_id, step, status, message)
    logger.info("[%s] [%s] [%s] %s", scan_id, step, status, message)


def _decorate_scan(scan: dict | None) -> dict | None:
    if scan is None:
        return None
    enriched = dict(scan)
    expires_at = enriched.get("codespace_expires_at")
    is_active = False
    if expires_at:
        try:
            is_active = (
                datetime.now(timezone.utc) < datetime.fromisoformat(expires_at)
                and not enriched.get("cleanup", {}).get("codespace_deleted", False)
            )
        except ValueError:
            is_active = False
    enriched["is_active"] = is_active
    return enriched


async def _run_pipeline(scan_id: str) -> None:
    """Run the blocking pipeline in a thread so it doesn't block the event loop."""
    from pipeline import ScanPipeline
    await asyncio.to_thread(ScanPipeline().run, scan_id)


@router.get("/debug/github")
async def debug_github() -> dict:
    from github_client import GitHubClient, GitHubDiagnosticsError

    try:
        return GitHubClient().get_debug_status()
    except GitHubDiagnosticsError as exc:
        raise HTTPException(status_code=500, detail=exc.to_failure()) from exc


# ------------------------------------------------------------------
# POST /api/scan
# ------------------------------------------------------------------

@router.post("/scan", status_code=201)
async def submit_scan(body: ScanRequest, background_tasks: BackgroundTasks) -> dict:
    owner, repo = _parse_github_url(body.repo_url)

    # Dedup: reject if same repo scanned in the last 24 hours
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for s in storage.list_scans(limit=500):
        if s.get("repo_owner") == owner and s.get("repo_name") == repo:
            try:
                ts = datetime.fromisoformat(s["created_at"])
                if ts > cutoff:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Repo {owner}/{repo} was already scanned recently (id={s['id']})",
                    )
            except ValueError:
                pass

    scan_id = str(uuid.uuid4())
    scan_data = {
        "status": "queued",
        "repo_url": body.repo_url,
        "repo_owner": owner,
        "repo_name": repo,
        "input_metadata": {
            "summary": body.summary,
            "reason_selected": body.reason_selected,
            "tags": body.tags or [],
            "priority": body.priority,
        },
        "fork_repo_name": None,
        "codespace_name": None,
        "preview_url": None,
        "accessible": False,
        "ttl_seconds": settings.default_codespace_ttl_seconds,
        "codespace_expires_at": None,
        "is_active": False,
        "timeline": [],
        "execution": None,
        "analysis": None,
        "failure": None,
        "error": None,
        "cleanup": {"codespace_deleted": False, "fork_deleted": False},
    }
    storage.create_scan(scan_id, scan_data)

    # Immediately record observable pre-pipeline steps so timeline is never empty
    _tl(scan_id, "received_request", "completed", f"Scan request received for {owner}/{repo}")
    _tl(scan_id, "parse_repo_url", "completed", f"Extracted owner={owner} repo={repo}")
    _tl(scan_id, "validate_repo_url", "completed", f"URL validated: {body.repo_url}")

    scan = _decorate_scan(storage.get_scan(scan_id))
    background_tasks.add_task(_run_pipeline, scan_id)

    return {"id": scan_id, "status": "queued", "created_at": scan["created_at"]}


# ------------------------------------------------------------------
# GET /api/scan
# ------------------------------------------------------------------

@router.get("/scan")
async def list_scans(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    scans = [
        _decorate_scan(s)
        for s in storage.list_scans(status=status, limit=limit, offset=offset)
    ]
    total = len(storage.list_scans(status=status, limit=10000))
    return {"items": scans, "total": total}


# ------------------------------------------------------------------
# GET /api/scan/:id
# ------------------------------------------------------------------

@router.get("/scan/{scan_id}")
async def get_scan(scan_id: str) -> dict:
    scan = _decorate_scan(storage.get_scan(scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


# ------------------------------------------------------------------
# DELETE /api/scan/:id
# ------------------------------------------------------------------

@router.delete("/scan/{scan_id}", status_code=204)
async def delete_scan(scan_id: str) -> None:
    scan = storage.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    cleanup_scan_resources(scan_id, reason="delete_scan")

    storage.delete_scan(scan_id)


@router.post("/scan/{scan_id}/rerun", status_code=201)
async def rerun_scan(scan_id: str, body: RerunRequest, background_tasks: BackgroundTasks) -> dict:
    source = storage.get_scan(scan_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    owner, repo = source["repo_owner"], source["repo_name"]
    new_scan_id = str(uuid.uuid4())
    ttl_seconds = (
        body.ttl_seconds
        or source.get("ttl_seconds")
        or settings.default_codespace_ttl_seconds
    )
    scan_data = {
        "status": "queued",
        "repo_url": source["repo_url"],
        "repo_owner": owner,
        "repo_name": repo,
        "input_metadata": source.get("input_metadata", {}),
        "fork_repo_name": None,
        "codespace_name": None,
        "preview_url": None,
        "accessible": False,
        "ttl_seconds": ttl_seconds,
        "codespace_expires_at": None,
        "is_active": False,
        "timeline": [],
        "execution": None,
        "analysis": None,
        "failure": None,
        "error": None,
        "cleanup": {"codespace_deleted": False, "fork_deleted": False},
    }
    storage.create_scan(new_scan_id, scan_data)
    _tl(new_scan_id, "rerun_started", "started", f"Rerun started from scan {scan_id}")
    _tl(new_scan_id, "rerun_completed", "completed", "Rerun queued")
    background_tasks.add_task(_run_pipeline, new_scan_id)
    created = _decorate_scan(storage.get_scan(new_scan_id))
    return {"id": new_scan_id, "status": "queued", "created_at": created["created_at"]}


@router.post("/scan/{scan_id}/extend")
async def extend_scan_runtime(scan_id: str, body: TTLRequest) -> dict:
    scan = storage.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    expires_at = scan.get("codespace_expires_at")
    if not expires_at:
        raise HTTPException(status_code=400, detail="codespace_expires_at is not set yet")
    try:
        expires_ts = datetime.fromisoformat(expires_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="codespace_expires_at is invalid") from exc

    updated_expiry = expires_ts + timedelta(seconds=body.ttl_seconds)
    storage.update_scan(scan_id, codespace_expires_at=updated_expiry.isoformat(), is_active=True)
    storage.add_timeline_step(
        scan_id,
        "codespace_expiration_set",
        "completed",
        f"Codespace expiration extended by {body.ttl_seconds}s",
        details={"codespace_expires_at": updated_expiry.isoformat()},
    )
    return {
        "scan_id": scan_id,
        "codespace_expires_at": updated_expiry.isoformat(),
        "is_active": True,
    }


@router.delete("/scan/{scan_id}/cleanup")
async def cleanup_scan(scan_id: str) -> dict:
    scan = storage.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    result = cleanup_scan_resources(scan_id, reason="manual_api")
    return {"scan_id": scan_id, "cleanup": result}


# ------------------------------------------------------------------
# GET /api/scan/:id/stream  (Server-Sent Events)
# ------------------------------------------------------------------

@router.get("/scan/{scan_id}/stream")
async def stream_scan(scan_id: str) -> StreamingResponse:
    scan = storage.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    return StreamingResponse(
        _sse_generator(scan_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(scan_id: str):
    """Yield SSE events until the scan reaches a terminal state."""
    terminal = {"completed", "failed"}
    last_status = None
    emitted_steps = 0  # index into the timeline list up to which we've emitted

    while True:
        scan = storage.get_scan(scan_id)
        if scan is None:
            yield _sse_event("error", {"message": "Scan not found"})
            return

        status = scan.get("status")
        timeline = scan.get("timeline", [])
        if not isinstance(timeline, list):
            timeline = []

        # Emit stage_update events for newly appended timeline steps
        for step_entry in timeline[emitted_steps:]:
            yield _sse_event("stage_update", step_entry)
        emitted_steps = len(timeline)

        # Emit status change events
        if status != last_status:
            last_status = status
            if status in terminal:
                event_type = "completed" if status == "completed" else "failed"
                yield _sse_event(event_type, scan)
                return
            else:
                yield _sse_event("status_update", {"status": status})

        yield ": keep-alive\n\n"
        await asyncio.sleep(2)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
