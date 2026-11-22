import asyncio
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx
from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.models import (
    ExportFormat,
    JobStatus,
    MediaInspectResponse,
    ResolutionOption,
)
from app.security import sanitize_filename, validate_and_resolve_url


@dataclass
class ProgressUpdate:
    status: JobStatus
    stage_label: str
    progress_percent: float = 0.0
    progress_known: bool = False
    speed_bytes_per_sec: Optional[float] = None
    eta_seconds: Optional[int] = None


ProgressCallback = Callable[[ProgressUpdate], None]
ProcessRegisterCallback = Callable[[Optional[asyncio.subprocess.Process]], None]

YTDLP_PROGRESS_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
YTDLP_TEMPLATE_PREFIX = "NEXUS_PROG|"


class MediaProcessingError(Exception):
    """Raised when media download or FFmpeg conversion fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_optional_float(raw: str) -> Optional[float]:
    cleaned = raw.strip().rstrip("%")
    if not cleaned or cleaned.lower() in {"na", "none", "unknown", "n/a"}:
        return None
    try:
        val = float(cleaned)
        if val >= 0:
            return val
    except ValueError:
        pass
    return None


def _parse_optional_int(raw: str) -> Optional[int]:
    val = _parse_optional_float(raw)
    if val is None:
        return None
    return int(round(val))


async def _stream_download_direct(
    url: str,
    dest_path: Path,
    on_progress: ProgressCallback,
    allow_loopback: Optional[bool] = None,
) -> int:
    """Safely stream a direct file with redirect validation, strict size cap, and real speed/ETA."""
    current_url = validate_and_resolve_url(url, allow_loopback=allow_loopback)
    headers = {
        "User-Agent": "NEXUS-Media/0.2 (+https://nexus.local; responsible-media-exporter)",
    }

    total_written = 0
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(60.0, connect=10.0),
        headers=headers,
    ) as client:
        for _ in range(6):
            async with client.stream("GET", current_url) as resp:
                if resp.status_code in {301, 302, 303, 307, 308} and resp.headers.get("location"):
                    from urllib.parse import urljoin

                    next_target = urljoin(current_url, resp.headers["location"])
                    current_url = validate_and_resolve_url(next_target, allow_loopback=allow_loopback)
                    continue

                if resp.status_code >= 400:
                    raise MediaProcessingError(
                        "DOWNLOAD_HTTP_ERROR",
                        f"Сервер источника вернул ошибку HTTP {resp.status_code} при загрузке файла.",
                    )

                cl_header = resp.headers.get("content-length")
                expected_total = int(cl_header) if (cl_header and cl_header.isdigit()) else 0
                if expected_total > settings.max_file_size_bytes:
                    raise MediaProcessingError(
                        "LIMIT_EXCEEDED",
                        f"Файл превышает допустимый размер ({settings.max_file_size_bytes // (1024 * 1024)} МБ).",
                    )

                start_ts = time.monotonic()
                last_emit_ts = 0.0
                on_progress(
                    ProgressUpdate(
                        status=JobStatus.DOWNLOADING,
                        stage_label="Загрузка исходного потока...",
                        progress_percent=0.0,
                        progress_known=expected_total > 0,
                    )
                )

                with dest_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        total_written += len(chunk)
                        if total_written > settings.max_file_size_bytes:
                            raise MediaProcessingError(
                                "LIMIT_EXCEEDED",
                                f"Превышен лимит размера загружаемого файла ({settings.max_file_size_bytes // (1024 * 1024)} МБ).",
                            )
                        f.write(chunk)

                        now_ts = time.monotonic()
                        if now_ts - last_emit_ts >= 0.2 or (expected_total > 0 and total_written >= expected_total):
                            last_emit_ts = now_ts
                            elapsed = max(0.001, now_ts - start_ts)
                            speed_bps = total_written / elapsed if elapsed >= 0.02 else None
                            if expected_total > 0:
                                pct = round(min(100.0, (total_written / expected_total) * 100.0), 1)
                                remaining = max(0, expected_total - total_written)
                                eta = int(round(remaining / speed_bps)) if (speed_bps and speed_bps > 0) else None
                                on_progress(
                                    ProgressUpdate(
                                        status=JobStatus.DOWNLOADING,
                                        stage_label="Загрузка исходного потока...",
                                        progress_percent=pct,
                                        progress_known=True,
                                        speed_bytes_per_sec=round(speed_bps, 1) if speed_bps else None,
                                        eta_seconds=eta,
                                    )
                                )
                            else:
                                on_progress(
                                    ProgressUpdate(
                                        status=JobStatus.DOWNLOADING,
                                        stage_label="Загрузка потока (размер источника неизвестен)...",
                                        progress_percent=0.0,
                                        progress_known=False,
                                        speed_bytes_per_sec=round(speed_bps, 1) if speed_bps else None,
                                        eta_seconds=None,
                                    )
                                )
                break
        else:
            raise MediaProcessingError("TOO_MANY_REDIRECTS", "Слишком много перенаправлений при скачивании.")

    if total_written == 0:
        raise MediaProcessingError("EMPTY_FILE", "Источник вернул пустой файл.")

    return total_written


async def _run_ffmpeg(
    args: list[str],
    register_process: ProcessRegisterCallback,
    error_message: str,
    on_progress: Optional[ProgressCallback] = None,
    stage_label: str = "Обработка медиа через FFmpeg...",
    duration_seconds: Optional[float] = None,
) -> None:
    """Execute FFmpeg with strict argument array (no shell interpolation) and real progress parsing."""
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        *args,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    register_process(proc)

    if on_progress:
        on_progress(
            ProgressUpdate(
                status=JobStatus.CONVERTING,
                stage_label=stage_label,
                progress_percent=0.0,
                progress_known=bool(duration_seconds and duration_seconds > 0),
                speed_bytes_per_sec=None,
                eta_seconds=None,
            )
        )

    stderr_chunks: list[bytes] = []

    async def _read_stderr() -> None:
        if proc.stderr:
            stderr_chunks.append(await proc.stderr.read())

    stderr_task = asyncio.create_task(_read_stderr())

    try:
        assert proc.stdout is not None
        out_time_us: Optional[int] = None
        speed_mult: Optional[float] = None
        last_emit_ts = 0.0

        async def _consume_stdout() -> None:
            nonlocal out_time_us, speed_mult, last_emit_ts
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if line.startswith("out_time_us="):
                    raw_us = line.split("=", 1)[1].strip()
                    if raw_us.isdigit():
                        out_time_us = int(raw_us)
                elif line.startswith("speed="):
                    raw_spd = line.split("=", 1)[1].strip().rstrip("x")
                    speed_mult = _parse_optional_float(raw_spd)
                elif line.startswith("progress=") and on_progress:
                    now_ts = time.monotonic()
                    if now_ts - last_emit_ts < 0.2 and not line.endswith("end"):
                        continue
                    last_emit_ts = now_ts
                    if duration_seconds and duration_seconds > 0 and out_time_us is not None:
                        elapsed_media = out_time_us / 1_000_000.0
                        pct = round(min(99.0, max(0.0, (elapsed_media / duration_seconds) * 100.0)), 1)
                        eta: Optional[int] = None
                        if speed_mult and speed_mult > 0.05:
                            remaining_media = max(0.0, duration_seconds - elapsed_media)
                            eta = int(round(remaining_media / speed_mult))
                        on_progress(
                            ProgressUpdate(
                                status=JobStatus.CONVERTING,
                                stage_label=stage_label,
                                progress_percent=pct,
                                progress_known=True,
                                speed_bytes_per_sec=None,
                                eta_seconds=eta,
                            )
                        )

        await asyncio.wait_for(_consume_stdout(), timeout=settings.subprocess_timeout_seconds)
        await asyncio.wait_for(proc.wait(), timeout=15.0)
        await stderr_task
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        stderr_task.cancel()
        raise MediaProcessingError(
            "CONVERSION_TIMEOUT",
            "Превышено допустимое время обработки медиа в FFmpeg.",
        ) from exc
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
        stderr_task.cancel()
        raise
    finally:
        register_process(None)

    if proc.returncode != 0:
        err_detail = (b"".join(stderr_chunks).decode("utf-8", errors="replace")).strip()
        if "does not contain any stream" in err_detail or "Output file does not contain" in err_detail:
            raise MediaProcessingError(
                "NO_AUDIO_STREAM",
                "Исходный видеофайл не содержит аудиодорожки для экспорта в MP3.",
            )
        raise MediaProcessingError("CONVERSION_FAILED", error_message)


async def _has_audio_stream(file_path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(file_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode == 0 and bool(stdout.strip())


async def _run_ytdlp_download(
    url: str,
    format_selector: str,
    job_dir: Path,
    on_progress: ProgressCallback,
    register_process: ProcessRegisterCallback,
) -> Path:
    output_template = str(job_dir / "source_stream.%(ext)s")
    max_size_arg = f"{settings.max_file_size_bytes}"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-exec",
        "--socket-timeout",
        "20",
        "--newline",
        "--progress-template",
        f"download:{YTDLP_TEMPLATE_PREFIX}%(progress._percent_str)s|%(progress.speed)s|%(progress.eta)s",
        "--no-playlist",
        "--no-warnings",
        "--max-filesize",
        max_size_arg,
        "-f",
        format_selector,
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        "--",
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    register_process(proc)
    stderr_chunks: list[bytes] = []

    async def _read_stderr() -> None:
        if proc.stderr:
            stderr_chunks.append(await proc.stderr.read())

    stderr_task = asyncio.create_task(_read_stderr())

    try:
        assert proc.stdout is not None

        async def _consume_ytdlp_stdout() -> None:
            last_emit_ts = 0.0
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()

                now_ts = time.monotonic()
                if line.startswith(YTDLP_TEMPLATE_PREFIX):
                    parts = line[len(YTDLP_TEMPLATE_PREFIX) :].split("|")
                    if len(parts) >= 3:
                        pct = _parse_optional_float(parts[0])
                        spd = _parse_optional_float(parts[1])
                        eta = _parse_optional_int(parts[2])
                        if now_ts - last_emit_ts >= 0.2 or (pct is not None and pct >= 100.0):
                            last_emit_ts = now_ts
                            on_progress(
                                ProgressUpdate(
                                    status=JobStatus.DOWNLOADING,
                                    stage_label="Загрузка медиапотока...",
                                    progress_percent=round(min(100.0, pct), 1) if pct is not None else 0.0,
                                    progress_known=pct is not None,
                                    speed_bytes_per_sec=round(spd, 1) if spd is not None else None,
                                    eta_seconds=eta,
                                )
                            )
                    continue

                match = YTDLP_PROGRESS_RE.search(line)
                if match and (now_ts - last_emit_ts >= 0.2):
                    last_emit_ts = now_ts
                    raw_pct = float(match.group(1))
                    on_progress(
                        ProgressUpdate(
                            status=JobStatus.DOWNLOADING,
                            stage_label="Загрузка медиапотока...",
                            progress_percent=round(min(100.0, raw_pct), 1),
                            progress_known=True,
                        )
                    )

        await asyncio.wait_for(_consume_ytdlp_stdout(), timeout=settings.subprocess_timeout_seconds)
        await asyncio.wait_for(proc.wait(), timeout=15.0)
        await stderr_task
    except asyncio.TimeoutError as exc:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        stderr_task.cancel()
        raise MediaProcessingError(
            "DOWNLOAD_TIMEOUT",
            "Превышено время ожидания загрузки медиапотока.",
        ) from exc
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
        stderr_task.cancel()
        raise
    finally:
        register_process(None)

    if proc.returncode != 0:
        err_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
        err_low = err_text.lower()
        if "file is larger than max-filesize" in err_low:
            raise MediaProcessingError(
                "LIMIT_EXCEEDED",
                f"Размер медиафайла превышает установленный лимит ({settings.max_file_size_bytes // (1024 * 1024)} МБ).",
            )
        if any(tok in err_low for tok in ("timed out", "handshake", "transporterror", "connection reset")):
            raise MediaProcessingError(
                "SOURCE_NETWORK_TIMEOUT",
                "Превышено время ожидания соединения с сервером источника (таймаут TLS/сети).",
            )
        if "http error 429" in err_low or "too many requests" in err_low:
            raise MediaProcessingError(
                "SOURCE_RATE_LIMITED",
                "Источник временно ограничил частоту загрузок (HTTP 429). Повторите позже.",
            )
        if "http error 403" in err_low:
            raise MediaProcessingError(
                "SOURCE_FORBIDDEN",
                "Источник отклонил загрузку медиапотока (HTTP 403).",
            )
        raise MediaProcessingError(
            "DOWNLOAD_FAILED",
            "Не удалось загрузить поток с источника. Возможно, доступ к файлу ограничен.",
        )

    candidates = sorted(
        [p for p in job_dir.glob("source_stream.*") if p.is_file() and not p.name.endswith(".part")],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        raise MediaProcessingError(
            "DOWNLOAD_EMPTY",
            "Не удалось получить медиафайл после завершения загрузки.",
        )
    return candidates[0]


async def process_media_job(
    inspect_info: MediaInspectResponse,
    export_format: ExportFormat,
    selected_resolution: Optional[ResolutionOption],
    audio_bitrate_kbps: int,
    job_dir: Path,
    on_progress: ProgressCallback,
    register_process: ProcessRegisterCallback,
    allow_loopback: Optional[bool] = None,
) -> Path:
    """
    Download and convert/export the media item inside its isolated job directory.
    Returns the final output file Path.
    """
    safe_base = sanitize_filename(inspect_info.title, default="nexus-media")
    duration = inspect_info.duration_seconds

    # 1. IMAGE ORIGINAL EXPORT
    if export_format == ExportFormat.IMAGE_ORIGINAL:
        ext = (inspect_info.original_ext or "jpg").lower().lstrip(".")
        raw_path = job_dir / f"raw_image.{ext}"
        await _stream_download_direct(
            inspect_info.url,
            raw_path,
            on_progress=on_progress,
            allow_loopback=allow_loopback,
        )
        on_progress(
            ProgressUpdate(
                status=JobStatus.CONVERTING,
                stage_label="Проверка целостности оригинального изображения...",
                progress_percent=0.0,
                progress_known=False,
            )
        )
        try:
            with Image.open(raw_path) as img:
                detected_fmt = (img.format or ext).lower()
                img.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise MediaProcessingError(
                "INVALID_IMAGE",
                "Загруженный файл повреждён или не является корректным изображением.",
            ) from exc

        final_ext = "jpg" if detected_fmt == "jpeg" else detected_fmt
        final_path = job_dir / f"{safe_base}.{final_ext}"
        shutil.move(str(raw_path), str(final_path))
        on_progress(
            ProgressUpdate(
                status=JobStatus.COMPLETED,
                stage_label="Оригинальное изображение сохранено",
                progress_percent=100.0,
                progress_known=True,
            )
        )
        return final_path

    # Obtain source file (either via Direct download or yt-dlp)
    if inspect_info.source_id == "direct":
        src_ext = (inspect_info.original_ext or "mp4").lower().lstrip(".")
        source_file = job_dir / f"raw_source.{src_ext}"
        await _stream_download_direct(
            inspect_info.url,
            source_file,
            on_progress=on_progress,
            allow_loopback=allow_loopback,
        )
    else:
        if export_format == ExportFormat.MP3:
            selector = "bestaudio/best"
        elif selected_resolution:
            selector = selected_resolution.format_selector
        else:
            selector = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

        source_file = await _run_ytdlp_download(
            url=inspect_info.url,
            format_selector=selector,
            job_dir=job_dir,
            on_progress=on_progress,
            register_process=register_process,
        )

    # 2. MP3 AUDIO EXPORT
    if export_format == ExportFormat.MP3:
        stage_msg = f"Аудиоэкспорт: кодирование в MP3 ({audio_bitrate_kbps} кбит/с, FFmpeg)..."
        if not await _has_audio_stream(source_file):
            raise MediaProcessingError(
                "NO_AUDIO_STREAM",
                "В исходном медиафайле отсутствует звуковая дорожка для экспорта в MP3.",
            )

        final_mp3 = job_dir / f"{safe_base}.mp3"
        await _run_ffmpeg(
            [
                "-i",
                str(source_file),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                f"{audio_bitrate_kbps}k",
                "-ar",
                "44100",
                str(final_mp3),
            ],
            register_process=register_process,
            error_message="Не удалось выполнить аудиоэкспорт в формат MP3 через FFmpeg.",
            on_progress=on_progress,
            stage_label=stage_msg,
            duration_seconds=duration,
        )

        if not final_mp3.exists() or final_mp3.stat().st_size == 0:
            raise MediaProcessingError("CONVERSION_FAILED", "Результирующий MP3-файл пуст.")

        if source_file.exists() and source_file != final_mp3:
            source_file.unlink(missing_ok=True)

        on_progress(
            ProgressUpdate(
                status=JobStatus.COMPLETED,
                stage_label="Аудиоэкспорт MP3 завершён",
                progress_percent=100.0,
                progress_known=True,
            )
        )
        return final_mp3

    # 3. MP4 VIDEO EXPORT
    res_suffix = f" ({selected_resolution.id})" if selected_resolution and selected_resolution.id != "source" else ""
    final_mp4 = job_dir / f"{safe_base}{res_suffix}.mp4"

    needs_transcode = bool(selected_resolution and selected_resolution.requires_transcoding)
    if not needs_transcode and source_file.suffix.lower() == ".mp4":
        try:
            await _run_ffmpeg(
                [
                    "-i",
                    str(source_file),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(final_mp4),
                ],
                register_process=register_process,
                error_message="Ошибка упаковки контейнера MP4.",
                on_progress=on_progress,
                stage_label="Оптимизация контейнера MP4 (faststart для браузеров и iOS)...",
                duration_seconds=duration,
            )
        except MediaProcessingError:
            needs_transcode = True

    if needs_transcode or not final_mp4.exists():
        vf_args: list[str] = []
        if selected_resolution and selected_resolution.height:
            target_h = selected_resolution.height
            vf_args = ["-vf", f"scale=-2:'min({target_h},ih)'"]

        await _run_ffmpeg(
            [
                "-i",
                str(source_file),
                *vf_args,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(final_mp4),
            ],
            register_process=register_process,
            error_message="Не удалось конвертировать видеопоток в формат MP4 через FFmpeg.",
            on_progress=on_progress,
            stage_label="Перекодирование видеопотока в совместимый MP4 (H.264 / AAC, FFmpeg)...",
            duration_seconds=duration,
        )

    if not final_mp4.exists() or final_mp4.stat().st_size == 0:
        raise MediaProcessingError("CONVERSION_FAILED", "Не удалось сформировать выходной файл MP4.")

    if source_file.exists() and source_file != final_mp4:
        source_file.unlink(missing_ok=True)

    on_progress(
        ProgressUpdate(
            status=JobStatus.COMPLETED,
            stage_label="Видео MP4 готово к сохранению",
            progress_percent=100.0,
            progress_known=True,
        )
    )
    return final_mp4
