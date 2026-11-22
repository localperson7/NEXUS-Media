# Changelog

All notable changes to **NEXUS Media** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses pre-release semantic versioning during beta development.

## [0.1.0-beta] — 2026-11-22

### Added
- **Core Media Inspection & Processing**:
  - Extensible provider architecture (`DirectMediaProvider`, `YouTubeProvider`, `TikTokProvider`, `InstagramProvider`, `PinterestProvider`, `CompatibleWebProvider`).
  - Honest resolution reporting from real source streams (`yt-dlp` / `ffprobe`) with rejection of unavailable resolutions (`422 RESOLUTION_NOT_AVAILABLE`) and upstream HTTP 4xx/5xx direct-media validation.
  - Bounded streaming OpenGraph `og:image` fallback for public Pinterest image pins with SSRF validation.
  - MP4 video export with faststart optimization and FFmpeg remux/H.264 transcoding indicators.
  - Explicit MP3 audio export (`Аудиоэкспорт MP3`) with selectable bitrates (`128`–`320 kbps`) via `FFmpeg libmp3lame`.
  - Lossless original image downloads verified with Pillow.
  - Accurate structured Russian error classification distinguishing TLS/network timeouts (`504 SOURCE_NETWORK_TIMEOUT`), rate limits (`429`), forbidden (`403`), and extractor errors (`500`).
- **Persistent SQLite History & Recovery**:
  - Thread-safe SQLite database (`WAL` mode) with versioned schema migrations (`v1` jobs table, `v2` retry linkage metadata).
  - Startup recovery marking interrupted in-flight jobs as `INTERRUPTED_BY_RESTART` while cleaning partial temp files.
  - History-preserving temporary file cleanup (`file_available` / `file_expired`), one-click retry (`POST /api/jobs/{id}/retry`), and individual record deletion (`DELETE /api/jobs/{id}`).
- **Live Progress via Server-Sent Events (SSE)**:
  - Real-time `GET /api/jobs/events` endpoint with measured download speed, ETA, FFmpeg `-progress` parsing, `Last-Event-ID` replay without duplicates, keepalive heartbeats, and leak-free disconnect cleanup.
  - Frontend `useJobEvents` hook with exponential reconnect, iOS Safari background/foreground recovery (`visibilitychange`, `pageshow`, `online`/`offline`), and fallback polling when disconnected.
- **Unified Production Server & Private iPhone PWA Readiness**:
  - Single-origin FastAPI serving of the built React/Vite PWA (`frontend/dist`) and `/api/*` with security response headers and safe SPA fallback.
  - Optional `NEXUS_MEDIA_ACCESS_TOKEN` private access protection using HMAC-signed `HttpOnly; SameSite=Strict` cookies and a lock-screen UI.
  - PWA manifest, icons (`192`, `512`, `apple-touch-icon`), Service Worker (`v2`), safe-area insets, `16px` anti-zoom mobile inputs, standalone detection, and Safari installation guide.
- **Defense-in-Depth Security & Subprocess Stability**:
  - SSRF protection covering initial URLs, DNS resolution, HTTP redirect chains, `ffprobe` protocol whitelisting, and `yt-dlp` extracted stream & `requested_formats` URLs.
  - Bounded subprocess timeouts (`--socket-timeout` + `asyncio.wait_for` on stdout loops) with zombie-process reaping on timeout and cancellation.
  - Cross-platform filename sanitization (stripping traversal, control chars, `;`, and Windows reserved names).
  - Rate limiting, isolated `0700` per-job directories, `0600` SQLite file permissions, and sanitized log URLs.
- **Open-Source Release Infrastructure**:
  - English `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `.env.example`, Tailscale Serve private access documentation, and GitHub Actions CI workflow.
