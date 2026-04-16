import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import storage
from cleanup import cleanup_scan_resources
from routes.scan import router as scan_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the cleanup background task when the server starts."""
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Repo Viability Scanner", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router, prefix="/api")


async def _cleanup_loop() -> None:
    while True:
        try:
            now = datetime.now(timezone.utc)
            for scan in storage.list_scans(limit=1000):
                if scan.get("status") not in ("completed", "failed"):
                    continue
                if not scan.get("is_active"):
                    continue
                expires_at = scan.get("codespace_expires_at")
                if not expires_at:
                    continue
                try:
                    expires_ts = datetime.fromisoformat(expires_at)
                except ValueError:
                    continue
                if now > expires_ts:
                    result = cleanup_scan_resources(scan["id"], reason="ttl_expired")
                    logger.info("Cleanup: scan=%s result=%s", scan["id"], result)
        except Exception:
            logger.exception("Error in cleanup loop")
        await asyncio.sleep(1800)  # run every 30 minutes


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
