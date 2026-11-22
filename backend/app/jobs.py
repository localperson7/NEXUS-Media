import asyncio
import json
import shutil
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from app.config import settings
from app.database import JobDatabase
from app.media_processor import MediaProcessingError, ProgressUpdate, process_media_job
from app.models import (
    CleanupResponse,
    CreateJobRequest,
    ExportCategory,
    ExportFormat,
    JobResponse,
    JobStatus,
    MediaInspectResponse,
    ResolutionOption,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@dataclass
class JobRecord:
    job_id: str
    url: str
    title: str
    source_id: str
    source_name: str
    media_type: str
    export_format: ExportFormat
    export_category: ExportCategory
    resolution_id: Optional[str]
    resolution_label: Optional[str]
    audio_bitrate_kbps: int
    requires_transcoding: bool
    transcoding_note: Optional[str]
    thumbnail_url: Optional[str]
    job_dir: Path
    status: JobStatus = JobStatus.QUEUED
    progress_percent: float = 0.0
    progress_known: bool = False
    stage_label: str = "В очереди на обработку..."
    speed_bytes_per_sec: Optional[float] = None
    eta_seconds: Optional[int] = None
    output_path: Optional[Path] = None
    filename: Optional[str] = None
    file_size_bytes: Optional[int] = None
    output_ext: Optional[str] = None
    file_available: bool = False
    file_expired: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_of_job_id: Optional[str] = None
    attempt_number: int = 1
    created_at: datetime = field(default_factory=_utc_now)
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    task: Optional[asyncio.Task] = None
    active_process: Optional[asyncio.subprocess.Process] = None

    def sync_file_state(self) -> bool:
        """Return True if file availability changed on disk."""
        prev_avail = self.file_available
        prev_exp = self.file_expired
        if self.status == JobStatus.COMPLETED:
            now = _utc_now()
            is_expired = self.expires_at is not None and now >= self.expires_at
            exists_on_disk = bool(self.output_path and self.output_path.exists() and self.output_path.is_file())
            if is_expired or not exists_on_disk:
                self.file_available = False
                self.file_expired = True
            else:
                self.file_available = True
                self.file_expired = False
        else:
            self.file_available = False
        return (prev_avail != self.file_available) or (prev_exp != self.file_expired)

    def to_db_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "url": self.url,
            "title": self.title,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "media_type": self.media_type,
            "export_format": self.export_format.value,
            "export_category": self.export_category.value,
            "resolution_id": self.resolution_id,
            "resolution_label": self.resolution_label,
            "audio_bitrate_kbps": self.audio_bitrate_kbps,
            "requires_transcoding": 1 if self.requires_transcoding else 0,
            "transcoding_note": self.transcoding_note,
            "status": self.status.value,
            "progress_percent": self.progress_percent,
            "progress_known": 1 if self.progress_known else 0,
            "stage_label": self.stage_label,
            "speed_bytes_per_sec": self.speed_bytes_per_sec,
            "eta_seconds": self.eta_seconds,
            "filename": self.filename,
            "file_size_bytes": self.file_size_bytes,
            "output_ext": self.output_ext,
            "output_path": str(self.output_path) if self.output_path else None,
            "file_available": 1 if self.file_available else 0,
            "file_expired": 1 if self.file_expired else 0,
            "thumbnail_url": self.thumbnail_url,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "retry_of_job_id": self.retry_of_job_id,
            "attempt_number": self.attempt_number,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_db_row(cls, row: Dict[str, Any]) -> "JobRecord":
        job_id = row["job_id"]
        out_path_raw = row.get("output_path")
        return cls(
            job_id=job_id,
            url=row["url"],
            title=row["title"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            media_type=row["media_type"],
            export_format=ExportFormat(row["export_format"]),
            export_category=ExportCategory(row["export_category"]),
            resolution_id=row.get("resolution_id"),
            resolution_label=row.get("resolution_label"),
            audio_bitrate_kbps=int(row.get("audio_bitrate_kbps") or 192),
            requires_transcoding=bool(row.get("requires_transcoding")),
            transcoding_note=row.get("transcoding_note"),
            thumbnail_url=row.get("thumbnail_url"),
            job_dir=settings.storage_root / job_id,
            status=JobStatus(row["status"]),
            progress_percent=float(row.get("progress_percent") or 0.0),
            progress_known=bool(row.get("progress_known")),
            stage_label=row["stage_label"],
            speed_bytes_per_sec=row.get("speed_bytes_per_sec"),
            eta_seconds=row.get("eta_seconds"),
            output_path=Path(out_path_raw) if out_path_raw else None,
            filename=row.get("filename"),
            file_size_bytes=row.get("file_size_bytes"),
            output_ext=row.get("output_ext"),
            file_available=bool(row.get("file_available")),
            file_expired=bool(row.get("file_expired")),
            error_code=row.get("error_code"),
            error_message=row.get("error_message"),
            retry_of_job_id=row.get("retry_of_job_id"),
            attempt_number=int(row.get("attempt_number") or 1),
            created_at=_parse_iso(row.get("created_at")) or _utc_now(),
            completed_at=_parse_iso(row.get("completed_at")),
            expires_at=_parse_iso(row.get("expires_at")),
        )

    def to_response(self) -> JobResponse:
        return JobResponse(
            job_id=self.job_id,
            url=self.url,
            title=self.title,
            source_id=self.source_id,
            source_name=self.source_name,
            media_type=self.media_type,  # type: ignore[arg-type]
            export_format=self.export_format,
            export_category=self.export_category,
            resolution_id=self.resolution_id,
            resolution_label=self.resolution_label,
            audio_bitrate_kbps=self.audio_bitrate_kbps,
            requires_transcoding=self.requires_transcoding,
            transcoding_note=self.transcoding_note,
            status=self.status,
            progress_percent=self.progress_percent,
            progress_known=self.progress_known,
            stage_label=self.stage_label,
            speed_bytes_per_sec=self.speed_bytes_per_sec,
            eta_seconds=self.eta_seconds,
            filename=self.filename,
            file_size_bytes=self.file_size_bytes,
            output_ext=self.output_ext,
            file_available=self.file_available,
            file_expired=self.file_expired,
            thumbnail_url=self.thumbnail_url,
            error_code=self.error_code,
            error_message=self.error_message,
            retry_of_job_id=self.retry_of_job_id,
            attempt_number=self.attempt_number,
            created_at=self.created_at,
            completed_at=self.completed_at,
            expires_at=self.expires_at,
        )


@dataclass
class SSEEvent:
    event_id: int
    event_type: str
    payload: Dict[str, Any]

    def format_sse(self) -> str:
        data_json = json.dumps(self.payload, ensure_ascii=False)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {data_json}\n\n"


class JobManager:
    """Manages SQLite-persisted jobs, isolated directories, concurrency semaphore, cancellation, and SSE broadcast."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = JobDatabase(db_path or settings.database_path)
        self._jobs: Dict[str, JobRecord] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._subscribers: Set[asyncio.Queue[SSEEvent]] = set()
        self._event_seq: int = 0
        self._event_history: Deque[SSEEvent] = deque(maxlen=250)
        self.recover_from_database()

    @property
    def database(self) -> JobDatabase:
        return self._db

    @property
    def active_subscriber_count(self) -> int:
        return len(self._subscribers)

    def reconfigure_database(self, db_path: Path) -> None:
        """Rebind to a new SQLite path (primarily for isolated tests or restart simulations)."""
        self._db = JobDatabase(db_path)
        self._jobs.clear()
        self._event_history.clear()
        self.recover_from_database()

    def recover_from_database(self) -> int:
        """
        Load historical jobs from SQLite on startup.
        Any job left in queued/downloading/converting is marked failed (INTERRUPTED_BY_RESTART)
        and its partial files are removed. Completed jobs verify whether their files still exist.
        """
        rows = self._db.load_all_jobs()
        interrupted_count = 0
        self._jobs.clear()

        for row in rows:
            record = JobRecord.from_db_row(row)
            changed = False

            if record.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.CONVERTING}:
                record.status = JobStatus.FAILED
                record.error_code = "INTERRUPTED_BY_RESTART"
                record.error_message = (
                    "Обработка была прервана перезапуском сервера. Задачу можно запустить повторно."
                )
                record.stage_label = "Прервано перезапуском сервера"
                record.speed_bytes_per_sec = None
                record.eta_seconds = None
                record.file_available = False
                shutil.rmtree(record.job_dir, ignore_errors=True)
                interrupted_count += 1
                changed = True
            else:
                if record.sync_file_state():
                    if record.file_expired and record.job_dir.exists():
                        shutil.rmtree(record.job_dir, ignore_errors=True)
                        record.output_path = None
                    changed = True

            if changed:
                self._db.upsert_job(record.to_db_dict())

            self._jobs[record.job_id] = record

        return interrupted_count

    def _persist(self, record: JobRecord) -> None:
        self._db.upsert_job(record.to_db_dict())

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> SSEEvent:
        self._event_seq += 1
        evt = SSEEvent(event_id=self._event_seq, event_type=event_type, payload=payload)
        self._event_history.append(evt)

        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(evt)
            except asyncio.QueueFull:
                pass
        return evt

    def subscribe(self, last_event_id: Optional[int] = None) -> Tuple[asyncio.Queue[SSEEvent], List[SSEEvent]]:
        """
        Register an SSE subscriber queue.
        Returns (queue, initial_events) where initial_events either replays missed events
        strictly after last_event_id (no duplicates) or emits a full snapshot.
        """
        queue: asyncio.Queue[SSEEvent] = asyncio.Queue(maxsize=128)
        self._subscribers.add(queue)

        initial_events: List[SSEEvent] = []
        if (
            last_event_id is not None
            and self._event_history
            and last_event_id >= self._event_history[0].event_id - 1
            and last_event_id <= self._event_seq
        ):
            initial_events = [e for e in self._event_history if e.event_id > last_event_id]
        else:
            snapshot_payload = {
                "jobs": [j.model_dump(mode="json") for j in self.list_jobs()],
                "event_seq": self._event_seq,
            }
            initial_events = [
                SSEEvent(event_id=self._event_seq, event_type="snapshot", payload=snapshot_payload)
            ]

        return queue, initial_events

    def unsubscribe(self, queue: asyncio.Queue[SSEEvent]) -> None:
        self._subscribers.discard(queue)

    def list_jobs(self) -> List[JobResponse]:
        records = sorted(
            self._jobs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        for r in records:
            if r.sync_file_state():
                self._persist(r)
        return [r.to_response() for r in records]

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        record = self._jobs.get(job_id)
        if record and record.sync_file_state():
            self._persist(record)
        return record

    def create_job(
        self,
        inspect_info: MediaInspectResponse,
        req: CreateJobRequest,
        selected_resolution: Optional[ResolutionOption],
        requires_transcoding: bool,
        transcoding_note: Optional[str],
        allow_loopback: Optional[bool] = None,
        retry_of_job_id: Optional[str] = None,
        attempt_number: int = 1,
    ) -> JobRecord:
        job_id = uuid.uuid4().hex[:12]
        job_dir = settings.storage_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        if req.export_format == ExportFormat.MP3:
            category = ExportCategory.AUDIO_EXPORT
        elif req.export_format == ExportFormat.IMAGE_ORIGINAL:
            category = ExportCategory.IMAGE
        else:
            category = ExportCategory.VIDEO

        record = JobRecord(
            job_id=job_id,
            url=inspect_info.url,
            title=inspect_info.title,
            source_id=inspect_info.source_id,
            source_name=inspect_info.source_name,
            media_type=inspect_info.media_type.value,
            export_format=req.export_format,
            export_category=category,
            resolution_id=selected_resolution.id if selected_resolution else req.resolution_id,
            resolution_label=selected_resolution.label if selected_resolution else None,
            audio_bitrate_kbps=req.audio_bitrate_kbps,
            requires_transcoding=requires_transcoding,
            transcoding_note=transcoding_note,
            thumbnail_url=inspect_info.thumbnail_url,
            job_dir=job_dir,
            retry_of_job_id=retry_of_job_id,
            attempt_number=attempt_number,
        )
        self._jobs[job_id] = record
        self._persist(record)
        self._emit_event("job_update", record.to_response().model_dump(mode="json"))

        record.task = asyncio.create_task(
            self._execute_job(
                record=record,
                inspect_info=inspect_info,
                selected_resolution=selected_resolution,
                audio_bitrate_kbps=req.audio_bitrate_kbps,
                allow_loopback=allow_loopback,
            )
        )
        return record

    async def _execute_job(
        self,
        record: JobRecord,
        inspect_info: MediaInspectResponse,
        selected_resolution: Optional[ResolutionOption],
        audio_bitrate_kbps: int,
        allow_loopback: Optional[bool] = None,
    ) -> None:
        def update_progress(upd: ProgressUpdate) -> None:
            if record.status == JobStatus.CANCELLED:
                return
            status_changed = record.status != upd.status
            record.status = upd.status
            record.progress_percent = upd.progress_percent
            record.progress_known = upd.progress_known
            record.stage_label = upd.stage_label
            record.speed_bytes_per_sec = upd.speed_bytes_per_sec
            record.eta_seconds = upd.eta_seconds
            if status_changed:
                self._persist(record)
            self._emit_event("job_update", record.to_response().model_dump(mode="json"))

        def register_proc(proc: Optional[asyncio.subprocess.Process]) -> None:
            record.active_process = proc

        try:
            async with self._semaphore:
                if record.status == JobStatus.CANCELLED:
                    return
                update_progress(
                    ProgressUpdate(
                        status=JobStatus.DOWNLOADING,
                        stage_label="Подготовка изолированного окружения...",
                        progress_percent=0.0,
                        progress_known=False,
                    )
                )
                final_path = await process_media_job(
                    inspect_info=inspect_info,
                    export_format=record.export_format,
                    selected_resolution=selected_resolution,
                    audio_bitrate_kbps=audio_bitrate_kbps,
                    job_dir=record.job_dir,
                    on_progress=update_progress,
                    register_process=register_proc,
                    allow_loopback=allow_loopback,
                )
                if record.status == JobStatus.CANCELLED:
                    shutil.rmtree(record.job_dir, ignore_errors=True)
                    return

                stat = final_path.stat()
                now = _utc_now()
                record.output_path = final_path
                record.filename = final_path.name
                record.file_size_bytes = stat.st_size
                record.output_ext = final_path.suffix.lstrip(".").lower()
                record.status = JobStatus.COMPLETED
                record.progress_percent = 100.0
                record.progress_known = True
                record.speed_bytes_per_sec = None
                record.eta_seconds = 0
                record.file_available = True
                record.file_expired = False
                record.completed_at = now
                record.expires_at = now + timedelta(seconds=settings.job_ttl_seconds)
                self._persist(record)
                self._emit_event("job_update", record.to_response().model_dump(mode="json"))

        except asyncio.CancelledError:
            record.status = JobStatus.CANCELLED
            record.stage_label = "Загрузка отменена пользователем"
            record.speed_bytes_per_sec = None
            record.eta_seconds = None
            record.file_available = False
            shutil.rmtree(record.job_dir, ignore_errors=True)
            self._persist(record)
            self._emit_event("job_update", record.to_response().model_dump(mode="json"))
        except MediaProcessingError as exc:
            if record.status != JobStatus.CANCELLED:
                record.status = JobStatus.FAILED
                record.error_code = exc.code
                record.error_message = exc.message
                record.stage_label = exc.message
                record.speed_bytes_per_sec = None
                record.eta_seconds = None
                record.file_available = False
                shutil.rmtree(record.job_dir, ignore_errors=True)
                self._persist(record)
                self._emit_event("job_update", record.to_response().model_dump(mode="json"))
        except Exception:
            if record.status != JobStatus.CANCELLED:
                record.status = JobStatus.FAILED
                record.error_code = "INTERNAL_PROCESSING_ERROR"
                record.error_message = "Внутренняя ошибка при обработке медиафайла."
                record.stage_label = "Ошибка обработки"
                record.speed_bytes_per_sec = None
                record.eta_seconds = None
                record.file_available = False
                shutil.rmtree(record.job_dir, ignore_errors=True)
                self._persist(record)
                self._emit_event("job_update", record.to_response().model_dump(mode="json"))

    async def cancel_job(self, job_id: str) -> Optional[JobRecord]:
        record = self._jobs.get(job_id)
        if not record:
            return None

        if record.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return record

        record.status = JobStatus.CANCELLED
        record.stage_label = "Отменено пользователем"
        record.error_code = "USER_CANCELLED"
        record.error_message = "Задача была остановлена по запросу пользователя."
        record.speed_bytes_per_sec = None
        record.eta_seconds = None
        record.file_available = False

        proc = record.active_process
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.sleep(0.1)
                if proc.returncode is None:
                    proc.kill()
            except ProcessLookupError:
                pass

        if record.task and not record.task.done():
            record.task.cancel()
            try:
                await record.task
            except asyncio.CancelledError:
                pass

        shutil.rmtree(record.job_dir, ignore_errors=True)
        self._persist(record)
        self._emit_event("job_update", record.to_response().model_dump(mode="json"))
        return record

    async def delete_job_record(self, job_id: str) -> bool:
        """Delete a single job from history (and clean its files if present)."""
        record = self._jobs.get(job_id)
        if not record:
            return False

        if record.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.CONVERTING}:
            await self.cancel_job(job_id)

        shutil.rmtree(record.job_dir, ignore_errors=True)
        del self._jobs[job_id]
        self._db.delete_job(job_id)
        self._emit_event("job_deleted", {"job_id": job_id})
        return True

    def cleanup_expired_jobs(self, force_all_finished: bool = False) -> CleanupResponse:
        """
        Remove expired (or all finished, when forced) temporary files from disk
        WITHOUT deleting or corrupting SQLite historical records.
        """
        now = _utc_now()
        removed_files_count = 0
        freed_bytes = 0
        history_preserved = 0

        for job_id, record in list(self._jobs.items()):
            is_expired = (
                record.expires_at is not None and now >= record.expires_at
            ) or (
                now - record.created_at > timedelta(seconds=settings.job_ttl_seconds)
            )
            is_finished = record.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }

            if is_finished and (force_all_finished or is_expired):
                had_disk_dir = record.job_dir.exists()
                if had_disk_dir:
                    for f in record.job_dir.rglob("*"):
                        if f.is_file():
                            freed_bytes += f.stat().st_size
                    shutil.rmtree(record.job_dir, ignore_errors=True)
                    removed_files_count += 1

                if record.file_available or not record.file_expired or record.output_path is not None:
                    record.file_available = False
                    record.file_expired = True
                    record.output_path = None
                    self._persist(record)
                    self._emit_event("job_update", record.to_response().model_dump(mode="json"))

                history_preserved += 1

        # Clean up any orphan directories in storage_root not belonging to active jobs
        active_ids = {
            jid
            for jid, rec in self._jobs.items()
            if rec.status in {JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.CONVERTING}
            or rec.file_available
        }
        if settings.storage_root.exists():
            for child in settings.storage_root.iterdir():
                if child.is_dir() and child.name not in active_ids:
                    for f in child.rglob("*"):
                        if f.is_file():
                            freed_bytes += f.stat().st_size
                    shutil.rmtree(child, ignore_errors=True)
                    removed_files_count += 1

        return CleanupResponse(
            removed_jobs=removed_files_count,
            freed_bytes=freed_bytes,
            history_preserved=history_preserved,
            message=f"Удалено временных файлов: {removed_files_count} (история задач сохранена)",
        )


job_manager = JobManager()
