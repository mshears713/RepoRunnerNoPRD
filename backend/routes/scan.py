"""
/api/scan  — scan submission, retrieval, deletion, and SSE stream.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

import storage
from config import settings

router = APIRouter()


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
        if len(parts) < 2:
            raise ValueError("repo_url must include owner and repo name")
        return v.rstrip("/")


def _parse_github_url(url: str) -> tuple[str, str]:
    parts = urlparse(url).path.strip("/").split("/")
    return parts[0], parts[1]


# ------------------------------------------------------------------
# POST /api/scan
# ------------------------------------------------------------------

@router.post("/scan", status_code=201)
async def submit_scan(body: ScanRequest) -> dict:
    owner, repo = _parse_github_url(body.repo_url)

    # Dedup: reject if same repo scanned in the last 24 hours
    existing = storage.list_scans(limit=500)
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for s in existing:
        if s.get("repo_owner") == owner and s.get("repo_name") == repo:
            created = s.get("created_at", "")
            try:
                ts = datetime.fromisoformat(created)
                if ts > cutoff:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Repo {owner}/{repo} was already scanned recently (id={s['id']})",
                    )
            except ValueError:
                pass

    scan_id = str(uuid.uuid4())
    scan_data = {
        "status": "pending",
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
        "timeline": {},
        "execution": None,
        "analysis": None,
        "failure": None,
        "cleanup": {"codespace_deleted": False, "fork_deleted": False},
    }
    scan = storage.create_scan(scan_id, scan_data)

    # Enqueue the background job
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await redis.enqueue_job("run_scan", scan_id)
    await redis.aclose()

    return {"id": scan_id, "status": "pending", "created_at": scan["created_at"]}


# ------------------------------------------------------------------
# GET /api/scan
# ------------------------------------------------------------------

@router.get("/scan")
async def list_scans(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    scans = storage.list_scans(status=status, limit=limit, offset=offset)
    all_scans = storage.list_scans(status=status, limit=10000)
    return {"items": scans, "total": len(all_scans)}


# ------------------------------------------------------------------
# GET /api/scan/:id
# ------------------------------------------------------------------

@router.get("/scan/{scan_id}")
async def get_scan(scan_id: str) -> dict:
    scan = storage.get_scan(scan_id)
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

    # Trigger async cleanup of Codespace/fork if still alive
    cs_name = scan.get("codespace_name")
    fork_name = scan.get("fork_repo_name")
    if cs_name and not scan.get("cleanup", {}).get("codespace_deleted"):
        try:
            from codespaces_client import CodespacesClient
            CodespacesClient().delete_codespace(cs_name)
        except Exception:
            pass
    if fork_name and not scan.get("cleanup", {}).get("fork_deleted"):
        try:
            from github_client import GitHubClient
            GitHubClient().delete_fork(fork_name)
        except Exception:
            pass

    storage.delete_scan(scan_id)


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
    last_timeline = {}
    poll_interval = 2  # seconds

    while True:
        scan = storage.get_scan(scan_id)
        if scan is None:
            yield _sse_event("error", {"message": "Scan not found"})
            return

        status = scan.get("status")
        timeline = scan.get("timeline", {})

        # Emit stage_update events for newly completed timeline milestones
        for key, ts in timeline.items():
            if ts and last_timeline.get(key) != ts:
                yield _sse_event("stage_update", {"stage": key, "timestamp": ts})
                last_timeline[key] = ts

        # Emit status change events
        if status != last_status:
            last_status = status
            if status in terminal:
                event_type = "completed" if status == "completed" else "failed"
                yield _sse_event(event_type, scan)
                return
            else:
                yield _sse_event("status_update", {"status": status})

        # Keep-alive comment
        yield ": keep-alive\n\n"

        await asyncio.sleep(poll_interval)


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
