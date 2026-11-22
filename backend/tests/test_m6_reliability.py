import asyncio
import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.database import JobDatabase
from app.jobs import JobManager, job_manager
from app.main import app
from app.models import ExportCategory, ExportFormat, JobStatus
from app.security import MediaSecurityError, validate_url_with_redirects


async def _wait_for_terminal(client: httpx.AsyncClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            return data
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


def test_sqlite_migrations_idempotency_and_integrity(tmp_path: Path):
    db_file = tmp_path / "integrity.db"
    db1 = JobDatabase(db_file)
    assert db1.get_schema_version() == 2

    # Re-opening the same DB must be idempotent and keep schema version 2
    db2 = JobDatabase(db_file)
    assert db2.get_schema_version() == 2
    assert db2.count_jobs() == 0


def test_restart_recovery_marks_interrupted_jobs_failed_and_preserves_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage_dir = tmp_path / "tmp_jobs"
    storage_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "storage" / "restart_test.db"
    monkeypatch.setattr(settings, "storage_root", storage_dir)
    monkeypatch.setattr(settings, "database_path", db_file)

    db = JobDatabase(db_file)
    now_iso = datetime.now(timezone.utc).isoformat()
    future_iso = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    # Create partial temp folders for interrupted jobs
    for jid, status in [("job_q", "queued"), ("job_d", "downloading"), ("job_c", "converting")]:
        d = storage_dir / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "partial.bin").write_bytes(b"incomplete-data")
        db.upsert_job(
            {
                "job_id": jid,
                "url": "https://example.com/video.mp4",
                "title": f"Interrupted {jid}",
                "source_id": "direct",
                "source_name": "Прямой видеофайл",
                "media_type": "video",
                "export_format": "mp4",
                "export_category": "video",
                "resolution_id": "720p",
                "resolution_label": "720p HD",
                "audio_bitrate_kbps": 192,
                "requires_transcoding": 0,
                "transcoding_note": "copy",
                "status": status,
                "progress_percent": 42.0,
                "progress_known": 1,
                "stage_label": "Загрузка...",
                "speed_bytes_per_sec": 120000.0,
                "eta_seconds": 15,
                "filename": None,
                "file_size_bytes": None,
                "output_ext": None,
                "output_path": None,
                "file_available": 0,
                "file_expired": 0,
                "thumbnail_url": None,
                "error_code": None,
                "error_message": None,
                "retry_of_job_id": None,
                "attempt_number": 1,
                "created_at": now_iso,
                "completed_at": None,
                "expires_at": None,
            }
        )

    # Create one completed job whose file STILL exists on disk, and one whose file is missing
    valid_dir = storage_dir / "job_ok"
    valid_dir.mkdir(parents=True, exist_ok=True)
    valid_file = valid_dir / "done.mp4"
    valid_file.write_bytes(b"mp4-placeholder")

    for jid, path_str in [("job_ok", str(valid_file)), ("job_gone", str(storage_dir / "job_gone" / "gone.mp4"))]:
        db.upsert_job(
            {
                "job_id": jid,
                "url": "https://example.com/ok.mp4",
                "title": f"Completed {jid}",
                "source_id": "direct",
                "source_name": "Прямой видеофайл",
                "media_type": "video",
                "export_format": "mp4",
                "export_category": "video",
                "resolution_id": "360p",
                "resolution_label": "360p",
                "audio_bitrate_kbps": 192,
                "requires_transcoding": 0,
                "transcoding_note": "copy",
                "status": "completed",
                "progress_percent": 100.0,
                "progress_known": 1,
                "stage_label": "Готово",
                "speed_bytes_per_sec": None,
                "eta_seconds": 0,
                "filename": "done.mp4",
                "file_size_bytes": 15,
                "output_ext": "mp4",
                "output_path": path_str,
                "file_available": 1,
                "file_expired": 0,
                "thumbnail_url": None,
                "error_code": None,
                "error_message": None,
                "retry_of_job_id": None,
                "attempt_number": 1,
                "created_at": now_iso,
                "completed_at": now_iso,
                "expires_at": future_iso,
            }
        )

    # Simulate backend restart by creating a fresh JobManager reading the same SQLite DB
    restarted_manager = JobManager(db_path=db_file)
    all_jobs = {j.job_id: j for j in restarted_manager.list_jobs()}
    assert len(all_jobs) == 5

    for jid in ("job_q", "job_d", "job_c"):
        assert all_jobs[jid].status == JobStatus.FAILED
        assert all_jobs[jid].error_code == "INTERRUPTED_BY_RESTART"
        assert all_jobs[jid].file_available is False
        assert not (storage_dir / jid).exists()

    assert all_jobs["job_ok"].status == JobStatus.COMPLETED
    assert all_jobs["job_ok"].file_available is True
    assert all_jobs["job_ok"].file_expired is False

    assert all_jobs["job_gone"].status == JobStatus.COMPLETED
    assert all_jobs["job_gone"].file_available is False
    assert all_jobs["job_gone"].file_expired is True


@pytest.mark.asyncio
async def test_cleanup_preserves_history_and_retry_and_delete(
    local_media_server: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        img_url = f"{local_media_server}/artwork_original.png"
        create_resp = await client.post(
            "/api/jobs",
            json={"url": img_url, "export_format": ExportFormat.IMAGE_ORIGINAL.value},
        )
        assert create_resp.status_code == 200
        job_id = create_resp.json()["job_id"]
        done = await _wait_for_terminal(client, job_id)
        assert done["status"] == JobStatus.COMPLETED.value
        assert done["file_available"] is True

        # Clean up temporary files — disk file disappears, but history stays in SQLite!
        clean_resp = await client.post("/api/jobs/cleanup")
        assert clean_resp.status_code == 200
        assert clean_resp.json()["removed_jobs"] >= 1
        assert clean_resp.json()["history_preserved"] >= 1
        assert not (settings.storage_root / job_id).exists()

        # Record still exists in history with file_available=False, file_expired=True
        hist_resp = await client.get(f"/api/jobs/{job_id}")
        assert hist_resp.status_code == 200
        hist = hist_resp.json()
        assert hist["status"] == JobStatus.COMPLETED.value
        assert hist["file_available"] is False
        assert hist["file_expired"] is True

        # Download of expired file returns 410 Gone with clear Russian message
        dl_expired = await client.get(f"/api/jobs/{job_id}/download")
        assert dl_expired.status_code == 410
        assert dl_expired.json()["detail"]["code"] == "FILE_EXPIRED"

        # Retry the expired job -> creates a linked job (attempt_number=2) that downloads fresh copy
        retry_resp = await client.post(f"/api/jobs/{job_id}/retry")
        assert retry_resp.status_code == 200
        retry_data = retry_resp.json()
        assert retry_data["retry_of_job_id"] == job_id
        assert retry_data["attempt_number"] == 2
        retry_done = await _wait_for_terminal(client, retry_data["job_id"])
        assert retry_done["status"] == JobStatus.COMPLETED.value
        assert retry_done["file_available"] is True

        # Delete the original history record
        del_resp = await client.delete(f"/api/jobs/{job_id}")
        assert del_resp.status_code == 200
        assert (await client.get(f"/api/jobs/{job_id}")).status_code == 404


@pytest.mark.asyncio
async def test_simultaneous_downloads_and_concurrency_safety(
    local_media_server: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        video_url = f"{local_media_server}/sample_360p.mp4"
        img_url = f"{local_media_server}/artwork_original.png"

        # Launch 4 simultaneous jobs (> default semaphore of 3)
        payloads = [
            {"url": video_url, "export_format": "mp4", "resolution_id": "360p"},
            {"url": video_url, "export_format": "mp3", "audio_bitrate_kbps": 192},
            {"url": img_url, "export_format": "image_original"},
            {"url": video_url, "export_format": "mp3", "audio_bitrate_kbps": 128},
        ]
        responses = await asyncio.gather(*[client.post("/api/jobs", json=p) for p in payloads])
        job_ids = []
        for r in responses:
            assert r.status_code == 200
            job_ids.append(r.json()["job_id"])

        results = await asyncio.gather(*[_wait_for_terminal(client, jid) for jid in job_ids])
        for res in results:
            assert res["status"] == JobStatus.COMPLETED.value
            assert res["file_available"] is True
            assert res["file_size_bytes"] > 500


@pytest.mark.asyncio
async def test_cancellation_during_ffmpeg_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Create a 12-second video served locally and cancel mid-conversion to ensure clean FFmpeg shutdown."""
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    media_file = tmp_path / "long_sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=12:size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(media_file),
        ],
        check=True,
    )

    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class SilentHandler(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SilentHandler, directory=str(tmp_path)))
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/jobs",
                json={"url": f"http://127.0.0.1:{port}/long_sample.mp4", "export_format": "mp3", "audio_bitrate_kbps": 320},
            )
            assert resp.status_code == 200
            jid = resp.json()["job_id"]
            await asyncio.sleep(0.05)
            cancel_resp = await client.post(f"/api/jobs/{jid}/cancel")
            assert cancel_resp.status_code == 200
            status = cancel_resp.json()["status"]
            assert status in {JobStatus.CANCELLED.value, JobStatus.COMPLETED.value}
            if status == JobStatus.CANCELLED.value:
                assert not (settings.storage_root / jid).exists()
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.asyncio
async def test_sse_subscription_deduplication_and_no_leak():
    """Verify SSE snapshot, Last-Event-ID replay without duplicates, and clean unsubscribe."""
    assert job_manager.active_subscriber_count == 0
    q1, init1 = job_manager.subscribe()
    assert job_manager.active_subscriber_count == 1
    assert len(init1) == 1
    assert init1[0].event_type == "snapshot"

    evt_a = job_manager._emit_event("job_update", {"job_id": "test1", "status": "downloading"})
    evt_b = job_manager._emit_event("job_update", {"job_id": "test1", "status": "converting"})

    got_a = await asyncio.wait_for(q1.get(), timeout=1.0)
    got_b = await asyncio.wait_for(q1.get(), timeout=1.0)
    assert got_a.event_id == evt_a.event_id
    assert got_b.event_id == evt_b.event_id

    # Reconnect with Last-Event-ID = evt_a.event_id -> must receive ONLY evt_b (no duplicate evt_a)
    q2, replay = job_manager.subscribe(last_event_id=evt_a.event_id)
    assert job_manager.active_subscriber_count == 2
    assert [e.event_id for e in replay] == [evt_b.event_id]

    job_manager.unsubscribe(q1)
    job_manager.unsubscribe(q2)
    assert job_manager.active_subscriber_count == 0


@pytest.mark.asyncio
async def test_ssrf_redirect_to_cloud_metadata_blocked():
    """Verify a redirect from an allowed host to 169.254.169.254 is rejected with SSRF_BLOCKED."""

    class RedirectToMetadataHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        def do_GET(self):
            self.do_HEAD()

        def log_message(self, format: str, *args) -> None:
            pass

    srv = HTTPServer(("127.0.0.1", 0), RedirectToMetadataHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    try:
        with pytest.raises(MediaSecurityError) as exc_info:
            await validate_url_with_redirects(
                f"http://127.0.0.1:{port}/start",
                allow_loopback=True,
            )
        assert exc_info.value.code == "SSRF_BLOCKED"
        assert exc_info.value.status_code == 403
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.asyncio
async def test_failed_provider_request_returns_structured_error():
    """Verify failed/unsupported provider inspection returns clean structured Russian error."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/inspect",
            json={"url": "https://nonexistent.invalid.nexus-domain.example/video.mp4"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "DNS_RESOLUTION_FAILED"
        assert "Не удалось разрешить" in body["message"]


@pytest.mark.asyncio
async def test_sse_http_stream_snapshot_and_disconnect_cleanup():
    """Verify GET /api/jobs/events streams valid SSE snapshot and cleans up subscriber on disconnect."""
    from app.main import stream_job_events

    class FakeRequest:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks >= 1

    resp = await stream_job_events(
        request=FakeRequest(),  # type: ignore[arg-type]
        last_event_id_header=None,
        last_event_id_query=None,
    )
    assert resp.media_type == "text/event-stream"
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))

    full_stream = "".join(chunks)
    assert "retry: 2500" in full_stream
    assert "event: snapshot" in full_stream
    # After stream ends / disconnects, subscriber must be unsubscribed with zero leaks
    assert job_manager.active_subscriber_count == 0
