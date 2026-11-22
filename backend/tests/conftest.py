import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.jobs import job_manager
from app.rate_limit import rate_limiter


class QuietHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        pass


@pytest.fixture(autouse=True)
def reset_rate_limiter_and_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rate_limiter.reset()
    isolated_storage = tmp_path / "tmp_jobs"
    isolated_storage.mkdir(parents=True, exist_ok=True)
    isolated_db = tmp_path / "storage" / "test_nexus_media.db"
    monkeypatch.setattr(settings, "storage_root", isolated_storage)
    monkeypatch.setattr(settings, "database_path", isolated_db)
    job_manager.reconfigure_database(isolated_db)
    yield


@pytest.fixture(scope="session")
def sample_media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create authorized local synthetic video, silent video, and image files for integration tests."""
    media_dir = tmp_path_factory.mktemp("authorized_media")

    # 1. Valid 640x360 MP4 video with audio track (1.5 seconds)
    video_with_audio = media_dir / "sample_360p.mp4"
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
            "testsrc=duration=1.5:size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(video_with_audio),
        ],
        check=True,
    )

    # 2. Valid 480x270 WebM video without audio track (to test audio extraction failure & webm->mp4 transcode)
    silent_video = media_dir / "silent_clip.mp4"
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
            "color=c=navy:size=480x270:d=1.0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(silent_video),
        ],
        check=True,
    )

    # 3. Original PNG image (800x600)
    sample_img = media_dir / "artwork_original.png"
    img = Image.new("RGB", (800, 600), color=(20, 24, 33))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 700, 500], outline=(76, 195, 138), width=4)
    img.save(sample_img, format="PNG")

    # 4. Corrupted image file with .png extension
    corrupt_img = media_dir / "broken_image.png"
    corrupt_img.write_bytes(b"not-a-valid-png-header-at-all")

    return media_dir


@pytest.fixture(scope="session")
def local_media_server(sample_media_dir: Path) -> Generator[str, None, None]:
    handler = partial(QuietHTTPRequestHandler, directory=str(sample_media_dir))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
