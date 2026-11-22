import httpx
import pytest

from app.config import settings
from app.main import app
from app.security import (
    MediaSecurityError,
    sanitize_thumbnail_url,
    validate_extracted_media_urls,
)


@pytest.mark.asyncio
async def test_unified_production_server_routes_and_headers():
    """Verify FastAPI serves built React frontend, PWA assets, SPA fallback, and strict /api 404 isolation."""
    assert (settings.frontend_dist_dir / "index.html").is_file(), "Run `npm run build` in frontend/ first"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        # 1. Root SPA index.html (both GET and HEAD)
        root_resp = await client.get("/")
        assert root_resp.status_code == 200
        assert "text/html" in root_resp.headers["content-type"]
        assert "NEXUS Media" in root_resp.text
        head_resp = await client.head("/")
        assert head_resp.status_code == 200
        assert root_resp.headers["x-content-type-options"] == "nosniff"
        assert root_resp.headers["x-frame-options"] == "DENY"
        assert root_resp.headers["referrer-policy"] == "no-referrer"
        assert "no-cache" in root_resp.headers["cache-control"]

        # 2. PWA Manifest & Service Worker under same origin
        manifest_resp = await client.get("/manifest.webmanifest")
        assert manifest_resp.status_code == 200
        assert "manifest+json" in manifest_resp.headers["content-type"]
        assert "no-cache" in manifest_resp.headers["cache-control"]
        assert manifest_resp.json()["display"] == "standalone"

        sw_resp = await client.get("/sw.js")
        assert sw_resp.status_code == 200
        assert "no-cache" in sw_resp.headers["cache-control"]
        assert "CACHE_NAME" in sw_resp.text

        icon_resp = await client.get("/apple-touch-icon.png")
        assert icon_resp.status_code == 200
        assert icon_resp.content.startswith(b"\x89PNG")

        # 3. Client-side navigation fallback serves index.html
        spa_resp = await client.get("/history/recent")
        assert spa_resp.status_code == 200
        assert "text/html" in spa_resp.headers["content-type"]

        # 4. Unknown /api/* route MUST return JSON 404, NEVER index.html
        api_404 = await client.get("/api/does-not-exist")
        assert api_404.status_code == 404
        assert api_404.json()["code"] == "API_ROUTE_NOT_FOUND"

        # 5. Path traversal attempt cannot escape frontend/dist
        traversal = await client.get("/..%2fbackend/pyproject.toml")
        assert traversal.status_code == 200
        assert "[project]" not in traversal.text


@pytest.mark.asyncio
async def test_private_access_token_cookie_auth_and_lockout(monkeypatch: pytest.MonkeyPatch):
    """Verify optional NEXUS_MEDIA_ACCESS_TOKEN protects API/SSE with HttpOnly SameSite=Strict cookie."""
    monkeypatch.setattr(settings, "access_token", "my-private-tailnet-code-99")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        # Unauthenticated status check
        st0 = await client.get("/api/auth/status")
        assert st0.status_code == 200
        assert st0.json() == {"auth_required": True, "authenticated": False}

        # Protected endpoints reject unauthenticated calls with 401
        for path in ("/api/jobs", "/api/providers", "/api/jobs/events"):
            denied = await client.get(path)
            assert denied.status_code == 401
            assert denied.json()["detail"]["code"] == "AUTH_REQUIRED"

        # Wrong token rejected
        bad_login = await client.post("/api/auth/session", json={"token": "wrong-code"})
        assert bad_login.status_code == 401
        assert bad_login.json()["detail"]["code"] == "INVALID_ACCESS_TOKEN"

        # Correct token sets HttpOnly cookie & unlocks API
        ok_login = await client.post("/api/auth/session", json={"token": "my-private-tailnet-code-99"})
        assert ok_login.status_code == 200
        assert ok_login.json()["authenticated"] is True
        set_cookie = ok_login.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()
        assert "samesite=strict" in set_cookie.lower()
        # Token itself must NEVER be placed verbatim into the cookie!
        assert "my-private-tailnet-code-99" not in set_cookie

        # Authenticated API call succeeds via cookie
        jobs_ok = await client.get("/api/jobs")
        assert jobs_ok.status_code == 200

        # Logout clears cookie and re-locks API
        out = await client.post("/api/auth/logout")
        assert out.status_code == 200
        jobs_locked = await client.get("/api/jobs")
        assert jobs_locked.status_code == 401


def test_ytdlp_extracted_internal_urls_blocked_by_ssrf():
    """Ensure malicious stream URLs extracted by external tools (yt-dlp) cannot reach internal networks."""
    malicious_payloads = [
        {"url": "http://169.254.169.254/latest/meta-data/"},
        {"manifest_url": "http://127.0.0.1:8000/api/health"},
        {"formats": [{"url": "file:///etc/passwd"}]},
        {"formats": [{"url": "http://10.0.0.5/internal-stream.m3u8"}]},
        {"requested_formats": [{"url": "http://192.168.1.1/private.mp4"}]},
    ]
    for payload in malicious_payloads:
        with pytest.raises(MediaSecurityError) as exc_info:
            validate_extracted_media_urls(payload, allow_loopback=False)
        assert exc_info.value.code in {"SSRF_BLOCKED", "UNSUPPORTED_PROTOCOL"}


def test_thumbnail_url_sanitization():
    assert sanitize_thumbnail_url("https://i.ytimg.com/vi/abc/hqdefault.jpg") == "https://i.ytimg.com/vi/abc/hqdefault.jpg"
    assert sanitize_thumbnail_url("javascript:alert(1)") is None
    assert sanitize_thumbnail_url("data:text/html,<script>alert(1)</script>") is None
    assert sanitize_thumbnail_url("file:///etc/passwd") is None
