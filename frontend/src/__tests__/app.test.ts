import { describe, expect, it } from 'vitest';
import {
  formatBytes,
  formatDuration,
  formatEta,
  formatSpeed,
  getJobDownloadUrl,
  mergeJobUpdate,
} from '../api';
import type { JobResponse } from '../types';

function makeJob(overrides: Partial<JobResponse>): JobResponse {
  return {
    job_id: 'j1',
    url: 'https://example.com/v.mp4',
    title: 'Sample',
    source_id: 'direct',
    source_name: 'Прямой видеофайл',
    media_type: 'video',
    export_format: 'mp4',
    export_category: 'video',
    audio_bitrate_kbps: 192,
    requires_transcoding: false,
    status: 'downloading',
    progress_percent: 25,
    progress_known: true,
    stage_label: 'Загрузка...',
    file_available: false,
    file_expired: false,
    attempt_number: 1,
    created_at: '2026-11-21T18:00:00Z',
    ...overrides,
  };
}

describe('NEXUS Media Frontend Utilities & M6 State Contracts', () => {
  it('formats byte sizes accurately in Russian with tabular decimals', () => {
    expect(formatBytes(null)).toBe('—');
    expect(formatBytes(0)).toBe('—');
    expect(formatBytes(512)).toBe('512 Б');
    expect(formatBytes(2048)).toBe('2.0 КБ');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 МБ');
  });

  it('formats live download speed and ETA honestly', () => {
    expect(formatSpeed(null)).toBeNull();
    expect(formatSpeed(0)).toBeNull();
    expect(formatSpeed(512 * 1024)).toBe('512.0 КБ/с');
    expect(formatSpeed(3.5 * 1024 * 1024)).toBe('3.5 МБ/с');

    expect(formatEta(null)).toBeNull();
    expect(formatEta(0)).toBe('< 1 с');
    expect(formatEta(18)).toBe('~18 с');
    expect(formatEta(125)).toBe('~2 мин 5 с');
  });

  it('formats timecode durations accurately', () => {
    expect(formatDuration(undefined)).toBe('—');
    expect(formatDuration(19)).toBe('0:19');
    expect(formatDuration(635)).toBe('10:35');
    expect(formatDuration(3665)).toBe('1:01:05');
  });

  it('constructs safe download URLs for completed jobs', () => {
    expect(getJobDownloadUrl('abc123def456')).toBe(
      '/api/jobs/abc123def456/download'
    );
  });

  it('merges SSE job updates without creating duplicate entries and preserves recency sort', () => {
    const older = makeJob({ job_id: 'old', created_at: '2026-11-21T18:00:00Z', progress_percent: 10 });
    const newer = makeJob({ job_id: 'new', created_at: '2026-11-21T18:05:00Z', progress_percent: 5 });
    let list = mergeJobUpdate([older], newer);
    expect(list.map((j) => j.job_id)).toEqual(['new', 'old']);

    // Update existing job via SSE -> no duplicate row
    list = mergeJobUpdate(list, { ...older, status: 'completed', progress_percent: 100, file_available: true });
    expect(list).toHaveLength(2);
    expect(list.find((j) => j.job_id === 'old')?.file_available).toBe(true);
  });
});
