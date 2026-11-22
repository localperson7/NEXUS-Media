import asyncio
import logging
import mimetypes
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, List, Optional
from urllib.parse import quote

import yt_dlp
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.auth import (
    clear_session_cookie,
    enforce_access_control,
    is_auth_enabled,
    is_request_authenticated,
    set_session_cookie,
    verify_access_token,
)
from app.config import ensure_private_dir, settings
from app.jobs import job_manager
from app.models import (
    CleanupResponse,
    CreateJobRequest,
    ExportFormat,
    InspectRequest,
    JobResponse,
    JobStatus,
    MediaInspectResponse,
    ProviderInfo,
    ResolutionOption,
)
from app.providers.base import ProviderError
from app.providers.registry import provider_registry
from app.rate_limit import enforce_rate_limit
from app.security import (
    MediaSecurityError,
    sanitize_url_for_log,
    validate_url_with_redirects,
)

logger = logging.getLogger("nexus_media")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Register PWA manifest MIME type explicitly across Linux distros
mimetypes.add_type("application/manifest+json", ".webmanifest")


class AuthLoginRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


async def _periodic_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(300)
        job_manager.cleanup_expired_jobs(force_all_finished=False)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_private_dir(settings.storage_root)
    ensure_private_dir(settings.database_path.parent)
    interrupted = job_manager.recover_from_database()
    if interrupted:
        logger.warning("Recovered %d interrupted job(s) from SQLite after restart.", interrupted)
    cleanup_task = asyncio.create_task(_periodic_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )
    return response


@app.exception_handler(MediaSecurityError)
async def security_error_handler(_request, exc: MediaSecurityError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


@app.exception_handler(ProviderError)
async def provider_error_handler(_request, exc: ProviderError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


@app.get("/api/auth/status")
async def get_auth_status(request: Request):
    return {
        "auth_required": is_auth_enabled(),
        "authenticated": is_request_authenticated(request),
    }


@app.post(
    "/api/auth/session",
    dependencies=[Depends(enforce_rate_limit)],
)
async def create_auth_session(
    body: AuthLoginRequest,
    request: Request,
    response: Response,
):
    if not is_auth_enabled():
        return {"authenticated": True, "auth_required": False}
    if not verify_access_token(body.token):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_ACCESS_TOKEN",
                "message": "Неверный код доступа к серверу NEXUS Media.",
            },
        )
    set_session_cookie(response, request)
    return {"authenticated": True, "auth_required": True}


@app.post("/api/auth/logout")
async def logout_auth_session(response: Response):
    clear_session_cookie(response)
    return {"authenticated": not is_auth_enabled(), "auth_required": is_auth_enabled()}


@app.get("/api/health")
async def get_health(request: Request):
    auth_enabled = is_auth_enabled()
    authenticated = is_request_authenticated(request)
    if auth_enabled and not authenticated:
        return {
            "status": "ok",
            "version": settings.app_version,
            "auth_required": True,
            "authenticated": False,
        }

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    storage_bytes = 0
    if settings.storage_root.exists():
        for p in settings.storage_root.rglob("*"):
            if p.is_file():
                storage_bytes += p.stat().st_size

    jobs = job_manager.list_jobs()
    active_count = sum(
        1 for j in jobs if j.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.CONVERTING}
    )
    downloadable_count = sum(1 for j in jobs if j.status == JobStatus.COMPLETED and j.file_available)

    return {
        "status": "ok",
        "version": settings.app_version,
        "auth_required": auth_enabled,
        "authenticated": authenticated,
        "unified_frontend_ready": (settings.frontend_dist_dir / "index.html").is_file(),
        "ffmpeg_available": bool(ffmpeg_path and ffprobe_path),
        "ytdlp_version": yt_dlp.version.__version__,
        "limits": {
            "max_file_size_mb": settings.max_file_size_bytes // (1024 * 1024),
            "max_duration_minutes": settings.max_duration_seconds // 60,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            "job_ttl_minutes": settings.job_ttl_seconds // 60,
        },
        "storage": {
            "used_bytes": storage_bytes,
            "active_jobs": active_count,
            "total_tracked_jobs": len(jobs),
            "downloadable_files": downloadable_count,
        },
        "database": {
            "schema_version": job_manager.database.get_schema_version(),
            "persisted_jobs": job_manager.database.count_jobs(),
            "active_sse_clients": job_manager.active_subscriber_count,
        },
    }


@app.get(
    "/api/providers",
    response_model=List[ProviderInfo],
    dependencies=[Depends(enforce_access_control)],
)
async def list_providers():
    return provider_registry.list_providers()


@app.post(
    "/api/inspect",
    response_model=MediaInspectResponse,
    dependencies=[Depends(enforce_access_control), Depends(enforce_rate_limit)],
)
async def inspect_media(req: InspectRequest):
    safe_log_url = sanitize_url_for_log(req.url)
    logger.info("Inspecting media URL: %s", safe_log_url)
    validated_url, headers = await validate_url_with_redirects(req.url)
    result = await provider_registry.inspect_url(validated_url, headers=headers)
    return result


async def _prepare_and_start_job(
    req: CreateJobRequest,
    retry_of_job_id: Optional[str] = None,
    attempt_number: int = 1,
) -> JobResponse:
    safe_log_url = sanitize_url_for_log(req.url)
    logger.info(
        "Creating job for URL: %s (format=%s, res=%s, attempt=%d)",
        safe_log_url,
        req.export_format,
        req.resolution_id,
        attempt_number,
    )

    validated_url, headers = await validate_url_with_redirects(req.url)
    inspect_info = await provider_registry.inspect_url(validated_url, headers=headers)

    matching_opt = next(
        (opt for opt in inspect_info.export_options if opt.format == req.export_format),
        None,
    )
    if not matching_opt:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FORMAT_NOT_SUPPORTED",
                "message": f"Формат «{req.export_format.value}» недоступен для данного типа медиа ({inspect_info.media_type.value}).",
            },
        )

    selected_resolution: Optional[ResolutionOption] = None
    requires_transcoding = matching_opt.requires_transcoding
    transcoding_note = matching_opt.transcoding_note

    if req.export_format == ExportFormat.MP4:
        if not matching_opt.resolutions:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "NO_VIDEO_RESOLUTIONS",
                    "message": "У источника не обнаружено доступных видеопотоков.",
                },
            )
        if req.resolution_id:
            selected_resolution = next(
                (r for r in matching_opt.resolutions if r.id == req.resolution_id),
                None,
            )
            if not selected_resolution:
                available_ids = ", ".join(r.id for r in matching_opt.resolutions)
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "RESOLUTION_NOT_AVAILABLE",
                        "message": f"Разрешение «{req.resolution_id}» не предоставляется источником. Доступные варианты: {available_ids}.",
                    },
                )
        else:
            selected_resolution = matching_opt.resolutions[0]

        requires_transcoding = selected_resolution.requires_transcoding
        transcoding_note = selected_resolution.processing_note

    record = job_manager.create_job(
        inspect_info=inspect_info,
        req=req,
        selected_resolution=selected_resolution,
        requires_transcoding=requires_transcoding,
        transcoding_note=transcoding_note,
        retry_of_job_id=retry_of_job_id,
        attempt_number=attempt_number,
    )
    return record.to_response()


@app.post(
    "/api/jobs",
    response_model=JobResponse,
    dependencies=[Depends(enforce_access_control), Depends(enforce_rate_limit)],
)
async def create_job(req: CreateJobRequest):
    return await _prepare_and_start_job(req)


@app.get(
    "/api/jobs",
    response_model=List[JobResponse],
    dependencies=[Depends(enforce_access_control)],
)
async def list_jobs():
    job_manager.cleanup_expired_jobs(force_all_finished=False)
    return job_manager.list_jobs()


@app.get(
    "/api/jobs/events",
    dependencies=[Depends(enforce_access_control)],
)
async def stream_job_events(
    request: Request,
    last_event_id_header: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: Optional[int] = Query(default=None, alias="last_event_id"),
):
    """Server-Sent Events endpoint streaming live job status, progress, speed, and ETA."""
    parsed_last_id: Optional[int] = last_event_id_query
    if parsed_last_id is None and last_event_id_header:
        try:
            parsed_last_id = int(last_event_id_header.strip())
        except ValueError:
            parsed_last_id = None

    queue, initial_events = job_manager.subscribe(last_event_id=parsed_last_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield "retry: 2500\n\n"
            for init_evt in initial_events:
                yield init_evt.format_sse()

            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield evt.format_sse()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            job_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(
    "/api/jobs/cleanup",
    response_model=CleanupResponse,
    dependencies=[Depends(enforce_access_control)],
)
async def manual_cleanup():
    return job_manager.cleanup_expired_jobs(force_all_finished=True)


@app.get(
    "/api/jobs/{job_id}",
    response_model=JobResponse,
    dependencies=[Depends(enforce_access_control)],
)
async def get_job(job_id: str):
    record = job_manager.get_job(job_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Задача не найдена в истории."},
        )
    return record.to_response()


@app.post(
    "/api/jobs/{job_id}/cancel",
    response_model=JobResponse,
    dependencies=[Depends(enforce_access_control)],
)
async def cancel_job(job_id: str):
    record = await job_manager.cancel_job(job_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Задача не найдена."},
        )
    return record.to_response()


@app.post(
    "/api/jobs/{job_id}/retry",
    response_model=JobResponse,
    dependencies=[Depends(enforce_access_control), Depends(enforce_rate_limit)],
)
async def retry_job(job_id: str):
    existing = job_manager.get_job(job_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Исходная задача не найдена для повторного запуска."},
        )
    if existing.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.CONVERTING}:
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_STILL_RUNNING", "message": "Эта задача уже выполняется."},
        )

    retry_req = CreateJobRequest(
        url=existing.url,
        export_format=existing.export_format,
        resolution_id=existing.resolution_id,
        audio_bitrate_kbps=existing.audio_bitrate_kbps,
    )
    return await _prepare_and_start_job(
        retry_req,
        retry_of_job_id=existing.job_id,
        attempt_number=existing.attempt_number + 1,
    )


@app.delete(
    "/api/jobs/{job_id}",
    dependencies=[Depends(enforce_access_control)],
)
async def delete_job(job_id: str):
    deleted = await job_manager.delete_job_record(job_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Запись не найдена в истории."},
        )
    return {"deleted": True, "job_id": job_id}


def _ascii_fallback_filename(filename: str, ext: str) -> str:
    stem = Path(filename).stem
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not ascii_stem:
        ascii_stem = "nexus-media"
    clean_ext = re.sub(r"[^A-Za-z0-9]+", "", ext or "bin") or "bin"
    return f"{ascii_stem[:80]}.{clean_ext}"


@app.get(
    "/api/jobs/{job_id}/download",
    dependencies=[Depends(enforce_access_control)],
)
async def download_job_file(job_id: str):
    record = job_manager.get_job(job_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "Задача не найдена в истории."},
        )
    if record.status == JobStatus.COMPLETED and not record.file_available:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "FILE_EXPIRED",
                "message": "Временный файл уже удалён с сервера. Вы можете повторно запустить экспорт из истории.",
            },
        )
    if record.status != JobStatus.COMPLETED or not record.output_path or not record.output_path.exists():
        raise HTTPException(
            status_code=409,
            detail={"code": "FILE_NOT_READY", "message": "Файл ещё не готов к скачиванию."},
        )

    filename = record.filename or record.output_path.name
    ext = record.output_ext or record.output_path.suffix.lstrip(".").lower() or "bin"
    media_type, _ = mimetypes.guess_type(filename)
    if not media_type:
        if ext == "mp4":
            media_type = "video/mp4"
        elif ext == "mp3":
            media_type = "audio/mpeg"
        elif ext in {"jpg", "jpeg"}:
            media_type = "image/jpeg"
        elif ext == "png":
            media_type = "image/png"
        elif ext == "webp":
            media_type = "image/webp"
        else:
            media_type = "application/octet-stream"

    ascii_fallback = _ascii_fallback_filename(filename, ext)
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}',
        "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=record.output_path,
        media_type=media_type,
        headers=headers,
    )


# --- M7.1: Unified Production Frontend Serving & Client-Side Fallback Routing ---

@app.api_route("/api/{unknown_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def api_not_found(unknown_path: str):
    return JSONResponse(
        status_code=404,
        content={
            "code": "API_ROUTE_NOT_FOUND",
            "message": f"Маршрут API «/api/{unknown_path}» не существует.",
        },
    )


def _serve_frontend_asset(requested_path: str) -> Response:
    dist_root = settings.frontend_dist_dir.resolve()
    index_file = dist_root / "index.html"
    if not index_file.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "code": "FRONTEND_NOT_BUILT",
                "message": "Production-сборка фронтенда не найдена. Выполните `npm run build` в каталоге frontend/.",
            },
        )

    cleaned = requested_path.lstrip("/")
    if cleaned:
        candidate = (dist_root / cleaned).resolve()
        # Prevent path traversal outside frontend/dist
        if candidate.is_relative_to(dist_root) and candidate.is_file():
            media_type, _ = mimetypes.guess_type(str(candidate))
            if cleaned in {"sw.js", "manifest.webmanifest", "index.html"}:
                cache_hdr = "no-cache"
            elif cleaned.startswith("assets/"):
                cache_hdr = "public, max-age=31536000, immutable"
            else:
                cache_hdr = "public, max-age=3600"
            return FileResponse(
                path=candidate,
                media_type=media_type,
                headers={"Cache-Control": cache_hdr},
            )

    # Client-side SPA fallback route
    return FileResponse(
        path=index_file,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_spa_root():
    return _serve_frontend_asset("")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa_fallback(full_path: str):
    return _serve_frontend_asset(full_path)
