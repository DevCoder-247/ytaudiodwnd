"""
Download Service
Handles original audio extraction and MP3 conversion.
Enforces quality limits — never upscales.
"""
import asyncio
import logging
import os
import uuid
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from app.core.config import settings
from app.models.schemas import DownloadFormat, JobStatus

logger = logging.getLogger(__name__)

# In-memory job store (replace with Redis for multi-worker deployments)
_jobs: Dict[str, JobStatus] = {}


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    """Remove filesystem-unsafe characters."""
    import re
    safe = re.sub(r'[\\/*?:"<>|]', "_", name)
    safe = safe.strip(". ")
    return safe[:max_len] if safe else "audio"


def _build_ytdlp_opts_for_download(
    output_path: str,
    fmt: DownloadFormat,
    mp3_bitrate: Optional[int],
    progress_hook: Callable,
) -> dict:
    """Build yt-dlp options for actual download."""
    opts = {
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "noprogress": False,
        "retries": 3,
        "fragment_retries": 3,
        "file_access_retries": 3,
        "extractor_retries": 3,
        "socket_timeout": 30,
    }

    if settings.YTDLP_COOKIES_FILE:
        opts["cookiefile"] = settings.YTDLP_COOKIES_FILE
    if settings.YTDLP_PROXY:
        opts["proxy"] = settings.YTDLP_PROXY

    if fmt == DownloadFormat.ORIGINAL:
        # Download best audio stream without conversion
        opts["format"] = "bestaudio/best"
        # No postprocessors — preserve original codec & container
    else:
        # MP3 conversion
        assert mp3_bitrate is not None
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": str(mp3_bitrate),
        }]

    return opts


def create_job() -> str:
    """Create a new job entry and return job_id."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = JobStatus(job_id=job_id, status="pending", progress=0)
    return job_id


def get_job(job_id: str) -> Optional[JobStatus]:
    return _jobs.get(job_id)


def _download_sync(
    job_id: str,
    url: str,
    fmt: DownloadFormat,
    mp3_bitrate: Optional[int],
    allowed_mp3_options: list,
    title: str = "audio",
):
    """
    Synchronous download function — runs in a thread pool.
    """
    try:
        import yt_dlp
    except ImportError:
        _jobs[job_id].status = "error"
        _jobs[job_id].error = "yt-dlp is not installed."
        return

    # Validate MP3 bitrate against allowed options
    if fmt == DownloadFormat.MP3:
        if mp3_bitrate not in allowed_mp3_options:
            _jobs[job_id].status = "error"
            _jobs[job_id].error = (
                f"MP3 {mp3_bitrate} kbps is not allowed for this source. "
                f"Allowed: {allowed_mp3_options}"
            )
            return

    _jobs[job_id].status = "processing"
    _jobs[job_id].progress = 5

    safe_title = _sanitize_filename(title)
    suffix = f"_mp3_{mp3_bitrate}k" if fmt == DownloadFormat.MP3 else "_original"
    filename_base = f"{safe_title}{suffix}_{job_id[:8]}"
    output_template = os.path.join(settings.DOWNLOADS_DIR, f"{filename_base}.%(ext)s")

    def progress_hook(d: dict):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = int((downloaded / total) * 80) + 10  # 10–90%
                _jobs[job_id].progress = min(pct, 90)
        elif d["status"] == "finished":
            _jobs[job_id].progress = 92

    try:
        opts = _build_ytdlp_opts_for_download(
            output_template, fmt, mp3_bitrate, progress_hook
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        logger.error("Download failed for job %s: %s", job_id, e, exc_info=True)
        _jobs[job_id].status = "error"
        _jobs[job_id].error = _friendly_error(str(e))
        return

    # Find the produced file
    output_file = _find_output_file(settings.DOWNLOADS_DIR, filename_base)
    if not output_file:
        _jobs[job_id].status = "error"
        _jobs[job_id].error = "Download completed but output file not found."
        return

    _jobs[job_id].progress = 100
    _jobs[job_id].status = "done"
    _jobs[job_id].filename = os.path.basename(output_file)
    _jobs[job_id].download_url = f"/api/download/file/{os.path.basename(output_file)}"


def _find_output_file(directory: str, base: str) -> Optional[str]:
    """Find the file matching the base name in the output directory."""
    for fname in os.listdir(directory):
        if fname.startswith(base):
            return os.path.join(directory, fname)
    return None


def _friendly_error(msg: str) -> str:
    m = msg.lower()
    if "403" in m or "forbidden" in m:
        return "YouTube denied access. Try again or use cookies."
    if "429" in m:
        return "Rate limited by YouTube. Please wait a moment."
    if "network" in m or "connection" in m:
        return "Network error during download. Please try again."
    return f"Download error: {msg[:200]}"


async def start_download(
    job_id: str,
    url: str,
    fmt: DownloadFormat,
    mp3_bitrate: Optional[int],
    allowed_mp3_options: list,
    title: str = "audio",
):
    """Async wrapper — delegates to thread pool."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _download_sync,
        job_id, url, fmt, mp3_bitrate, allowed_mp3_options, title
    )


def cleanup_old_files():
    """Remove download files older than FILE_TTL_HOURS."""
    ttl_seconds = settings.FILE_TTL_HOURS * 3600
    now = time.time()
    removed = 0
    for fname in os.listdir(settings.DOWNLOADS_DIR):
        fpath = os.path.join(settings.DOWNLOADS_DIR, fname)
        if os.path.isfile(fpath):
            age = now - os.path.getmtime(fpath)
            if age > ttl_seconds:
                try:
                    os.remove(fpath)
                    removed += 1
                except OSError:
                    pass
    logger.info("Cleanup: removed %d old files.", removed)
