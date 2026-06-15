# YouTube Audio Downloader

A full-stack app that downloads YouTube audio with **dynamic quality detection**.  
It never assumes a fixed maximum bitrate. It never upscales audio.

---

## Features

| Requirement | Implementation |
|---|---|
| FR-3.1 Dynamic Quality Detection | yt-dlp extracts every audio-only stream; sorted by bitrate desc |
| FR-4.1 Source Quality Transparency | `/analyze` response always includes `best_quality` before download options |
| FR-6.1 Quality Limiting | `allowed_mp3_options` is computed as `bitrate <= source_bitrate`; validated server-side |
| FR-6.2 Original Audio Download | `format=original` downloads without conversion, preserving codec |
| FR-6.3 Quality Explanation | `quality_note` field returned on every analyze response |

---

## Stack

```
backend/   FastAPI + yt-dlp + mutagen
frontend/  React + Vite (no external UI lib)
queue/     Celery + Redis (optional; defaults to BackgroundTasks)
```

---

## Quick Start (local dev)

### Prerequisites

```bash
# Python 3.11+
pip install yt-dlp fastapi uvicorn[standard] mutagen pydantic aiofiles python-multipart

# ffmpeg (required for MP3 conversion)
# macOS:   brew install ffmpeg
# Ubuntu:  apt install ffmpeg
# Windows: https://ffmpeg.org/download.html

# Node 18+ (frontend)
```

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Visit: `http://localhost:8000/docs` for interactive API docs.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit: `http://localhost:5173`

---

## Docker (recommended for production)

```bash
# Build and run everything
docker compose up --build

# Frontend: http://localhost:80
# API:      http://localhost:8000
# Docs:     http://localhost:8000/docs
```

---

## Enable Celery (optional, for high-traffic / multi-worker)

1. Edit `docker-compose.yml` — uncomment `redis`, `worker`, and `flower` services
2. Set `USE_CELERY=true` in the `api` service environment
3. Run: `celery -A app.workers.celery_app worker --loglevel=info --concurrency=4`
4. Monitor: `http://localhost:5555` (Flower)

---

## API Reference

### `POST /api/analyze`

```json
// Request
{ "url": "https://youtube.com/watch?v=..." }

// Response
{
  "title": "Song Title",
  "duration": "4:32",
  "duration_seconds": 272,
  "thumbnail": "https://...",
  "channel": "Channel Name",
  "best_quality": { "codec": "Opus", "bitrate": 256, "format": "webm" },
  "can_offer_320": false,
  "audio_streams": [
    { "codec": "Opus",  "bitrate": 256, "format": "webm", "size_estimate_mb": 4.3, "is_best": true },
    { "codec": "AAC",   "bitrate": 128, "format": "m4a",  "size_estimate_mb": 2.1, "is_best": false },
    { "codec": "Opus",  "bitrate": 70,  "format": "webm", "size_estimate_mb": 1.2, "is_best": false }
  ],
  "allowed_mp3_options": [256, 192, 128, 96, 64],
  "quality_note": "Download options are generated based on the highest audio quality..."
}
```

### `POST /api/download/start`

```json
// Download original (recommended)
{ "url": "...", "format": "original" }

// Convert to MP3 — bitrate MUST be in allowed_mp3_options
{ "url": "...", "format": "mp3", "mp3_bitrate": 128 }

// Response
{ "job_id": "abc123", "status": "pending", "progress": 0 }
```

### `GET /api/download/status/{job_id}`

```json
// While processing
{ "job_id": "abc123", "status": "processing", "progress": 45 }

// When done
{
  "job_id": "abc123",
  "status": "done",
  "progress": 100,
  "filename": "Song_Title_original_abc12345.webm",
  "download_url": "/api/download/file/Song_Title_original_abc12345.webm"
}
```

### `GET /api/download/file/{filename}`

Serves the file for download. Files are auto-deleted after `FILE_TTL_HOURS` (default: 2h).

---

## Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `DOWNLOADS_DIR` | `./downloads` | Where completed files are stored |
| `TEMP_DIR` | `./temp` | Temp files during processing |
| `MAX_DURATION_SECONDS` | `1800` | Reject videos longer than this |
| `FILE_TTL_HOURS` | `2` | Auto-delete completed files after N hours |
| `USE_CELERY` | `false` | Enable Celery task queue |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (Celery only) |
| `YTDLP_COOKIES_FILE` | `` | Path to cookies.txt for age-restricted videos |
| `YTDLP_PROXY` | `` | HTTP/SOCKS proxy for yt-dlp |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Allowed CORS origins |

---

## Quality Limiting — How it works

```
Source detected: Opus 160 kbps

MP3 tiers (all): 320, 256, 192, 160, 128, 96, 64

Filter (tier <= 160):    160, 128, 96, 64   ✓
Removed (tier > 160):    320, 256, 192       ✗

Offered to user:   [160, 128, 96, 64]
Hidden from user:  [320, 256, 192]     ← never shown, server rejects if sent
```

The server **re-analyzes** on every download request and rejects any `mp3_bitrate`  
not in `allowed_mp3_options`. Client-side manipulation cannot bypass this.

---

## Fallback Mechanism

```
yt-dlp extract_info()
  └─ Found audio-only streams?          → Use them (FR-3.1 primary path)
  └─ No audio-only streams found?       → Fallback: scan all formats with acodec
  └─ Still no streams?                  → Return 422 "No audio streams detected"
```

---

## Tests

```bash
cd backend
pytest tests/ -v
```

Tests cover:
- FR-6.1 quality limiting for all bitrate cases
- Codec normalization
- Duration formatting  
- Stream deduplication
- Stream sorting
- Video-format exclusion
- Best-stream marking
- Integration tests with mocked yt-dlp
"# ytaudiodwnd" 
