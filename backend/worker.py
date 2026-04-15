"""
ARQ worker entrypoint.
Run with: python worker.py  (or arq worker.WorkerSettings)
"""

from arq import cron
from arq.connections import RedisSettings

from config import settings
from jobs import cleanup_codespaces, run_scan


class WorkerSettings:
    functions = [run_scan]
    cron_jobs = [
        cron(cleanup_codespaces, hour=None, minute={0, 30}),  # every 30 min
    ]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 900  # 15 minutes hard cap per job
    keep_result = 3600  # keep results for 1 hour


if __name__ == "__main__":
    import asyncio
    from arq import run_worker
    run_worker(WorkerSettings)
