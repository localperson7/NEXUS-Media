import type {
  AuthStatusResponse,
  CleanupResponse,
  ExportFormat,
  HealthResponse,
  JobResponse,
  MediaInspectResponse,
  ProviderInfo,
} from './types';

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

async function parseError(resp: Response): Promise<ApiError> {
  try {
    const body = await resp.json();
    const detail = body?.detail || body;
    const code = detail?.code || 'API_ERROR';
    const message =
      detail?.message ||
      (typeof detail === 'string'
        ? detail
        : 'Произошла ошибка при обращении к серверу обработки медиа');
    return new ApiError(code, message, resp.status);
  } catch {
    return new ApiError(
      'NETWORK_ERROR',
      `Сервер вернул статус ${resp.status}`,
      resp.status
    );
  }
}

export async function fetchAuthStatus(): Promise<AuthStatusResponse> {
  const resp = await fetch('/api/auth/status');
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function loginWithAccessToken(
  token: string
): Promise<AuthStatusResponse> {
  const resp = await fetch('/api/auth/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function logoutSession(): Promise<AuthStatusResponse> {
  const resp = await fetch('/api/auth/logout', { method: 'POST' });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const resp = await fetch('/api/health');
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const resp = await fetch('/api/providers');
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function inspectMediaUrl(url: string): Promise<MediaInspectResponse> {
  const resp = await fetch('/api/inspect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function createMediaJob(params: {
  url: string;
  export_format: ExportFormat;
  resolution_id?: string | null;
  audio_bitrate_kbps?: number;
}): Promise<JobResponse> {
  const resp = await fetch('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function fetchJobs(): Promise<JobResponse[]> {
  const resp = await fetch('/api/jobs');
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function cancelMediaJob(jobId: string): Promise<JobResponse> {
  const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function retryMediaJob(jobId: string): Promise<JobResponse> {
  const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function deleteMediaJob(jobId: string): Promise<{ deleted: boolean; job_id: string }> {
  const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export async function cleanupFinishedJobs(): Promise<CleanupResponse> {
  const resp = await fetch('/api/jobs/cleanup', {
    method: 'POST',
  });
  if (!resp.ok) throw await parseError(resp);
  return resp.json();
}

export function getJobDownloadUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/download`;
}

export function formatBytes(bytes?: number | null): string {
  if (bytes === undefined || bytes === null || bytes <= 0) return '—';
  if (bytes < 1024) return `${bytes} Б`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} КБ`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(1)} МБ`;
  const gb = mb / 1024;
  return `${gb.toFixed(2)} ГБ`;
}

export function formatSpeed(bytesPerSec?: number | null): string | null {
  if (bytesPerSec === undefined || bytesPerSec === null || bytesPerSec <= 0) {
    return null;
  }
  if (bytesPerSec < 1024) return `${Math.round(bytesPerSec)} Б/с`;
  const kb = bytesPerSec / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} КБ/с`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)} МБ/с`;
}

export function formatEta(seconds?: number | null): string | null {
  if (seconds === undefined || seconds === null || seconds < 0) return null;
  const s = Math.round(seconds);
  if (s === 0) return '< 1 с';
  if (s < 60) return `~${s} с`;
  const mins = Math.floor(s / 60);
  const rem = s % 60;
  if (mins < 60) return `~${mins} мин ${rem} с`;
  const hrs = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `~${hrs} ч ${remMins} мин`;
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === undefined || seconds === null || seconds < 0) return '—';
  const total = Math.round(seconds);
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  if (hrs > 0) {
    return `${hrs}:${pad(mins)}:${pad(secs)}`;
  }
  return `${mins}:${pad(secs)}`;
}

export function formatTimestamp(iso?: string | null): string {
  if (!iso) return '—';
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return '—';
  return dt.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function mergeJobUpdate(
  current: JobResponse[],
  incoming: JobResponse
): JobResponse[] {
  const exists = current.some((j) => j.job_id === incoming.job_id);
  const next = exists
    ? current.map((j) => (j.job_id === incoming.job_id ? incoming : j))
    : [incoming, ...current];
  return next.sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
}
