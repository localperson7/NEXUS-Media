import asyncio
import json
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

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

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".mkv", ".ogv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".opus"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


def _human_resolution_label(width: Optional[int], height: Optional[int]) -> str:
    if width and height:
        short_dim = min(width, height)
        if height in {2160, 1440, 1080, 720, 480, 360, 240, 144} and width >= height:
            suffix = " Full HD" if height == 1080 else (" HD" if height == 720 else (" 4K" if height == 2160 else ""))
            return f"{height}p{suffix} ({width}×{height})"
        return f"Исходное ({width}×{height}, {short_dim}p)"
    if height:
        return f"{height}p (Исходное)"
    return "Исходное качество источника"


class DirectMediaProvider(BaseMediaProvider):
    provider_id = "direct"
    display_name = "Прямой медиафайл"
    domains = ["Любой разрешённый HTTPS/HTTP хост с прямой ссылкой на файл"]
    supported_types = [MediaType.VIDEO, MediaType.AUDIO, MediaType.IMAGE]
    status_label = "active"
    notes = "Прямые ссылки на видео (.mp4, .webm, .mov), аудио (.mp3, .wav, .m4a) и оригинальные изображения (.jpg, .png, .webp)."

    def _detect_media_type(
        self,
        url: str,
        content_type: Optional[str] = None,
    ) -> tuple[Optional[MediaType], str]:
        parsed = urlparse(url)
        ext = Path(unquote(parsed.path)).suffix.lower()
        ct = (content_type or "").split(";")[0].strip().lower()

        if ct.startswith("image/") or ext in IMAGE_EXTENSIONS:
            inferred_ext = ext.lstrip(".") if ext in IMAGE_EXTENSIONS else ct.replace("image/", "")
            if inferred_ext == "jpeg":
                inferred_ext = "jpg"
            return MediaType.IMAGE, inferred_ext or "jpg"

        if ct.startswith("video/") or ext in VIDEO_EXTENSIONS:
            inferred_ext = ext.lstrip(".") if ext in VIDEO_EXTENSIONS else ct.replace("video/", "")
            return MediaType.VIDEO, inferred_ext or "mp4"

        if ct.startswith("audio/") or ext in AUDIO_EXTENSIONS:
            inferred_ext = ext.lstrip(".") if ext in AUDIO_EXTENSIONS else ct.replace("audio/", "")
            if inferred_ext == "mpeg":
                inferred_ext = "mp3"
            return MediaType.AUDIO, inferred_ext or "mp3"

        return None, ""

    def matches(self, url: str, content_type: Optional[str] = None) -> bool:
        media_type, _ = self._detect_media_type(url, content_type)
        return media_type is not None

    async def _probe_stream(self, url: str) -> dict:
        """Run ffprobe safely without shell interpolation and with strict HTTP/HTTPS protocol whitelist."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "http,https,tcp,tls",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode == 0 and stdout:
                return json.loads(stdout.decode("utf-8", errors="replace"))
        except Exception:
            pass
        return {}

    async def inspect(
        self,
        url: str,
        headers: Optional[httpx.Headers] = None,
    ) -> MediaInspectResponse:
        if headers is not None:
            raw_status = headers.get("x-nexus-http-status")
            if raw_status and raw_status.isdigit():
                http_status = int(raw_status)
                if http_status in {404, 410}:
                    raise ProviderError(
                        "MEDIA_UNAVAILABLE",
                        f"Файл по указанной ссылке не найден на сервере источника (HTTP {http_status}).",
                        status_code=404,
                    )
                if http_status == 403:
                    raise ProviderError(
                        "SOURCE_FORBIDDEN",
                        "Сервер источника запретил доступ к файлу (HTTP 403).",
                        status_code=403,
                    )
                if http_status == 429:
                    raise ProviderError(
                        "SOURCE_RATE_LIMITED",
                        "Сервер источника временно ограничил частоту запросов (HTTP 429). Повторите позже.",
                        status_code=429,
                    )
                if http_status >= 400:
                    raise ProviderError(
                        "MEDIA_UNAVAILABLE",
                        f"Сервер источника вернул ошибку HTTP {http_status} при проверке файла.",
                        status_code=422,
                    )

        content_type = headers.get("content-type") if headers else None
        content_length_raw = headers.get("content-length") if headers else None
        filesize = int(content_length_raw) if (content_length_raw and content_length_raw.isdigit()) else None

        if filesize and filesize > settings.max_file_size_bytes:
            max_mb = settings.max_file_size_bytes // (1024 * 1024)
            raise ProviderError(
                "LIMIT_EXCEEDED",
                f"Размер файла ({filesize // (1024 * 1024)} МБ) превышает допустимый лимит ({max_mb} МБ).",
                status_code=413,
            )

        media_type, ext = self._detect_media_type(url, content_type)
        if not media_type:
            raise ProviderError(
                "UNSUPPORTED_MEDIA",
                "Не удалось определить тип прямого медиафайла.",
            )

        parsed = urlparse(url)
        raw_name = Path(unquote(parsed.path)).stem or "media-file"
        title = raw_name.replace("_", " ").replace("-", " ").strip() or "Медиафайл"
        host_label = parsed.hostname or "Прямой источник"

        if media_type == MediaType.IMAGE:
            ext_upper = ext.upper()
            export_options = [
                ExportOption(
                    format=ExportFormat.IMAGE_ORIGINAL,
                    category=ExportCategory.IMAGE,
                    label=f"Оригинальное изображение ({ext_upper})",
                    badge="Оригинал",
                    description=f"Прямое сохранение исходного файла .{ext} без пережатия и потери качества.",
                    output_ext=ext,
                    requires_transcoding=False,
                    transcoding_note="Без перекодирования — побитовая копия исходного изображения",
                    resolutions=[],
                )
            ]
            return MediaInspectResponse(
                url=url,
                title=title,
                source_id=self.provider_id,
                source_name=f"Прямой файл ({host_label})",
                media_type=MediaType.IMAGE,
                thumbnail_url=url,
                original_ext=ext,
                filesize_approx=filesize,
                export_options=export_options,
            )

        probe_data = await self._probe_stream(url)
        fmt_info = probe_data.get("format", {})
        streams = probe_data.get("streams", [])

        duration: Optional[float] = None
        if fmt_info.get("duration"):
            try:
                duration = round(float(fmt_info["duration"]), 2)
            except (ValueError, TypeError):
                duration = None

        if duration and duration > settings.max_duration_seconds:
            raise ProviderError(
                "LIMIT_EXCEEDED",
                f"Длительность медиа ({int(duration // 60)} мин) превышает максимальный лимит ({settings.max_duration_seconds // 60} мин).",
                status_code=413,
            )

        if not filesize and fmt_info.get("size"):
            try:
                filesize = int(fmt_info["size"])
            except (ValueError, TypeError):
                pass

        if media_type == MediaType.AUDIO:
            audio_codec = next(
                (s.get("codec_name") for s in streams if s.get("codec_type") == "audio"),
                ext,
            )
            needs_transcode = ext != "mp3" or audio_codec != "mp3"
            note = (
                "Без перекодирования — исходный файл уже в формате MP3"
                if not needs_transcode
                else f"Конвертация из {ext.upper()} ({audio_codec}) в MP3 192 кбит/с через FFmpeg"
            )
            return MediaInspectResponse(
                url=url,
                title=title,
                source_id=self.provider_id,
                source_name=f"Прямое аудио ({host_label})",
                media_type=MediaType.AUDIO,
                duration_seconds=duration,
                original_ext=ext,
                filesize_approx=filesize,
                export_options=[
                    ExportOption(
                        format=ExportFormat.MP3,
                        category=ExportCategory.AUDIO_EXPORT,
                        label="Аудиоэкспорт MP3",
                        badge="Аудиоэкспорт",
                        description="Сохранение аудиодорожки в универсальном формате MP3.",
                        output_ext="mp3",
                        requires_transcoding=needs_transcode,
                        transcoding_note=note,
                        resolutions=[],
                    )
                ],
            )

        # Video inspection: use only the real probed resolution from the stream
        v_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
        width = v_stream.get("width")
        height = v_stream.get("height")
        vcodec = v_stream.get("codec_name")
        acodec = a_stream.get("codec_name")

        fps: Optional[int] = None
        r_frame_rate = v_stream.get("r_frame_rate", "")
        if "/" in str(r_frame_rate):
            num, den = str(r_frame_rate).split("/", 1)
            try:
                if float(den) > 0:
                    fps = round(float(num) / float(den))
            except ValueError:
                pass

        is_native_mp4 = ext == "mp4" and vcodec in {None, "h264", "avc1", "hevc"}
        video_note = (
            "Прямое копирование потока MP4 без перекодирования"
            if is_native_mp4
            else f"Перекодирование контейнера/потока ({ext.upper()} → MP4 H.264/AAC) через FFmpeg"
        )
        res_id = f"{height}p" if height else "source"
        res_label = _human_resolution_label(width, height)

        resolution_option = ResolutionOption(
            id=res_id,
            label=res_label,
            width=width,
            height=height,
            fps=fps,
            vcodec=vcodec,
            acodec=acodec,
            source_ext=ext,
            format_selector="direct_source",
            filesize_bytes=filesize,
            requires_transcoding=not is_native_mp4,
            requires_muxing=False,
            processing_note=video_note,
        )

        export_options = [
            ExportOption(
                format=ExportFormat.MP4,
                category=ExportCategory.VIDEO,
                label="Видео MP4",
                badge="Видео",
                description="Видеофайл в контейнере MP4 в реальном исходном разрешении файла.",
                output_ext="mp4",
                requires_transcoding=not is_native_mp4,
                transcoding_note=video_note,
                resolutions=[resolution_option],
            ),
            ExportOption(
                format=ExportFormat.MP3,
                category=ExportCategory.AUDIO_EXPORT,
                label="Аудиоэкспорт MP3",
                badge="Аудиоэкспорт",
                description="Извлечение аудиодорожки из видеофайла в формат MP3 (192 кбит/с).",
                output_ext="mp3",
                requires_transcoding=True,
                transcoding_note="Требуется извлечение и перекодирование аудиодорожки через FFmpeg (Видео → MP3)",
                resolutions=[],
            ),
        ]

        return MediaInspectResponse(
            url=url,
            title=title,
            source_id=self.provider_id,
            source_name=f"Прямой видеофайл ({host_label})",
            media_type=MediaType.VIDEO,
            duration_seconds=duration,
            original_ext=ext,
            filesize_approx=filesize,
            width=width,
            height=height,
            export_options=export_options,
        )
