# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `0.1.0-beta` (`main`) | Yes |

## Security Architecture & Boundaries

NEXUS Media processes external URLs and invokes media tools (`yt-dlp`, `FFmpeg`, `ffprobe`). Because misconfigured media downloaders can easily become SSRF proxies, NEXUS Media enforces the following defenses:

1. **SSRF & URL Validation (`backend/app/security.py`)**:
   - Allows only `http` and `https` schemes.
   - Rejects embedded credentials (`user:pass@host`) and control characters.
   - Resolves DNS and blocks loopback (`127.0.0.0/8`, `::1`), RFC 1918 private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local / cloud metadata (`169.254.0.0/16`, `fe80::/10`), CGNAT (`100.64.0.0/10`), multicast, reserved IPs, and `.local`/`.internal` hostnames.
   - Manually inspects HTTP redirect chains (`follow_redirects=False`) so a public URL cannot redirect to an internal address.
   - Validates stream and manifest URLs extracted by `yt-dlp` (`validate_extracted_media_urls`) before downloading.
2. **External Tool Hardening**:
   - All subprocesses run via `asyncio.create_subprocess_exec` with explicit argument arrays and `--` option terminators (no shell interpolation).
   - `ffprobe` is restricted with `-protocol_whitelist http,https,tcp,tls`.
   - `yt-dlp` is invoked with `--ignore-config`, `--no-exec`, `--no-playlist`, and `--proto https,http,-file,-ftp,-rtsp,-rtmp,-mms`.
3. **Access Control & Privacy**:
   - Default binding is `127.0.0.1:8000` (localhost only).
   - Optional `NEXUS_MEDIA_ACCESS_TOKEN` protects all API, SSE, and download routes via constant-time HMAC-SHA256 `HttpOnly; SameSite=Strict` session cookies (with `Secure` over HTTPS).
   - Temporary job directories (`tmp_jobs/`) and SQLite storage (`storage/`) use restricted `0700`/`0600` permissions and automatic TTL cleanup.
   - Sensitive query parameters (`token`, `api_key`, `password`, `sig`, `cookie`, etc.) are masked before logging.
4. **Deployment Guidance**:
   - **Never** expose NEXUS Media as an unauthenticated public downloading proxy.
   - When using Tailscale for iPhone PWA access, use private **Tailscale Serve** only — **never** enable **Tailscale Funnel**.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities (such as SSRF bypasses, command injection, path traversal, or authentication flaws).

Instead, report vulnerabilities privately through GitHub's **Private Vulnerability Reporting** (Security Advisories tab once the repository is published) or by contacting the repository maintainer directly. Include:

- Affected component and version
- Step-by-step reproduction details or proof of concept
- Potential impact and any suggested mitigation

We aim to acknowledge reports promptly and coordinate a fix before public disclosure.
