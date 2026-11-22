export type MediaType = 'video' | 'audio' | 'image';
export type ExportCategory = 'video' | 'audio_export' | 'image';
export type ExportFormat = 'mp4' | 'mp3' | 'image_original';
export type JobStatus =
  | 'queued'
  | 'downloading'
  | 'converting'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type NavTab = 'home' | 'active' | 'completed' | 'settings';
export type ThemeMode = 'dark' | 'light';
export type SSEConnectionState =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'fallback'
  | 'offline';

export interface AuthStatusResponse {
  auth_required: boolean;
  authenticated: boolean;
}

export interface ResolutionOption {
  id: string;
  label: string;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  vcodec?: string | null;
  acodec?: string | null;
  source_ext?: string | null;
  format_selector: string;
  filesize_bytes?: number | null;
  requires_transcoding: boolean;
  requires_muxing: boolean;
  processing_note: string;
}

export interface ExportOption {
  format: ExportFormat;
  category: ExportCategory;
  label: string;
  badge: string;
  description: string;
  output_ext: string;
  requires_transcoding: boolean;
  transcoding_note: string;
  resolutions: ResolutionOption[];
}

export interface MediaInspectResponse {
  url: string;
  title: string;
  source_id: string;
  source_name: string;
  media_type: MediaType;
  thumbnail_url?: string | null;
  duration_seconds?: number | null;
  uploader?: string | null;
  original_ext?: string | null;
  filesize_approx?: number | null;
  width?: number | null;
  height?: number | null;
  export_options: ExportOption[];
  warnings: string[];
}

export interface JobResponse {
  job_id: string;
  url: string;
  title: string;
  source_id: string;
  source_name: string;
  media_type: MediaType;
  export_format: ExportFormat;
  export_category: ExportCategory;
  resolution_id?: string | null;
  resolution_label?: string | null;
  audio_bitrate_kbps: number;
  requires_transcoding: boolean;
  transcoding_note?: string | null;
  status: JobStatus;
  progress_percent: number;
  progress_known: boolean;
  stage_label: string;
  speed_bytes_per_sec?: number | null;
  eta_seconds?: number | null;
  filename?: string | null;
  file_size_bytes?: number | null;
  output_ext?: string | null;
  file_available: boolean;
  file_expired: boolean;
  thumbnail_url?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  retry_of_job_id?: string | null;
  attempt_number: number;
  created_at: string;
  completed_at?: string | null;
  expires_at?: string | null;
}

export interface ProviderInfo {
  id: string;
  name: string;
  domains: string[];
  supported_types: MediaType[];
  status: string;
  notes: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  auth_required?: boolean;
  authenticated?: boolean;
  unified_frontend_ready?: boolean;
  ffmpeg_available: boolean;
  ytdlp_version: string;
  limits: {
    max_file_size_mb: number;
    max_duration_minutes: number;
    max_concurrent_jobs: number;
    job_ttl_minutes: number;
  };
  storage: {
    used_bytes: number;
    active_jobs: number;
    total_tracked_jobs: number;
    downloadable_files?: number;
  };
  database?: {
    schema_version: number;
    persisted_jobs: number;
    active_sse_clients: number;
  };
}

export interface CleanupResponse {
  removed_jobs: number;
  freed_bytes: number;
  history_preserved?: number;
  message: string;
}

export interface UserPreferences {
  theme: ThemeMode;
  defaultAudioBitrate: 128 | 192 | 256 | 320;
  preferredExportCategory: 'video' | 'audio_export';
}
