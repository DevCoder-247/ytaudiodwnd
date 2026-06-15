"""
Tests — run with: pytest backend/tests/ -v
"""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.analyzer import (
    _compute_allowed_mp3_options,
    _extract_audio_streams,
    _normalize_codec,
    _format_duration,
)
from app.core.config import settings


# ─── Unit tests ───────────────────────────────────────────────────────────────

class TestAllowedMp3Options:
    def test_96kbps_source_never_offers_128_or_above(self):
        allowed = _compute_allowed_mp3_options(96)
        assert 128 not in allowed
        assert 192 not in allowed
        assert 320 not in allowed
        assert 96 in allowed
        assert 64 in allowed

    def test_160kbps_source(self):
        allowed = _compute_allowed_mp3_options(160)
        assert 160 in allowed
        assert 128 in allowed
        assert 64 in allowed
        assert 192 not in allowed
        assert 256 not in allowed
        assert 320 not in allowed

    def test_320kbps_source_offers_all(self):
        allowed = _compute_allowed_mp3_options(320)
        assert 320 in allowed
        assert 256 in allowed
        assert 192 in allowed
        assert 128 in allowed
        assert 64 in allowed

    def test_result_is_sorted_descending(self):
        allowed = _compute_allowed_mp3_options(256)
        assert allowed == sorted(allowed, reverse=True)

    def test_very_low_bitrate(self):
        allowed = _compute_allowed_mp3_options(48)
        assert allowed == []  # No standard MP3 tier <= 48 kbps (lowest is 64)
        # Actually 64 > 48, so all denied
        for tier in settings.MP3_BITRATE_TIERS:
            if tier <= 48:
                assert tier in allowed

    def test_zero_bitrate(self):
        allowed = _compute_allowed_mp3_options(0)
        assert allowed == []


class TestCodecNormalization:
    def test_opus(self):
        assert _normalize_codec("opus") == "Opus"

    def test_aac_variants(self):
        assert _normalize_codec("mp4a.40.2") == "AAC"
        assert _normalize_codec("aac") == "AAC"

    def test_vorbis(self):
        assert _normalize_codec("vorbis") == "Vorbis"

    def test_unknown(self):
        result = _normalize_codec("eac3")
        assert result == "EAC3"  # uppercase fallback


class TestFormatDuration:
    def test_minutes(self):
        assert _format_duration(272) == "4:32"

    def test_hours(self):
        assert _format_duration(3661) == "1:01:01"

    def test_zero(self):
        assert _format_duration(0) == "0:00"


class TestExtractAudioStreams:
    def _make_fmt(self, acodec, abr, ext, vcodec="none"):
        return {"acodec": acodec, "abr": abr, "ext": ext, "vcodec": vcodec}

    def test_sorts_descending(self):
        info = {
            "formats": [
                self._make_fmt("opus", 70, "webm"),
                self._make_fmt("opus", 256, "webm"),
                self._make_fmt("mp4a.40.2", 128, "m4a"),
            ]
        }
        streams = _extract_audio_streams(info, 240)
        bitrates = [s.bitrate for s in streams]
        assert bitrates == sorted(bitrates, reverse=True)

    def test_marks_best(self):
        info = {
            "formats": [
                self._make_fmt("opus", 70, "webm"),
                self._make_fmt("opus", 256, "webm"),
            ]
        }
        streams = _extract_audio_streams(info, 240)
        best = [s for s in streams if s.is_best]
        assert len(best) == 1
        assert best[0].bitrate == 256

    def test_skips_video_formats(self):
        info = {
            "formats": [
                {"acodec": "opus", "abr": 128, "ext": "webm", "vcodec": "vp9"},
            ]
        }
        streams = _extract_audio_streams(info, 240)
        assert streams == []

    def test_deduplicates(self):
        info = {
            "formats": [
                self._make_fmt("opus", 128, "webm"),
                self._make_fmt("opus", 128, "webm"),  # duplicate
            ]
        }
        streams = _extract_audio_streams(info, 240)
        assert len(streams) == 1

    def test_estimates_size(self):
        info = {
            "formats": [self._make_fmt("opus", 128, "webm")]
        }
        streams = _extract_audio_streams(info, 240)  # 4 minutes
        assert streams[0].size_estimate_mb is not None
        assert streams[0].size_estimate_mb > 0


# ─── Integration-style tests with mocked yt-dlp ───────────────────────────────

class TestAnalyzeUrlSync:
    """Mock yt-dlp to test the full analyze flow."""

    def _mock_info(self, best_bitrate=256):
        return {
            "title": "Test Song",
            "duration": 272,
            "thumbnail": "https://example.com/thumb.jpg",
            "uploader": "Test Channel",
            "formats": [
                {
                    "acodec": "opus",
                    "abr": best_bitrate,
                    "tbr": best_bitrate,
                    "ext": "webm",
                    "vcodec": "none",
                },
                {
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                    "tbr": 128,
                    "ext": "m4a",
                    "vcodec": "none",
                },
                {
                    "acodec": "opus",
                    "abr": 70,
                    "tbr": 70,
                    "ext": "webm",
                    "vcodec": "none",
                },
            ],
        }

    def test_best_quality_detected(self):
        from app.services.analyzer import analyze_url_sync

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=self._mock_info(256))

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = analyze_url_sync("https://youtube.com/watch?v=test")

        assert result.best_quality.bitrate == 256
        assert result.best_quality.codec == "Opus"
        assert result.can_offer_320 is False

    def test_320_flag_when_source_is_320(self):
        from app.services.analyzer import analyze_url_sync

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=self._mock_info(320))

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = analyze_url_sync("https://youtube.com/watch?v=test")

        assert result.can_offer_320 is True
        assert 320 in result.allowed_mp3_options

    def test_mp3_options_capped_at_source(self):
        from app.services.analyzer import analyze_url_sync

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=self._mock_info(96))

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = analyze_url_sync("https://youtube.com/watch?v=test")

        for opt in result.allowed_mp3_options:
            assert opt <= 96, f"Option {opt} exceeds source bitrate 96"
        assert 128 not in result.allowed_mp3_options
        assert 320 not in result.allowed_mp3_options

    def test_streams_sorted_descending(self):
        from app.services.analyzer import analyze_url_sync

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=self._mock_info(256))

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = analyze_url_sync("https://youtube.com/watch?v=test")

        bitrates = [s.bitrate for s in result.audio_streams]
        assert bitrates == sorted(bitrates, reverse=True)

    def test_quality_note_always_present(self):
        from app.services.analyzer import analyze_url_sync

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info = MagicMock(return_value=self._mock_info(160))

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = analyze_url_sync("https://youtube.com/watch?v=test")

        assert result.quality_note
        assert "original audio quality" in result.quality_note.lower()
