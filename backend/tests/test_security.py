import pytest

from app.security import (
    MediaSecurityError,
     is_ip_blocked,
    sanitize_filename,
    sanitize_url_for_log,
    validate_and_resolve_url,
)


def test_reject_non_http_protocols():
    for bad_url in [
        "file:///etc/passwd",
        "ftp://files.example.com/video.mp4",
        "gopher://127.0.0.1:70/",
        "javascript:alert(1)",
        "data:text/plain;base64,SGVsbG8=",
    ]:
        with pytest.raises(MediaSecurityError) as exc_info:
            validate_and_resolve_url(bad_url, allow_loopback=False)
        assert exc_info.value.code == "UNSUPPORTED_PROTOCOL"


def test_reject_embedded_credentials():
    with pytest.raises(MediaSecurityError) as exc_info:
        validate_and_resolve_url("https://admin:supersecret@example.com/media.mp4", allow_loopback=False)
    assert exc_info.value.code == "CREDENTIALS_IN_URL"


def test_reject_localhost_and_private_ips():
    blocked_targets = [
        "http://localhost:8000/api/health",
        "http://127.0.0.1:8080/internal.mp4",
        "http://[::1]:8000/video.mp4",
        "http://0.0.0.0/video.mp4",
        "http://10.0.0.15/stream.mp4",
        "http://172.16.12.4/stream.mp4",
        "http://192.168.1.1/router.mp4",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.1.1/cgnat.mp4",
        "http://nas.local/movie.mp4",
        "http://media.internal/clip.mp4",
        "http://metadata.google.internal/computeMetadata/v1/",
    ]
    for target in blocked_targets:
        with pytest.raises(MediaSecurityError) as exc_info:
            validate_and_resolve_url(target, allow_loopback=False)
        assert exc_info.value.code == "SSRF_BLOCKED"


def test_ip_blocking_helpers():
    assert is_ip_blocked("127.0.0.1", allow_loopback=False) is True
    assert is_ip_blocked("127.0.0.1", allow_loopback=True) is False
    assert is_ip_blocked("10.1.2.3", allow_loopback=True) is True
    assert is_ip_blocked("192.168.0.1", allow_loopback=True) is True
    assert is_ip_blocked("169.254.169.254", allow_loopback=True) is True
    assert is_ip_blocked("93.184.216.34", allow_loopback=False) is False


def test_log_url_sanitization():
    dirty = "https://user:pass@cdn.example.com/video.mp4?token=abc123secret&id=42&api_key=999&sig=xyz"
    cleaned = sanitize_url_for_log(dirty)
    assert "user" not in cleaned
    assert "pass" not in cleaned
    assert "abc123secret" not in cleaned
    assert "999" not in cleaned
    assert "xyz" not in cleaned
    assert "id=42" in cleaned


def test_filename_sanitization():
    assert sanitize_filename("../../etc/passwd") == "etc passwd"
    assert sanitize_filename("Клип: Осень / 2026 * HD?;.mp4") == "Клип Осень 2026 HD .mp4"
    assert sanitize_filename("   ...   ") == "nexus-media"
    assert sanitize_filename("CON") == "nexus-media"
    assert sanitize_filename("nul") == "nexus-media"
