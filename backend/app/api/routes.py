"""
API Routes
POST /api/analyze       — detect all audio streams
POST /api/download/start — start a download job
GET  /api/download/status/{job_id} — poll job status
GET  /api/download/file/{filename} — serve completed file
DELETE /api/download/job/{job_id} — cancel / cleanup
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings
from app.models.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    DownloadFormat,
    DownloadRequest,
    JobStatus,
)
from app.services.analyzer import analyze_url
from app.services.downloader import (
    cleanup_old_files,
    create_job,
    get_job,
    start_download,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Analyze ──────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest):
    """
    Analyze a YouTube URL and return all audio streams.
    The response includes:
    - All detected audio streams (sorted by bitrate desc)
    - The highest available quality (best_quality)
    - Whether 320 kbps is actually achievable (can_offer_320)
    - The allowed MP3 bitrate options (never exceeds source bitrate)
    """
    try:
        result = await analyze_url(request.url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error during analyze: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again."
        )


# ─── Download ─────────────────────────────────────────────────────────────────

@router.post("/download/start", response_model=JobStatus)
async def download_start(request: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Start an audio download job.

    - format=original: downloads the best audio stream without conversion
    - format=mp3: converts to MP3 at the specified bitrate

    IMPORTANT: The mp3_bitrate must be within the allowed_mp3_options returned
    by /analyze. The server will re-validate this.

    Returns a job_id for polling status.
    """
    # Re-analyze to get fresh allowed options (prevents bitrate forgery)
    try:
        analysis = await analyze_url(request.url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Validate MP3 bitrate server-side
    if request.format == DownloadFormat.MP3:
        if request.mp3_bitrate is None:
            raise HTTPException(
                status_code=422,
                detail="mp3_bitrate is required when format is mp3."
            )
        if request.mp3_bitrate not in analysis.allowed_mp3_options:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"MP3 {request.mp3_bitrate} kbps exceeds the source audio quality "
                    f"({analysis.best_quality.bitrate} kbps). "
                    f"Allowed options: {analysis.allowed_mp3_options} kbps."
                )
            )

    job_id = create_job()

    # Dispatch: Celery if enabled, else background thread
    if settings.USE_CELERY:
        _dispatch_celery(
            job_id=job_id,
            url=request.url,
            fmt=request.format,
            mp3_bitrate=request.mp3_bitrate,
            allowed_mp3_options=analysis.allowed_mp3_options,
            title=analysis.title,
        )
    else:
        background_tasks.add_task(
            start_download,
            job_id=job_id,
            url=request.url,
            fmt=request.format,
            mp3_bitrate=request.mp3_bitrate,
            allowed_mp3_options=analysis.allowed_mp3_options,
            title=analysis.title,
        )

    # Trigger old file cleanup
    background_tasks.add_task(cleanup_old_files)

    return get_job(job_id)


@router.get("/download/status/{job_id}", response_model=JobStatus)
async def download_status(job_id: str):
    """Poll the status of a download job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job


@router.get("/download/file/{filename}")
async def download_file(filename: str):
    """Serve a completed download file."""
    # Prevent path traversal
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(settings.DOWNLOADS_DIR, safe_filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found or has expired.")

    # Guess media type
    ext = os.path.splitext(safe_filename)[1].lower()
    media_types = {
        ".mp3": "audio/mpeg",
        ".webm": "audio/webm",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".opus": "audio/opus",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=safe_filename,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.delete("/download/job/{job_id}")
async def delete_job(job_id: str):
    """Clean up a completed job and its associated file."""
    from app.services.downloader import _jobs
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    # Delete file if it exists
    if job.filename:
        file_path = os.path.join(settings.DOWNLOADS_DIR, job.filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    del _jobs[job_id]
    return {"deleted": job_id}


def _dispatch_celery(job_id, url, fmt, mp3_bitrate, allowed_mp3_options, title):
    """Dispatch download task to Celery worker."""
    try:
        from app.workers.celery_app import get_celery_app
        app = get_celery_app()
        if app:
            app.send_task(
                "ytdl.download",
                kwargs=dict(
                    job_id=job_id,
                    url=url,
                    fmt=fmt.value,
                    mp3_bitrate=mp3_bitrate,
                    allowed_mp3_options=allowed_mp3_options,
                    title=title,
                ),
            )
        else:
            raise RuntimeError("Celery not available.")
    except Exception as e:
        logger.error("Celery dispatch failed: %s", e)
        raise HTTPException(status_code=503, detail="Task queue unavailable.")
