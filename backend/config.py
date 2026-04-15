from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    github_token: str = ""
    github_fork_owner: str = ""
    gemini_api_key: str = ""
    data_dir: str = "./data"
    redis_url: str = "redis://localhost:6379"

    # Pipeline timeouts (seconds)
    fork_poll_timeout: int = 120
    codespace_ready_timeout: int = 300
    execution_timeout: int = 180

    # Mocking
    scanner_mock_mode: str = "off"  # "full" | "no_codespace" | "off"


settings = Settings()
