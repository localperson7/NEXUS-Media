import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NEXUS Media API"
    app_version: str = "0.1.0-beta"
    host: str = "127.0.0.1"
    port: int = 8000

    # Safety & resource limits
    max_file_size_bytes: int = 500 * 1024 * 1024  # 500 MB
    max_duration_seconds: int = 3600  # 60 minutes
    max_concurrent_jobs: int = 3
    job_ttl_seconds: int = 3600  # 1 hour retention for temporary files
    rate_limit_per_minute: int = 45
    subprocess_timeout_seconds: int = 300  # 5 minutes per job

    # Storage & frontend paths
    storage_root: Path = Path(__file__).resolve().parent.parent / "tmp_jobs"
    database_path: Path = (
        Path(__file__).resolve().parent.parent / "storage" / "nexus_media.db"
    )
    frontend_dist_dir: Path = (
        Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    )

    # Optional private access protection (recommended when exposing over Tailscale Serve)
    access_token: Optional[str] = None

    # Security flags (never enable allow_loopback in production)
    allow_loopback_for_tests: bool = False

    model_config = SettingsConfigDict(env_prefix="NEXUS_MEDIA_", extra="ignore")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


settings = Settings()
ensure_private_dir(settings.storage_root)
ensure_private_dir(settings.database_path.parent)
