import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
env_path = ROOT_DIR / ".env"
load_dotenv(dotenv_path=env_path)

print("=== ENV DEBUG ===")
print("ROOT_DIR:", ROOT_DIR)
print(".env path:", env_path)
print(".env exists:", env_path.exists())
print("GITHUB_TOKEN loaded:", os.getenv("GITHUB_TOKEN") is not None)
print("GITHUB_TOKEN length:", len(os.getenv("GITHUB_TOKEN") or ""))
print("=================")

token = os.getenv("GITHUB_TOKEN")
if not token:
    raise RuntimeError(f"GITHUB_TOKEN not loaded. Expected at: {env_path}")

DEFAULT_CODESPACE_TTL_SECONDS = 300  # 5 minutes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    github_token: str = ""
    github_fork_owner: str = ""
    gemini_api_key: str = ""
    data_dir: str = "./data"

    # Pipeline timeouts (seconds)
    fork_poll_timeout: int = 120
    codespace_ready_timeout: int = 300
    execution_timeout: int = 180
    default_codespace_ttl_seconds: int = DEFAULT_CODESPACE_TTL_SECONDS

    # Mocking
    scanner_mock_mode: str = "off"  # "full" | "no_codespace" | "off"


settings = Settings()
