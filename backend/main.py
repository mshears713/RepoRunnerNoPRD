import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
            import storage
            from codespaces_client import CodespacesClient
            stale = storage.find_scans_for_cleanup(older_than_seconds=3600)
            if stale:
                cs_client = CodespacesClient()
                for scan in stale:
                    cs_name = scan.get("codespace_name")
                    if cs_name:
                        deleted = cs_client.delete_codespace(cs_name)
                        storage.update_scan(scan["id"], **{"cleanup.codespace_deleted": deleted})
                        logger.info("Cleanup: codespace %s deleted=%s", cs_name, deleted)
        except Exception:
            logger.exception("Error in cleanup loop")
        await asyncio.sleep(1800)  # run every 30 minutes


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
