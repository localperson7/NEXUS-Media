import hashlib
import hmac
from typing import Optional

from fastapi import HTTPException, Request, Response

from app.config import settings

SESSION_COOKIE_NAME = "nexus_media_session"
_SESSION_CONTEXT = b"nexus-media-private-session-v1"


def is_auth_enabled() -> bool:
    return bool(settings.access_token and settings.access_token.strip())


def _compute_session_mac(token: str) -> str:
    return hmac.new(
        token.strip().encode("utf-8"),
        _SESSION_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def verify_access_token(candidate: Optional[str]) -> bool:
    if not is_auth_enabled():
        return True
    if not candidate or not settings.access_token:
        return False
    return hmac.compare_digest(candidate.strip(), settings.access_token.strip())


def is_request_authenticated(request: Request) -> bool:
    if not is_auth_enabled():
        return True
    assert settings.access_token is not None

    # 1. Check HttpOnly session cookie (works seamlessly with iOS Safari EventSource & <a download>)
    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_val:
        expected_mac = _compute_session_mac(settings.access_token)
        if hmac.compare_digest(cookie_val, expected_mac):
            return True

    # 2. Check explicit header for API clients/scripts (never query string to avoid log/history leaks)
    header_token = request.headers.get("X-Nexus-Token")
    if header_token and verify_access_token(header_token):
        return True

    return False


async def enforce_access_control(request: Request) -> None:
    if not is_request_authenticated(request):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_REQUIRED",
                "message": "Требуется код доступа к личному серверу NEXUS Media.",
            },
        )


def set_session_cookie(response: Response, request: Request) -> None:
    if not is_auth_enabled() or not settings.access_token:
        return
    mac = _compute_session_mac(settings.access_token)
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    is_https = request.url.scheme == "https" or forwarded_proto == "https"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=mac,
        httponly=True,
        samesite="strict",
        secure=is_https,
        max_age=60 * 60 * 24 * 30,  # 30 days on owner's personal device
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
