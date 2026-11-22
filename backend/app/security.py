import ipaddress
import re
import socket
from typing import Optional, Set
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx

from app.config import settings

SENSITIVE_QUERY_KEYS: Set[str] = {
    "token",
    "access_token",
    "auth",
    "key",
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "sig",
    "signature",
    "cookie",
    "session",
    "sessionid",
    "jwt",
}

BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "0.0.0.0",
}

BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
    ".home.arpa",
    ".lan",
    ".corp",
)

CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
BENCHMARK_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class MediaSecurityError(Exception):
    """Raised when a URL or request violates SSRF or security policies."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def sanitize_url_for_log(raw_url: str) -> str:
    """Mask sensitive query parameters and strip credentials before logging."""
    try:
        parsed = urlparse(raw_url.strip())
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        masked_pairs = [
            (k, "***" if k.lower() in SENSITIVE_QUERY_KEYS else v)
            for k, v in query_pairs
        ]
        return urlunparse(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                urlencode(masked_pairs),
                "",
            )
        )
    except Exception:
        return "<invalid-url>"


WINDOWS_RESERVED_NAMES: Set[str] = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, default: str = "nexus-media") -> str:
    """Create a safe filename preserving Cyrillic and Latin characters without traversal."""
    cleaned = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|;]+", " ", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    if not cleaned or cleaned in {".", ".."} or cleaned.lower() in WINDOWS_RESERVED_NAMES:
        return default
    return cleaned[:140]


def _check_single_ip(
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address,
    allow_loopback: bool = False,
) -> bool:
    """Return True if the IP address is blocked by SSRF policy."""
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    if ip_obj.is_loopback:
        return not allow_loopback

    if (
        ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_unspecified
        or ip_obj.is_reserved
    ):
        return True

    if isinstance(ip_obj, ipaddress.IPv4Address):
        if ip_obj in CGNAT_NETWORK or ip_obj in BENCHMARK_NETWORK:
            return True

    return False


def is_ip_blocked(ip_str: str, allow_loopback: bool = False) -> bool:
    """Return True if ip_str is not a safe public IP address."""
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return _check_single_ip(ip_obj, allow_loopback=allow_loopback)


def validate_and_resolve_url(
    raw_url: str,
    allow_loopback: Optional[bool] = None,
) -> str:
    """Validate URL format, protocol, hostname, and DNS resolution against SSRF."""
    if allow_loopback is None:
        allow_loopback = settings.allow_loopback_for_tests

    if not raw_url or not isinstance(raw_url, str):
        raise MediaSecurityError("INVALID_URL", "Введите корректную ссылку на медиафайл.")

    cleaned = raw_url.strip()
    if len(cleaned) > 2048:
        raise MediaSecurityError("URL_TOO_LONG", "Ссылка превышает допустимую длину (2048 символов).")

    if any(ch in cleaned for ch in ("\r", "\n", "\t", "\x00")):
        raise MediaSecurityError("INVALID_URL", "Ссылка содержит недопустимые управляющие символы.")

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise MediaSecurityError(
            "UNSUPPORTED_PROTOCOL",
            "Поддерживаются только протоколы HTTP и HTTPS.",
        )

    if parsed.username or parsed.password:
        raise MediaSecurityError(
            "CREDENTIALS_IN_URL",
            "Ссылки со встроенными логинами или паролями запрещены политикой безопасности.",
        )

    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        raise MediaSecurityError("INVALID_HOST", "В ссылке отсутствует корректное имя хоста.")

    is_local_hostname = hostname in BLOCKED_HOSTNAMES or hostname.endswith(BLOCKED_HOST_SUFFIXES)
    if is_local_hostname:
        if not (allow_loopback and hostname in {"localhost", "127.0.0.1"}):
            raise MediaSecurityError(
                "SSRF_BLOCKED",
                "Доступ к локальным узлам и внутренним сетевым адресам заблокирован.",
                status_code=403,
            )

    # Check if hostname is a literal IP
    try:
        literal_ip = ipaddress.ip_address(hostname)
        if _check_single_ip(literal_ip, allow_loopback=allow_loopback):
            raise MediaSecurityError(
                "SSRF_BLOCKED",
                "Доступ к внутренним, частным и зарезервированным IP-адресам запрещён.",
                status_code=403,
            )
    except ValueError:
        pass

    port = parsed.port or (443 if scheme == "https" else 80)

    try:
        addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise MediaSecurityError(
            "DNS_RESOLUTION_FAILED",
            f"Не удалось разрешить доменное имя «{hostname}». Проверьте ссылку и подключение.",
            status_code=400,
        ) from exc

    if not addr_info:
        raise MediaSecurityError(
            "DNS_RESOLUTION_FAILED",
            f"Домен «{hostname}» не вернул ни одного IP-адреса.",
            status_code=400,
        )

    for family, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if is_ip_blocked(ip_str, allow_loopback=allow_loopback):
            raise MediaSecurityError(
                "SSRF_BLOCKED",
                "Домен указывает на внутренний или защищённый сетевой адрес (защита от SSRF).",
                status_code=403,
            )

    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            parsed.query,
            "",
        )
    )


async def validate_url_with_redirects(
    raw_url: str,
    max_redirects: int = 5,
    allow_loopback: Optional[bool] = None,
    timeout: float = 10.0,
) -> tuple[str, Optional[httpx.Headers]]:
    """
    Validate URL and manually inspect redirect chain so that no redirect
    points to localhost, private networks, or non-HTTP(S) schemes.
    Returns (final_validated_url, response_headers_if_reachable).
    """
    current_url = validate_and_resolve_url(raw_url, allow_loopback=allow_loopback)
    headers = {
        "User-Agent": "NEXUS-Media/0.1 (+https://github.com/nexus-media; media-inspector)",
        "Accept": "*/*",
    }

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout, connect=5.0),
        headers=headers,
    ) as client:
        for _ in range(max_redirects + 1):
            try:
                resp = await client.request("HEAD", current_url)
                if resp.status_code in {405, 403, 400}:
                    # Some servers block HEAD; fall back to streaming GET without reading body
                    async with client.stream("GET", current_url) as stream_resp:
                        status = stream_resp.status_code
                        resp_headers = httpx.Headers(stream_resp.headers)
                        location = resp_headers.get("location")
                else:
                    status = resp.status_code
                    resp_headers = httpx.Headers(resp.headers)
                    location = resp_headers.get("location")
            except httpx.HTTPError:
                return current_url, None

            if status in {301, 302, 303, 307, 308} and location:
                next_url = urljoin(current_url, location)
                current_url = validate_and_resolve_url(next_url, allow_loopback=allow_loopback)
                continue

            resp_headers["x-nexus-http-status"] = str(status)
            return current_url, resp_headers

    raise MediaSecurityError(
        "TOO_MANY_REDIRECTS",
        "Превышено допустимое количество перенаправлений ссылки.",
        status_code=400,
    )


def sanitize_thumbnail_url(raw_url: Optional[str]) -> Optional[str]:
    """Allow only http/https thumbnail URLs so untrusted schemes never reach the UI."""
    if not raw_url or not isinstance(raw_url, str):
        return None
    cleaned = raw_url.strip()
    parsed = urlparse(cleaned)
    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return None
    if not parsed.hostname:
        return None
    return cleaned


def validate_extracted_media_urls(
    info: dict,
    allow_loopback: Optional[bool] = None,
) -> None:
    """
    Validate stream URLs extracted by external tools (yt-dlp) against SSRF boundaries.
    Prevents a malicious public webpage from pointing yt-dlp to internal IPs or file:// URIs.
    """
    candidate_urls: list[str] = []
    for key in ("url", "manifest_url", "webpage_url"):
        val = info.get(key)
        if isinstance(val, str) and val.strip():
            candidate_urls.append(val.strip())

    # Validate unique hostnames across extracted format & requested_formats URLs
    seen_hosts: set[tuple[str, str, Optional[int]]] = set()
    all_formats = [*(info.get("formats") or []), *(info.get("requested_formats") or [])]
    for fmt in all_formats:
        if not isinstance(fmt, dict):
            continue
        f_url = fmt.get("url")
        if isinstance(f_url, str) and f_url.strip():
            parsed = urlparse(f_url.strip())
            host_key = (
                (parsed.scheme or "").lower(),
                (parsed.hostname or "").lower(),
                parsed.port,
            )
            if host_key not in seen_hosts:
                seen_hosts.add(host_key)
                candidate_urls.append(f_url.strip())

    for url in candidate_urls:
        validate_and_resolve_url(url, allow_loopback=allow_loopback)
