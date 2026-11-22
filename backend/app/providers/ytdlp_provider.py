import asyncio
import html
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models import (
    ExportCategory,
    ExportFormat,
    ExportOption,
    MediaInspectResponse,
    MediaType,
    ResolutionOption,
)
from app.providers.base import BaseMediaProvider, ProviderError
from app.security import (
    sanitize_thumbnail_url,
    sanitize_url_for_log,
    validate_and_resolve_url,
    validate_extracted_media_urls,
)

logger = logging.getLogger("nexus_media.ytdlp")

IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
META_TAG_RE = re.compile(r"<meta\s+[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r'([a-zA-Z0-9_:-]+)\s*=\s*["\']([^"\']*)["\']')


def _translate_ytdlp_error(stderr_text: str, source_name: str) -> ProviderError:
    low = stderr_text.lower()
    if stderr_text.strip():
        first_line = stderr_text.strip().splitlines()[-1][:240]
        logger.warning("yt-dlp error on %s: %s", source_name, first_line)

    if "no such option:" in low or "traceback (most recent call last)" in low:
        return ProviderError(
            "EXTRACTOR_INTERNAL_ERROR",
            f"Внутренняя ошибка запуска экстрактора при обращении к {source_name}. Проверьте конфигурацию сервера.",
            status_code=500,
        )
    if any(
        token in low
        for token in (
            "timed out",
            "handshake",
            "transporterror",
            "connection reset",
            "connection refused",
            "remotedisconnected",
            "sslerror",
            "temporary failure in name resolution",
            "name or service not known",
            "failed to resolve",
        )
    ):
        return ProviderError(
            "SOURCE_NETWORK_TIMEOUT",
            f"Не удалось установить соединение с {source_name} (таймаут TLS/сети). Возможно, ресурс ограничен в вашей сети или временно недоступен.",
            status_code=504,
        )
    if "http error 429" in low or "too many requests" in low or "rate limit" in low or "rate-limit" in low:
        return ProviderError(
            "SOURCE_RATE_LIMITED",
            f"Платформа {source_name} временно ограничила частоту запросов (HTTP 429). Повторите попытку позже.",
            status_code=429,
        )
    if "drm" in low or "widevine" in low or "playready" in low:
        return ProviderError(
            "DRM_PROTECTED",
            f"Контент на {source_name} защищён DRM. NEXUS Media не обходит технические средства защиты авторских прав.",
            status_code=403,
        )
    if any(
        token in low
        for token in (
            "private video",
            "login required",
            "sign in to confirm",
            "cookies",
            "members-only",
            "this video is private",
            "age-restricted",
            "registered users",
            "authentication",
        )
    ):
        return ProviderError(
            "PRIVATE_OR_AUTH_REQUIRED",
            f"Медиафайл на {source_name} закрыт настройками приватности или требует авторизации. Доступны только открытые публичные ссылки.",
            status_code=403,
        )
    if "http error 403" in low or "403: forbidden" in low:
        return ProviderError(
            "SOURCE_FORBIDDEN",
            f"Сервер {source_name} отклонил доступ к медиа (HTTP 403).",
            status_code=403,
        )
    if "unsupported url" in low or "no suitable infoextractor" in low:
        return ProviderError(
            "UNSUPPORTED_SOURCE",
            "Эта ссылка или платформа не поддерживается либо страница не содержит доступных медиафайлов.",
            status_code=422,
        )
    if "video unavailable" in low or "not available" in low or "404" in low or "removed" in low:
        return ProviderError(
            "MEDIA_UNAVAILABLE",
            f"Медиафайл на {source_name} удалён, скрыт автором или недоступен в вашем регионе.",
            status_code=404,
        )
    return ProviderError(
        "EXTRACTION_FAILED",
        f"Не удалось получить метаданные с {source_name}. Убедитесь, что ссылка публична и содержит медиафайл.",
        status_code=422,
    )


def _format_resolution_label(height: int, width: Optional[int], fps: Optional[int]) -> str:
    tier = ""
    if height == 2160:
        tier = " 4K UHD"
    elif height == 1440:
        tier = " QHD"
    elif height == 1080:
        tier = " Full HD"
    elif height == 720:
        tier = " HD"

    dims = f" ({width}×{height})" if width and height else ""
    fps_str = f" · {int(fps)} fps" if fps and fps > 30 else ""
    return f"{height}p{tier}{dims}{fps_str}"


def extract_actual_resolutions(info: dict) -> List[ResolutionOption]:
    """
    Extract ONLY actual video resolutions reported by the source in info['formats'].
    Never invent or extrapolate resolutions that do not exist in the source.
    """
    formats = info.get("formats") or []
    by_height: Dict[int, dict] = {}

    for fmt in formats:
        vcodec = fmt.get("vcodec")
        height = fmt.get("height")
        width = fmt.get("width")
        if not vcodec or vcodec == "none":
            continue
        if not isinstance(height, int) or height <= 0:
            continue

        # Score candidate formats at the same height: prefer H.264 (avc1) + mp4 + known filesize
        ext = (fmt.get("ext") or "").lower()
        acodec = fmt.get("acodec") or "none"
        is_h264 = vcodec.startswith("avc1") or vcodec.startswith("h264")
        has_audio = acodec != "none"
        filesize = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        fps = fmt.get("fps") or 0

        score = (
            (100 if is_h264 else 40)
            + (30 if ext == "mp4" else 10)
            + (15 if has_audio else 0)
            + (5 if filesize > 0 else 0)
            + min(int(fps or 0), 60) * 0.1
        )

        existing = by_height.get(height)
        if existing is None or score > existing["_score"]:
            candidate = dict(fmt)
            candidate["_score"] = score
            by_height[height] = candidate

    # Fallback if top-level info has width/height on a single-stream media without detailed formats array
    if not by_height and isinstance(info.get("height"), int) and info["height"] > 0:
        h = info["height"]
        by_height[h] = {
            "format_id": info.get("format_id") or "best",
            "height": h,
            "width": info.get("width"),
            "fps": info.get("fps"),
            "vcodec": info.get("vcodec") or "h264",
            "acodec": info.get("acodec") or "aac",
            "ext": info.get("ext") or "mp4",
            "filesize": info.get("filesize") or info.get("filesize_approx"),
        }

    resolutions: List[ResolutionOption] = []
    for height in sorted(by_height.keys(), reverse=True):
        fmt = by_height[height]
        width = fmt.get("width")
        fps_raw = fmt.get("fps")
        fps = int(round(fps_raw)) if isinstance(fps_raw, (int, float)) and fps_raw > 0 else None
        vcodec = fmt.get("vcodec") or "unknown"
        acodec = fmt.get("acodec") or "none"
        ext = (fmt.get("ext") or "mp4").lower()
        filesize = fmt.get("filesize") or fmt.get("filesize_approx")

        is_h264 = vcodec.startswith("avc1") or vcodec.startswith("h264")
        has_audio = acodec != "none"

        if is_h264 and ext == "mp4" and has_audio:
            requires_transcoding = False
            requires_muxing = False
            note = "Готовый поток MP4 (H.264 + AAC) — без перекодирования"
        elif is_h264:
            requires_transcoding = False
            requires_muxing = True
            note = "Сборка видеопотока H.264 и аудиодорожки в контейнер MP4 (FFmpeg)"
        else:
            requires_transcoding = True
            requires_muxing = True
            note = f"Сборка потоков и конвертация кодека ({vcodec.split('.')[0].upper()} → H.264 MP4) через FFmpeg"

        # Precise yt-dlp format selector capped strictly at this exact height
        selector = (
            f"bestvideo[height={height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
            f"bestvideo[height={height}]+bestaudio/best[height={height}]"
        )

        resolutions.append(
            ResolutionOption(
                id=f"{height}p",
                label=_format_resolution_label(height, width, fps),
                width=width,
                height=height,
                fps=fps,
                vcodec=vcodec,
                acodec=acodec if has_audio else "aac (mux)",
                source_ext=ext,
                format_selector=selector,
                filesize_bytes=int(filesize) if isinstance(filesize, (int, float)) else None,
                requires_transcoding=requires_transcoding,
                requires_muxing=requires_muxing,
                processing_note=note,
            )
        )

    # If the source is a video stream whose height metadata is omitted by the platform
    if not resolutions and info.get("vcodec") != "none":
        resolutions.append(
            ResolutionOption(
                id="source",
                label="Исходное разрешение источника",
                width=info.get("width"),
                height=info.get("height"),
                fps=None,
                vcodec=info.get("vcodec"),
                acodec=info.get("acodec"),
                source_ext=info.get("ext") or "mp4",
                format_selector="bestvideo+bestaudio/best",
                filesize_bytes=info.get("filesize") or info.get("filesize_approx"),
                requires_transcoding=False,
                requires_muxing=True,
                processing_note="Сохранение оригинального потока в контейнер MP4 (FFmpeg)",
            )
        )

    return resolutions


class YtDlpBaseProvider(BaseMediaProvider):
    """Base provider using yt-dlp in safe, no-cookie, single-item JSON inspection mode."""

    async def _run_ytdlp_inspect(self, url: str) -> dict:
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-exec",
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            "--socket-timeout",
            "15",
            "--",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
        except asyncio.TimeoutError as exc:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise ProviderError(
                "SOURCE_NETWORK_TIMEOUT",
                f"Превышено время ожидания ответа от {self.display_name}. Возможно, платформа ограничена в вашей сети или перегружена.",
                status_code=504,
            ) from exc

        if proc.returncode != 0 or not stdout:
            err_text = stderr.decode("utf-8", errors="replace") if stderr else ""
            raise _translate_ytdlp_error(err_text, self.display_name)

        try:
            data = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "INVALID_METADATA",
                f"Получены некорректные метаданные от {self.display_name}.",
                status_code=502,
            ) from exc

        if data.get("_type") == "playlist" and data.get("entries"):
            first_entry = next((e for e in data["entries"] if e), None)
            if first_entry:
                data = first_entry

        return data

    async def inspect(
        self,
        url: str,
        headers: Optional[httpx.Headers] = None,
    ) -> MediaInspectResponse:
        info = await self._run_ytdlp_inspect(url)
        # Validate every stream/manifest URL extracted by yt-dlp against SSRF boundaries
        validate_extracted_media_urls(info)

        duration = info.get("duration")
        if isinstance(duration, (int, float)) and duration > settings.max_duration_seconds:
            raise ProviderError(
                "LIMIT_EXCEEDED",
                f"Длительность медиа ({int(duration // 60)} мин) превышает лимит ({settings.max_duration_seconds // 60} мин).",
                status_code=413,
            )

        title = (info.get("title") or info.get("fulltitle") or "Медиафайл").strip()
        uploader = info.get("uploader") or info.get("channel") or info.get("creator")
        thumbnail = sanitize_thumbnail_url(info.get("thumbnail"))
        ext = (info.get("ext") or "mp4").lower()
        filesize = info.get("filesize") or info.get("filesize_approx")

        # Determine if image, audio-only, or video
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")
        if ext in IMAGE_EXTS:
            media_type = MediaType.IMAGE
        elif vcodec == "none" and acodec and acodec != "none":
            media_type = MediaType.AUDIO
        else:
            media_type = MediaType.VIDEO

        if media_type == MediaType.IMAGE:
            return MediaInspectResponse(
                url=url,
                title=title,
                source_id=self.provider_id,
                source_name=self.display_name,
                media_type=MediaType.IMAGE,
                thumbnail_url=thumbnail or info.get("url") or url,
                uploader=uploader,
                original_ext=ext,
                filesize_approx=int(filesize) if isinstance(filesize, (int, float)) else None,
                width=info.get("width"),
                height=info.get("height"),
                export_options=[
                    ExportOption(
                        format=ExportFormat.IMAGE_ORIGINAL,
                        category=ExportCategory.IMAGE,
                        label=f"Оригинальное изображение ({ext.upper()})",
                        badge="Оригинал",
                        description="Сохранение исходного файла изображения в максимальном доступном разрешении.",
                        output_ext=ext,
                        requires_transcoding=False,
                        transcoding_note="Без перекодирования — оригинальный файл источника",
                        resolutions=[],
                    )
                ],
            )

        if media_type == MediaType.AUDIO:
            return MediaInspectResponse(
                url=url,
                title=title,
                source_id=self.provider_id,
                source_name=self.display_name,
                media_type=MediaType.AUDIO,
                thumbnail_url=thumbnail,
                duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
                uploader=uploader,
                original_ext=ext,
                filesize_approx=int(filesize) if isinstance(filesize, (int, float)) else None,
                export_options=[
                    ExportOption(
                        format=ExportFormat.MP3,
                        category=ExportCategory.AUDIO_EXPORT,
                        label="Аудиоэкспорт MP3",
                        badge="Аудиоэкспорт",
                        description="Экспорт аудиопотока в формат MP3 (192 кбит/с).",
                        output_ext="mp3",
                        requires_transcoding=ext != "mp3",
                        transcoding_note="Конвертация аудиопотока в MP3 192 кбит/с через FFmpeg",
                        resolutions=[],
                    )
                ],
            )

        resolutions = extract_actual_resolutions(info)
        any_transcode = any(r.requires_transcoding for r in resolutions)

        export_options = [
            ExportOption(
                format=ExportFormat.MP4,
                category=ExportCategory.VIDEO,
                label="Видео MP4",
                badge="Видео",
                description="Экспорт видео в контейнер MP4. Доступны только реальные разрешения источника.",
                output_ext="mp4",
                requires_transcoding=any_transcode,
                transcoding_note=resolutions[0].processing_note if resolutions else "Сборка в MP4 через FFmpeg",
                resolutions=resolutions,
            ),
            ExportOption(
                format=ExportFormat.MP3,
                category=ExportCategory.AUDIO_EXPORT,
                label="Аудиоэкспорт MP3",
                badge="Аудиоэкспорт",
                description="Отдельный экспорт звуковой дорожки в MP3 (192 кбит/с, FFmpeg).",
                output_ext="mp3",
                requires_transcoding=True,
                transcoding_note="Требуется извлечение аудиопотока и перекодирование в MP3 через FFmpeg",
                resolutions=[],
            ),
        ]

        return MediaInspectResponse(
            url=url,
            title=title,
            source_id=self.provider_id,
            source_name=self.display_name,
            media_type=MediaType.VIDEO,
            thumbnail_url=thumbnail,
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
            uploader=uploader,
            original_ext=ext,
            filesize_approx=int(filesize) if isinstance(filesize, (int, float)) else None,
            width=resolutions[0].width if resolutions else info.get("width"),
            height=resolutions[0].height if resolutions else info.get("height"),
            export_options=export_options,
        )


class YouTubeProvider(YtDlpBaseProvider):
    provider_id = "youtube"
    display_name = "YouTube"
    domains = ["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]
    supported_types = [MediaType.VIDEO, MediaType.AUDIO]
    status_label = "active"
    notes = "Публичные видео и Shorts с точным списком реальных разрешений потока и аудиоэкспортом MP3."

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in self.domains or host.endswith(".youtube.com")


class TikTokProvider(YtDlpBaseProvider):
    provider_id = "tiktok"
    display_name = "TikTok"
    domains = ["tiktok.com", "www.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"]
    supported_types = [MediaType.VIDEO, MediaType.AUDIO]
    status_label = "limited"
    notes = "Публичные ролики TikTok без обхода авторизации (доступность зависит от ограничений сети и TLS на стороне провайдера)."

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in self.domains or host.endswith(".tiktok.com")


class InstagramProvider(YtDlpBaseProvider):
    provider_id = "instagram"
    display_name = "Instagram"
    domains = ["instagram.com", "www.instagram.com", "instagr.am"]
    supported_types = [MediaType.VIDEO, MediaType.IMAGE]
    status_label = "limited"
    notes = "Только открытые публичные Reels и публикации, которые платформа отдаёт без входа в аккаунт."

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in self.domains or host.endswith(".instagram.com")


class PinterestProvider(YtDlpBaseProvider):
    provider_id = "pinterest"
    display_name = "Pinterest"
    domains = ["pinterest.com", "www.pinterest.com", "ru.pinterest.com", "pin.it"]
    supported_types = [MediaType.VIDEO, MediaType.IMAGE]
    status_label = "active"
    notes = "Публичные видео-пины и оригинальные изображения из открытых карточек Pinterest."

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in self.domains or host.endswith(".pinterest.com") or host == "pin.it"

    async def _inspect_opengraph_image(self, url: str) -> Optional[MediaInspectResponse]:
        """Fallback for public Pinterest image pins where yt-dlp reports 'No video formats found'."""
        validated_page_url = validate_and_resolve_url(url)
        headers = {
            "User-Agent": "NEXUS-Media/0.1 (+https://github.com/nexus-media; media-inspector)",
            "Accept": "text/html,application/xhtml+xml",
        }
        max_html_bytes = 2_500_000
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(12.0, connect=5.0),
                headers=headers,
            ) as client:
                async with client.stream("GET", validated_page_url) as resp:
                    if resp.status_code != 200:
                        return None
                    ct = (resp.headers.get("content-type") or "").lower()
                    if ct and "html" not in ct:
                        return None
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes(chunk_size=32768):
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= max_html_bytes:
                            break
                    html_chunk = b"".join(chunks)[:max_html_bytes].decode("utf-8", errors="replace")
        except httpx.HTTPError:
            return None

        og: Dict[str, str] = {}
        for tag in META_TAG_RE.findall(html_chunk):
            attrs = {k.lower(): html.unescape(v) for k, v in ATTR_RE.findall(tag)}
            prop = (attrs.get("property") or attrs.get("name") or "").lower()
            content = attrs.get("content")
            if prop.startswith("og:") and content:
                og[prop] = content.strip()

        raw_img_url = og.get("og:image")
        if not raw_img_url:
            return None

        # Validate extracted image URL against SSRF policy
        safe_img_url = validate_and_resolve_url(raw_img_url)
        ext = Path(urlparse(safe_img_url).path).suffix.lower().lstrip(".") or "jpg"
        if ext == "jpeg":
            ext = "jpg"
        if ext not in IMAGE_EXTS:
            ext = "jpg"

        title = (og.get("og:title") or "Изображение Pinterest").strip()
        width = int(og["og:image:width"]) if og.get("og:image:width", "").isdigit() else None
        height = int(og["og:image:height"]) if og.get("og:image:height", "").isdigit() else None

        logger.info("Resolved Pinterest image pin via OpenGraph: %s", sanitize_url_for_log(safe_img_url))
        return MediaInspectResponse(
            url=safe_img_url,
            title=title,
            source_id=self.provider_id,
            source_name=self.display_name,
            media_type=MediaType.IMAGE,
            thumbnail_url=safe_img_url,
            original_ext=ext,
            width=width,
            height=height,
            export_options=[
                ExportOption(
                    format=ExportFormat.IMAGE_ORIGINAL,
                    category=ExportCategory.IMAGE,
                    label=f"Оригинальное изображение ({ext.upper()})",
                    badge="Оригинал",
                    description="Сохранение публичного изображения Pinterest без пережатия.",
                    output_ext=ext,
                    requires_transcoding=False,
                    transcoding_note="Без перекодирования — исходный файл изображения",
                    resolutions=[],
                )
            ],
        )

    async def inspect(
        self,
        url: str,
        headers: Optional[httpx.Headers] = None,
    ) -> MediaInspectResponse:
        try:
            return await super().inspect(url, headers=headers)
        except ProviderError as exc:
            if exc.code in {"EXTRACTION_FAILED", "UNSUPPORTED_SOURCE"}:
                img_result = await self._inspect_opengraph_image(url)
                if img_result is not None:
                    return img_result
            raise


class CompatibleWebProvider(YtDlpBaseProvider):
    provider_id = "compatible"
    display_name = "Совместимый веб-источник"
    domains = ["wikimedia.org", "vimeo.com", "dailymotion.com", "soundcloud.com", "archive.org"]
    supported_types = [MediaType.VIDEO, MediaType.AUDIO, MediaType.IMAGE]
    status_label = "active"
    notes = "Публичные медиастраницы с открытыми потоками (Wikimedia Commons, Vimeo, Archive.org, SoundCloud и др.)."

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        return True
