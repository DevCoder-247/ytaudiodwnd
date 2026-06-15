"""
Application Configuration
"""
import os
from pathlib import Path
from typing import List


class Settings:
    # App
    APP_NAME: str = "YT Audio Downloader"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DOWNLOADS_DIR: str = os.getenv("DOWNLOADS_DIR", str(BASE_DIR / "downloads"))
    TEMP_DIR: str = os.getenv("TEMP_DIR", str(BASE_DIR / "temp"))

    # CORS
    CORS_ORIGINS: List[str] = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173, https://ytaudiodwnd.vercel.app/"
    ).split(",")

    # Redis / Celery (optional — falls back to sync if Redis unavailable)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_CELERY: bool = os.getenv("USE_CELERY", "false").lower() == "true"

    # Download limits
    MAX_DURATION_SECONDS: int = int(os.getenv("MAX_DURATION_SECONDS", "1800"))  # 30 min
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "200"))
    DOWNLOAD_TIMEOUT_SECONDS: int = int(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "300"))

    # yt-dlp options
    YTDLP_COOKIES_FILE: str = os.getenv("YTDLP_COOKIES_FILE", "")
    YTDLP_PROXY: str = os.getenv("YTDLP_PROXY", "")

    # MP3 bitrate tiers (kbps) — ordered descending
    MP3_BITRATE_TIERS: List[int] = [320, 256, 192, 160, 128, 96, 64]

    # Cleanup: delete files older than N hours
    FILE_TTL_HOURS: int = int(os.getenv("FILE_TTL_HOURS", "2"))


settings = Settings()

# Ensure directories exist
os.makedirs(settings.DOWNLOADS_DIR, exist_ok=True)
os.makedirs(settings.TEMP_DIR, exist_ok=True)
