import os
from functools import lru_cache
from pathlib import Path


class Settings:
    """Environment-backed service settings."""

    def __init__(self) -> None:
        self.database_url = os.getenv("TENSORDATA_DATABASE_URL", "sqlite:///./data/tensordata.db")
        self.storage_root = Path(os.getenv("TENSORDATA_STORAGE_ROOT", "./data/artifacts")).resolve()
        self.api_key = os.getenv("TENSORDATA_API_KEY", "")
        self.max_upload_bytes = int(os.getenv("TENSORDATA_MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
        self.auto_create_schema = os.getenv("TENSORDATA_AUTO_CREATE_SCHEMA", "true").lower() in {
            "1", "true", "yes", "on"
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
