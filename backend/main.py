from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes.scan import router as scan_router

app = FastAPI(title="Repo Viability Scanner", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router, prefix="/api")


@app.get("/api/health")
async def health():
    redis_ok = False
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.ping()
        await pool.aclose()
        redis_ok = True
    except Exception:
        pass
    return {"status": "ok", "redis": "ok" if redis_ok else "unavailable"}
