"""
Audio Analyzer Service
Uses yt-dlp to detect all audio streams and their qualities.
Never assumes a fixed maximum bitrate.
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional, Tuple
from functools import lru_cache

from app.core.config import settings
from app.models.schemas import AnalyzeResponse, AudioStream, BestQuality

logger = logging.getLogger(__name__)


def _format_duration(seconds: int) -> str:
    """Convert seconds to MM:SS or H:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _estimate_size_mb(bitrate_kbps: int, duration_seconds: int) -> float:
    """Rough size estimate: bitrate * duration / 8 / 1024."""
    return round((bitrate_kbps * 1000 * duration_seconds) / 8 / 1024 / 1024, 1)


def _build_ytdlp_opts(extra: dict = None) -> dict:
    """Build base yt-dlp options dict."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    if settings.YTDLP_COOKIES_FILE:
        opts["cookiefile"] = settings.YTDLP_COOKIES_FILE
    if settings.YTDLP_PROXY:
        opts["proxy"] = settings.YTDLP_PROXY
    if extra:
        opts.update(extra)
    return opts


def _extract_audio_streams(info: dict, duration_seconds: int) -> List[AudioStream]:
    """
    Extract and deduplicate all audio-only streams from yt-dlp info dict.
    Returns streams sorted by bitrate descending.
    """
    formats = info.get("formats", [])
    seen: Dict[Tuple[str, int], bool] = {}
    streams: List[AudioStream] = []

    for fmt in formats:
        # Only audio-only formats (no video stream)
        if fmt.get("vcodec", "none") not in (None, "none"):
            continue
        acodec = fmt.get("acodec", "")
        if not acodec or acodec == "none":
            continue

        # Normalize codec name
        codec = _normalize_codec(acodec)

        # Get bitrate — prefer abr (audio bitrate) over tbr (total bitrate)
        bitrate = int(fmt.get("abr") or fmt.get("tbr") or 0)
        if bitrate < 1:
            continue

        container = fmt.get("ext", "unknown")

        key = (codec, bitrate)
        if key in seen:
            continue
        seen[key] = True

        size_mb = _estimate_size_mb(bitrate, duration_seconds)
        streams.append(AudioStream(
            codec=codec,
            bitrate=bitrate,
            format=container,
            size_estimate_mb=size_mb,
        ))

    # Sort by bitrate descending
    streams.sort(key=lambda s: s.bitrate, reverse=True)

    # Mark best
    if streams:
        streams[0].is_best = True

    return streams


def _normalize_codec(acodec: str) -> str:
    """Map raw codec identifiers to human-readable names."""
    acodec = acodec.lower()
    if "opus" in acodec:
        return "Opus"
    if "mp4a" in acodec or "aac" in acodec:
        return "AAC"
    if "vorbis" in acodec:
        return "Vorbis"
    if "mp3" in acodec:
        return "MP3"
    if "flac" in acodec:
        return "FLAC"
    if "wav" in acodec or "pcm" in acodec:
        return "WAV"
    return acodec.upper()


def _compute_allowed_mp3_options(source_bitrate_kbps: int) -> List[int]:
    """
    Return only MP3 bitrates <= source bitrate.
    Never offer upscaling.
    """
    return [
        tier for tier in settings.MP3_BITRATE_TIERS
        if tier <= source_bitrate_kbps
    ]


def analyze_url_sync(url: str) -> AnalyzeResponse:
    """
    Synchronous analysis — runs yt-dlp in-process.
    Called from the async wrapper via run_in_executor.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        )

    ydl_opts = _build_ytdlp_opts()

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        _handle_ytdlp_error(e)

    if not info:
        raise ValueError("Could not extract video information.")

    # Duration
    duration_seconds = int(info.get("duration") or 0)
    if duration_seconds > settings.MAX_DURATION_SECONDS:
        raise ValueError(
            f"Video is too long ({_format_duration(duration_seconds)}). "
            f"Maximum allowed: {_format_duration(settings.MAX_DURATION_SECONDS)}."
        )

    # Audio streams
    streams = _extract_audio_streams(info, duration_seconds)

    if not streams:
        # Fallback: try to infer from top-level metadata
        streams = _fallback_stream_detection(info, duration_seconds)

    if not streams:
        raise ValueError("No audio streams detected in this video.")

    best = streams[0]
    allowed_mp3 = _compute_allowed_mp3_options(best.bitrate)

    return AnalyzeResponse(
        title=info.get("title", "Unknown Title"),
        duration=_format_duration(duration_seconds),
        duration_seconds=duration_seconds,
        thumbnail=info.get("thumbnail"),
        channel=info.get("uploader") or info.get("channel", "Unknown"),
        best_quality=BestQuality(
            codec=best.codec,
            bitrate=best.bitrate,
            format=best.format,
        ),
        can_offer_320=best.bitrate >= 320,
        audio_streams=streams,
        allowed_mp3_options=allowed_mp3,
    )


def _fallback_stream_detection(info: dict, duration_seconds: int) -> List[AudioStream]:
    """
    Fallback: extract audio info from formats that have both video+audio,
    or from the top-level info dict.
    """
    logger.warning("Using fallback audio stream detection.")
    streams = []

    for fmt in info.get("formats", []):
        acodec = fmt.get("acodec", "")
        if not acodec or acodec == "none":
            continue
        bitrate = int(fmt.get("abr") or 0)
        if bitrate < 1:
            # Try to get from audio quality field
            audio_quality = fmt.get("audio_quality")
            if audio_quality:
                try:
                    bitrate = int(re.search(r"\d+", str(audio_quality)).group())
                except Exception:
                    continue
        if bitrate < 1:
            continue

        codec = _normalize_codec(acodec)
        container = fmt.get("ext", "unknown")
        streams.append(AudioStream(
            codec=codec,
            bitrate=bitrate,
            format=container,
            size_estimate_mb=_estimate_size_mb(bitrate, duration_seconds),
        ))

    # Deduplicate
    seen = set()
    unique = []
    for s in streams:
        k = (s.codec, s.bitrate)
        if k not in seen:
            seen.add(k)
            unique.append(s)

    unique.sort(key=lambda s: s.bitrate, reverse=True)
    if unique:
        unique[0].is_best = True
    return unique


def _handle_ytdlp_error(exc: Exception):
    """Convert yt-dlp exceptions to user-friendly errors."""
    msg = str(exc).lower()
    if "private" in msg:
        raise ValueError("This video is private and cannot be accessed.")
    if "age" in msg:
        raise ValueError("This video has age restrictions. Cookies may be required.")
    if "unavailable" in msg or "deleted" in msg:
        raise ValueError("This video is unavailable or has been deleted.")
    if "copyright" in msg:
        raise ValueError("This video is blocked due to copyright restrictions.")
    if "sign in" in msg or "login" in msg:
        raise ValueError("YouTube requires sign-in for this video.")
    if "429" in msg or "too many" in msg:
        raise ValueError("YouTube rate limited this request. Please try again later.")
    logger.error("yt-dlp error: %s", exc, exc_info=True)
    raise ValueError(f"Could not retrieve video information: {exc}")


async def analyze_url(url: str) -> AnalyzeResponse:
    """Async wrapper — runs sync yt-dlp in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, analyze_url_sync, url)
