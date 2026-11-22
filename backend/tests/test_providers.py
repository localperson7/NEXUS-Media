from app.models import ExportCategory, ExportFormat
from app.providers.registry import provider_registry
from app.providers.ytdlp_provider import _translate_ytdlp_error, extract_actual_resolutions


def test_extract_actual_resolutions_never_invents_options():
    """Verify only actual resolutions present in source metadata are returned."""
    sample_info = {
        "title": "Test YouTube Stream",
        "formats": [
            {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a"},
            {
                "format_id": "134",
                "width": 640,
                "height": 360,
                "fps": 30,
                "vcodec": "avc1.4d401e",
                "acodec": "none",
                "ext": "mp4",
                "filesize": 12_000_000,
            },
            {
                "format_id": "247",
                "width": 1280,
                "height": 720,
                "fps": 30,
                "vcodec": "vp9",
                "acodec": "none",
                "ext": "webm",
                "filesize": 28_000_000,
            },
            {
                "format_id": "137",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "vcodec": "avc1.64002a",
                "acodec": "none",
                "ext": "mp4",
                "filesize": 54_000_000,
            },
        ],
    }

    resolutions = extract_actual_resolutions(sample_info)
    res_ids = [r.id for r in resolutions]
    # Only 1080p, 720p, and 360p exist in the source — 4K, 1440p, 480p, 240p must NOT appear
    assert res_ids == ["1080p", "720p", "360p"]

    res_1080 = resolutions[0]
    assert res_1080.height == 1080
    assert res_1080.requires_transcoding is False
    assert res_1080.requires_muxing is True
    assert "60 fps" in res_1080.label

    res_720 = resolutions[1]
    assert res_720.height == 720
    # VP9 requires transcoding to H.264 MP4
    assert res_720.requires_transcoding is True
    assert "VP9" in res_720.processing_note


def test_provider_routing():
    assert provider_registry.resolve_provider("https://www.youtube.com/watch?v=dQw4w9WgXcQ").provider_id == "youtube"
    assert provider_registry.resolve_provider("https://youtu.be/dQw4w9WgXcQ").provider_id == "youtube"
    assert provider_registry.resolve_provider("https://www.tiktok.com/@user/video/123456").provider_id == "tiktok"
    assert provider_registry.resolve_provider("https://www.instagram.com/reel/ABC123/").provider_id == "instagram"
    assert provider_registry.resolve_provider("https://ru.pinterest.com/pin/123456789/").provider_id == "pinterest"
    assert provider_registry.resolve_provider("https://cdn.example.org/files/clip.mp4").provider_id == "direct"
    assert provider_registry.resolve_provider("https://cdn.example.org/photo.webp").provider_id == "direct"


def test_error_translation():
    drm_err = _translate_ytdlp_error("ERROR: This video is DRM protected (Widevine)", "YouTube")
    assert drm_err.code == "DRM_PROTECTED"
    assert drm_err.status_code == 403

    priv_err = _translate_ytdlp_error("ERROR: Private video. Sign in to confirm your age", "Instagram")
    assert priv_err.code == "PRIVATE_OR_AUTH_REQUIRED"
    assert priv_err.status_code == 403

    unsup_err = _translate_ytdlp_error("ERROR: Unsupported URL: https://example.com/foo", "Веб")
    assert unsup_err.code == "UNSUPPORTED_SOURCE"
    assert unsup_err.status_code == 422

    tls_err = _translate_ytdlp_error(
        "ERROR: [vm.tiktok] abc: Unable to download webpage: _ssl.c:1018: The handshake operation timed out",
        "TikTok",
    )
    assert tls_err.code == "SOURCE_NETWORK_TIMEOUT"
    assert tls_err.status_code == 504

    rate_err = _translate_ytdlp_error("ERROR: HTTP Error 429: Too Many Requests", "YouTube")
    assert rate_err.code == "SOURCE_RATE_LIMITED"
    assert rate_err.status_code == 429

    cli_err = _translate_ytdlp_error("__main__.py: error: no such option: --proto", "YouTube")
    assert cli_err.code == "EXTRACTOR_INTERNAL_ERROR"
    assert cli_err.status_code == 500


def test_direct_provider_rejects_upstream_http_404_and_400():
    import asyncio
    import httpx
    import pytest
    from app.providers.base import ProviderError
    from app.providers.direct import DirectMediaProvider

    provider = DirectMediaProvider()
    with pytest.raises(ProviderError) as exc_404:
        asyncio.run(
            provider.inspect(
                "https://cdn.example.com/missing.jpg",
                headers=httpx.Headers({"content-type": "text/html", "x-nexus-http-status": "404"}),
            )
        )
    assert exc_404.value.code == "MEDIA_UNAVAILABLE"
    assert exc_404.value.status_code == 404

    with pytest.raises(ProviderError) as exc_400:
        asyncio.run(
            provider.inspect(
                "https://cdn.example.com/bad-thumb.jpg",
                headers=httpx.Headers({"content-type": "text/html", "x-nexus-http-status": "400"}),
            )
        )
    assert exc_400.value.code == "MEDIA_UNAVAILABLE"
    assert exc_400.value.status_code == 422
