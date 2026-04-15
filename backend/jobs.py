"""
ARQ job definitions.
  run_scan   — main pipeline job
  cleanup    — periodic task to delete old Codespaces
"""

import logging

import storage
from config import settings
from pipeline import ScanPipeline

logger = logging.getLogger(__name__)


async def run_scan(ctx: dict, scan_id: str) -> None:
    """Entry point called by ARQ worker for each scan job."""
    logger.info("Starting scan job: %s", scan_id)
    try:
        pipeline = ScanPipeline()
        pipeline.run(scan_id)
        logger.info("Scan job complete: %s", scan_id)
    except Exception:
        logger.exception("Scan job %s raised an unhandled exception", scan_id)
        scan = storage.get_scan(scan_id)
        if scan and scan.get("status") not in ("completed", "failed"):
            storage.update_scan(scan_id, status="failed", error="Unhandled worker exception")


async def cleanup_codespaces(ctx: dict) -> None:
    """
    Periodic cleanup: find completed scans whose Codespaces haven't been deleted yet
    and delete them. Runs every 30 minutes via ARQ cron.
    """
    from codespaces_client import CodespacesClient

    cs_client = CodespacesClient()
    stale = storage.find_scans_for_cleanup(older_than_seconds=3600)
    logger.info("Cleanup: found %d scans with un-deleted Codespaces", len(stale))

    for scan in stale:
        cs_name = scan.get("codespace_name")
        if cs_name:
            deleted = cs_client.delete_codespace(cs_name)
            storage.update_scan(scan["id"], **{"cleanup.codespace_deleted": deleted})
            logger.info("Cleanup: codespace %s deleted=%s", cs_name, deleted)
