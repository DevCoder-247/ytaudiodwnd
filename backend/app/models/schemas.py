"""
Data Models & Schemas
"""
from pydantic import BaseModel, HttpUrl, field_validator
from typing import List, Optional
from enum import Enum


class AudioStream(BaseModel):
    codec: str
    bitrate: int          # kbps
    format: str           # webm, m4a, mp3, etc.
    size_estimate_mb: Optional[float] = None
    is_best: bool = False


class BestQuality(BaseModel):
    codec: str
    bitrate: int          # kbps
    format: str


class AnalyzeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        v = v.strip()
        allowed_domains = [
            "youtube.com", "www.youtube.com", "youtu.be",
            "music.youtube.com", "m.youtube.com"
        ]
        if not any(domain in v for domain in allowed_domains):
            raise ValueError("Only YouTube URLs are supported.")
        return v


class AnalyzeResponse(BaseModel):
    title: str
    duration: str              # "4:32"
    duration_seconds: int
    thumbnail: Optional[str]
    channel: str
    best_quality: BestQuality
    can_offer_320: bool        # True only if source >= 320 kbps
    audio_streams: List[AudioStream]
    allowed_mp3_options: List[int]   # kbps values, sorted desc
    quality_note: str = (
        "Download options are generated based on the highest audio quality "
        "available in the source video. Higher MP3 bitrates are hidden because "
        "they would not improve the original audio quality."
    )


class DownloadFormat(str, Enum):
    ORIGINAL = "original"
    MP3 = "mp3"


class DownloadRequest(BaseModel):
    url: str
    format: DownloadFormat = DownloadFormat.ORIGINAL
    mp3_bitrate: Optional[int] = None   # required when format == mp3

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if "youtube" not in v and "youtu.be" not in v:
            raise ValueError("Only YouTube URLs are supported.")
        return v

    def validate_mp3_bitrate(self, allowed: List[int]):
        if self.format == DownloadFormat.MP3:
            if self.mp3_bitrate not in allowed:
                raise ValueError(
                    f"MP3 bitrate {self.mp3_bitrate} kbps is not in the "
                    f"allowed list for this source: {allowed}"
                )


class JobStatus(BaseModel):
    job_id: str
    status: str          # pending | processing | done | error
    progress: int = 0    # 0-100
    filename: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
