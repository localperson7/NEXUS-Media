from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"


class ExportCategory(str, Enum):
    VIDEO = "video"
    AUDIO_EXPORT = "audio_export"
    IMAGE = "image"


class ExportFormat(str, Enum):
    MP4 = "mp4"
    MP3 = "mp3"
    IMAGE_ORIGINAL = "image_original"


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResolutionOption(BaseModel):
    id: str = Field(..., description="Unique resolution identifier, e.g. '1080p', '720p', 'source'")
    label: str = Field(..., description="Display label in Russian, e.g. '1080p Full HD'")
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    source_ext: Optional[str] = None
    format_selector: str = Field(..., description="Internal format selector for processor")
    filesize_bytes: Optional[int] = None
    requires_transcoding: bool = False
    requires_muxing: bool = False
    processing_note: str = Field(
        ...,
        description="Human-readable note about stream remuxing or transcoding",
    )


class ExportOption(BaseModel):
    format: ExportFormat
    category: ExportCategory
    label: str
    badge: str
    description: str
    output_ext: str
    requires_transcoding: bool
    transcoding_note: str
    resolutions: List[ResolutionOption] = Field(default_factory=list)


class InspectRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)


class MediaInspectResponse(BaseModel):
    url: str
    title: str
    source_id: str
    source_name: str
    media_type: MediaType
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[float] = None
    uploader: Optional[str] = None
    original_ext: Optional[str] = None
    filesize_approx: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    export_options: List[ExportOption]
    warnings: List[str] = Field(default_factory=list)


class CreateJobRequest(BaseModel):
    url: str = Field(..., min_length=4, max_length=2048)
    export_format: ExportFormat
    resolution_id: Optional[str] = None
    audio_bitrate_kbps: int = Field(default=192, ge=128, le=320)


class JobResponse(BaseModel):
    job_id: str
    url: str
    title: str
    source_id: str
    source_name: str
    media_type: MediaType
    export_format: ExportFormat
    export_category: ExportCategory
    resolution_id: Optional[str] = None
    resolution_label: Optional[str] = None
    audio_bitrate_kbps: int = 192
    requires_transcoding: bool = False
    transcoding_note: Optional[str] = None
    status: JobStatus
    progress_percent: float = 0.0
    progress_known: bool = False
    stage_label: str
    speed_bytes_per_sec: Optional[float] = None
    eta_seconds: Optional[int] = None
    filename: Optional[str] = None
    file_size_bytes: Optional[int] = None
    output_ext: Optional[str] = None
    file_available: bool = False
    file_expired: bool = False
    thumbnail_url: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_of_job_id: Optional[str] = None
    attempt_number: int = 1
    created_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ProviderInfo(BaseModel):
    id: str
    name: str
    domains: List[str]
    supported_types: List[MediaType]
    status: str
    notes: str


class CleanupResponse(BaseModel):
    removed_jobs: int
    freed_bytes: int
    history_preserved: int = 0
    message: str
