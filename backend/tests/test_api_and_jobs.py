import asyncio
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.jobs import job_manager
from app.main import app
from app.models import ExportCategory, ExportFormat, JobStatus


async def _wait_for_terminal_job(client: httpx.AsyncClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
            return data
        await asyncio.sleep(0.15)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


@pytest.mark.asyncio
async def test_health_and_providers_endpoints():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health_resp = await client.get("/api/health")
        assert health_resp.status_code == 200
        h_data = health_resp.json()
        assert h_data["status"] == "ok"
        assert h_data["ffmpeg_available"] is True

        prov_resp = await client.get("/api/providers")
        assert prov_resp.status_code == 200
        prov_ids = [p["id"] for p in prov_resp.json()]
        for expected in ("direct", "youtube", "tiktok", "instagram", "pinterest"):
            assert expected in prov_ids


@pytest.mark.asyncio
async def test_ssrf_blocked_on_inspect_endpoint(local_media_server: str, monkeypatch: pytest.MonkeyPatch):
    """When allow_loopback_for_tests is False (default production setting), localhost is blocked."""
    monkeypatch.setattr(settings, "allow_loopback_for_tests", False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post("/api/inspect", json={"url": f"{local_media_server}/sample_360p.mp4"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "SSRF_BLOCKED"


@pytest.mark.asyncio
async def test_inspect_and_export_mp4_and_mp3_and_image(
    local_media_server: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test real inspection, actual resolution check, MP4 processing, MP3 audio export, and Image download."""
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Inspect 640x360 video
        video_url = f"{local_media_server}/sample_360p.mp4"
        inspect_resp = await client.post("/api/inspect", json={"url": video_url})
        assert inspect_resp.status_code == 200
        info = inspect_resp.json()
        assert info["media_type"] == "video"
        assert info["width"] == 640
        assert info["height"] == 360

        opts = {o["format"]: o for o in info["export_options"]}
        assert "mp4" in opts
        assert "mp3" in opts

        # MP3 must be labeled as an audio export, not a video format
        mp3_opt = opts["mp3"]
        assert mp3_opt["category"] == ExportCategory.AUDIO_EXPORT.value
        assert "Аудиоэкспорт" in mp3_opt["label"]
        assert mp3_opt["requires_transcoding"] is True

        # Only actual resolution (360p) is offered
        mp4_resolutions = opts["mp4"]["resolutions"]
        assert len(mp4_resolutions) == 1
        assert mp4_resolutions[0]["id"] == "360p"
        assert mp4_resolutions[0]["height"] == 360

        # 2. Requesting a non-existent resolution (e.g. 1080p) must be rejected with 422
        bad_res = await client.post(
            "/api/jobs",
            json={"url": video_url, "export_format": "mp4", "resolution_id": "1080p"},
        )
        assert bad_res.status_code == 422
        assert bad_res.json()["detail"]["code"] == "RESOLUTION_NOT_AVAILABLE"

        # 3. Export MP4 at actual 360p resolution
        mp4_job_resp = await client.post(
            "/api/jobs",
            json={"url": video_url, "export_format": "mp4", "resolution_id": "360p"},
        )
        assert mp4_job_resp.status_code == 200
        mp4_job_id = mp4_job_resp.json()["job_id"]
        finished_mp4 = await _wait_for_terminal_job(client, mp4_job_id)
        assert finished_mp4["status"] == JobStatus.COMPLETED.value
        assert finished_mp4["output_ext"] == "mp4"
        assert finished_mp4["file_size_bytes"] > 1000

        dl_mp4 = await client.get(f"/api/jobs/{mp4_job_id}/download")
        assert dl_mp4.status_code == 200
        assert dl_mp4.headers["content-type"] == "video/mp4"
        assert len(dl_mp4.content) == finished_mp4["file_size_bytes"]

        # 4. Export MP3 audio from the same video
        mp3_job_resp = await client.post(
            "/api/jobs",
            json={"url": video_url, "export_format": "mp3", "audio_bitrate_kbps": 192},
        )
        assert mp3_job_resp.status_code == 200
        mp3_job_id = mp3_job_resp.json()["job_id"]
        finished_mp3 = await _wait_for_terminal_job(client, mp3_job_id)
        assert finished_mp3["status"] == JobStatus.COMPLETED.value
        assert finished_mp3["export_category"] == ExportCategory.AUDIO_EXPORT.value
        assert finished_mp3["output_ext"] == "mp3"

        dl_mp3 = await client.get(f"/api/jobs/{mp3_job_id}/download")
        assert dl_mp3.status_code == 200
        assert "audio/mpeg" in dl_mp3.headers["content-type"]
        assert len(dl_mp3.content) > 1000

        # 5. Inspect & download original PNG image
        img_url = f"{local_media_server}/artwork_original.png"
        img_inspect = await client.post("/api/inspect", json={"url": img_url})
        assert img_inspect.status_code == 200
        assert img_inspect.json()["media_type"] == "image"

        img_job_resp = await client.post(
            "/api/jobs",
            json={"url": img_url, "export_format": ExportFormat.IMAGE_ORIGINAL.value},
        )
        assert img_job_resp.status_code == 200
        img_job_id = img_job_resp.json()["job_id"]
        finished_img = await _wait_for_terminal_job(client, img_job_id)
        assert finished_img["status"] == JobStatus.COMPLETED.value
        assert finished_img["output_ext"] == "png"

        dl_img = await client.get(f"/api/jobs/{img_job_id}/download")
        assert dl_img.status_code == 200
        assert dl_img.content.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_conversion_failure_and_corrupt_image_handling(
    local_media_server: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify clear error status when MP3 export is requested on a silent video or corrupt image is downloaded."""
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Silent video has no audio stream -> MP3 extraction must fail cleanly
        silent_url = f"{local_media_server}/silent_clip.mp4"
        job_resp = await client.post(
            "/api/jobs",
            json={"url": silent_url, "export_format": "mp3"},
        )
        assert job_resp.status_code == 200
        job_id = job_resp.json()["job_id"]
        failed_job = await _wait_for_terminal_job(client, job_id)
        assert failed_job["status"] == JobStatus.FAILED.value
        assert failed_job["error_code"] == "NO_AUDIO_STREAM"
        # Temporary directory for failed job must be cleaned up automatically
        assert not (settings.storage_root / job_id).exists()

        # Corrupted PNG file must fail image verification cleanly
        corrupt_url = f"{local_media_server}/broken_image.png"
        c_resp = await client.post(
            "/api/jobs",
            json={"url": corrupt_url, "export_format": "image_original"},
        )
        c_id = c_resp.json()["job_id"]
        failed_img = await _wait_for_terminal_job(client, c_id)
        assert failed_img["status"] == JobStatus.FAILED.value
        assert failed_img["error_code"] == "INVALID_IMAGE"


@pytest.mark.asyncio
async def test_job_cancellation_and_manual_cleanup(
    local_media_server: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Test job cancellation and temporary file cleanup."""
    monkeypatch.setattr(settings, "allow_loopback_for_tests", True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        video_url = f"{local_media_server}/sample_360p.mp4"
        job_resp = await client.post(
            "/api/jobs",
            json={"url": video_url, "export_format": "mp4", "resolution_id": "360p"},
        )
        job_id = job_resp.json()["job_id"]

        # Cancel immediately or wait until finished then test cleanup
        cancel_resp = await client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] in {JobStatus.CANCELLED.value, JobStatus.COMPLETED.value}

        # Create another completed job and run manual cleanup
        img_url = f"{local_media_server}/artwork_original.png"
        j2 = (
            await client.post(
                "/api/jobs",
                json={"url": img_url, "export_format": "image_original"},
            )
        ).json()["job_id"]
        await _wait_for_terminal_job(client, j2)
        assert (settings.storage_root / j2).exists()

        cleanup_resp = await client.post("/api/jobs/cleanup")
        assert cleanup_resp.status_code == 200
        assert cleanup_resp.json()["removed_jobs"] >= 1
        assert not (settings.storage_root / j2).exists()
        assert len(list(settings.storage_root.iterdir())) == 0
