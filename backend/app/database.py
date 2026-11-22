import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


MIGRATIONS: List[Tuple[int, str, str]] = [
    (
        1,
        "001_create_jobs_table",
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            media_type TEXT NOT NULL,
            export_format TEXT NOT NULL,
            export_category TEXT NOT NULL,
            resolution_id TEXT,
            resolution_label TEXT,
            audio_bitrate_kbps INTEGER NOT NULL DEFAULT 192,
            requires_transcoding INTEGER NOT NULL DEFAULT 0,
            transcoding_note TEXT,
            status TEXT NOT NULL,
            progress_percent REAL NOT NULL DEFAULT 0.0,
            progress_known INTEGER NOT NULL DEFAULT 0,
            stage_label TEXT NOT NULL,
            speed_bytes_per_sec REAL,
            eta_seconds INTEGER,
            filename TEXT,
            file_size_bytes INTEGER,
            output_ext TEXT,
            output_path TEXT,
            file_available INTEGER NOT NULL DEFAULT 0,
            file_expired INTEGER NOT NULL DEFAULT 0,
            thumbnail_url TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            expires_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);
        """,
    ),
    (
        2,
        "002_add_retry_metadata",
        """
        ALTER TABLE jobs ADD COLUMN retry_of_job_id TEXT;
        ALTER TABLE jobs ADD COLUMN attempt_number INTEGER NOT NULL DEFAULT 1;
        """,
    ),
]


class JobDatabase:
    """Thread-safe SQLite store for NEXUS Media job history and schema migrations."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_initialized()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.db_path.parent, 0o700)
        except OSError:
            pass
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        try:
            if self.db_path.exists():
                os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _ensure_initialized(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    );
                    """
                )
                applied = {
                    row["version"]
                    for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
                }
                for version, name, sql_script in MIGRATIONS:
                    if version in applied:
                        continue
                    conn.executescript(sql_script)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                        (version, name, _iso_now()),
                    )
                conn.commit()

    def get_schema_version(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS ver FROM schema_migrations"
                ).fetchone()
                return int(row["ver"]) if row else 0

    def upsert_job(self, data: Dict[str, Any]) -> None:
        now_iso = _iso_now()
        payload = dict(data)
        payload["updated_at"] = now_iso

        columns = [
            "job_id",
            "url",
            "title",
            "source_id",
            "source_name",
            "media_type",
            "export_format",
            "export_category",
            "resolution_id",
            "resolution_label",
            "audio_bitrate_kbps",
            "requires_transcoding",
            "transcoding_note",
            "status",
            "progress_percent",
            "progress_known",
            "stage_label",
            "speed_bytes_per_sec",
            "eta_seconds",
            "filename",
            "file_size_bytes",
            "output_ext",
            "output_path",
            "file_available",
            "file_expired",
            "thumbnail_url",
            "error_code",
            "error_message",
            "retry_of_job_id",
            "attempt_number",
            "created_at",
            "completed_at",
            "expires_at",
            "updated_at",
        ]
        placeholders = ", ".join(f":{c}" for c in columns)
        update_assignments = ", ".join(
            f"{c} = excluded.{c}" for c in columns if c != "job_id"
        )
        sql = (
            f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(job_id) DO UPDATE SET {update_assignments}"
        )

        with self._lock:
            with self._connect() as conn:
                conn.execute(sql, payload)
                conn.commit()

    def load_all_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC"
                ).fetchall()
                return [dict(r) for r in rows]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                return dict(row) if row else None

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                conn.commit()
                return cur.rowcount > 0

    def count_jobs(self) -> int:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS cnt FROM jobs").fetchone()
                return int(row["cnt"]) if row else 0
