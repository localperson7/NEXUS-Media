import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Download,
  RotateCcw,
  Trash2,
  XCircle,
} from 'lucide-react';
import {
  formatBytes,
  formatEta,
  formatSpeed,
  getJobDownloadUrl,
} from '../api';
import type { JobResponse } from '../types';

interface ActiveJobsViewProps {
  jobs: JobResponse[];
  retryingJobId: string | null;
  onCancelJob: (jobId: string) => void;
  onRetryJob: (jobId: string) => void;
  onDeleteJob: (jobId: string) => void;
  onGoToInspector: () => void;
}

function getFormatBadgeLabel(job: JobResponse): string {
  if (job.export_category === 'audio_export') {
    return `Аудиоэкспорт MP3 (${job.audio_bitrate_kbps} кбит/с)`;
  }
  if (job.export_category === 'image') {
    return `Оригинал ${(job.output_ext || 'IMG').toUpperCase()}`;
  }
  return `Видео MP4${job.resolution_label ? ` · ${job.resolution_label}` : ''}`;
}

function getPhaseBadge(status: JobResponse['status']): string {
  switch (status) {
    case 'queued':
      return 'В очереди';
    case 'downloading':
      return 'Загрузка';
    case 'converting':
      return 'Конвертация FFmpeg';
    case 'completed':
      return 'Завершено';
    case 'cancelled':
      return 'Отменено';
    case 'failed':
      return 'Ошибка';
  }
}

export function ActiveJobsView({
  jobs,
  retryingJobId,
  onCancelJob,
  onRetryJob,
  onDeleteJob,
  onGoToInspector,
}: ActiveJobsViewProps) {
  if (jobs.length === 0) {
    return (
      <section className="surface-card empty-state">
        <span className="icon-box">
          <Activity size={24} strokeWidth={1.5} />
        </span>
        <h3 className="card-title">Активных задач обработки нет</h3>
        <p className="card-subtitle">
          Вставьте ссылку в инспекторе медиа, чтобы запустить экспорт видео в
          MP4, аудиоэкспорт в MP3 или сохранение изображения
        </p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onGoToInspector}
          style={{ marginTop: '8px' }}
        >
          <span>Перейти к инспектору</span>
          <ArrowRight size={16} strokeWidth={1.5} />
        </button>
      </section>
    );
  }

  return (
    <div
      className="jobs-list"
      aria-label="Список задач обработки"
      aria-live="polite"
    >
      {jobs.map((job) => {
        const isRunning =
          job.status === 'queued' ||
          job.status === 'downloading' ||
          job.status === 'converting';
        const isCompleted = job.status === 'completed';
        const isFailed = job.status === 'failed';
        const isCancelled = job.status === 'cancelled';
        const clampedPct = Math.max(0, Math.min(100, job.progress_percent));
        const speedStr = formatSpeed(job.speed_bytes_per_sec);
        const etaStr = formatEta(job.eta_seconds);
        const isRetrying = retryingJobId === job.job_id;

        return (
          <article key={job.job_id} className="job-card">
            <div className="job-card-header">
              <div className="job-title-wrap">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flexWrap: 'wrap',
                  }}
                >
                  <h3 className="job-title">{job.title}</h3>
                  <span className="category-tag">{getPhaseBadge(job.status)}</span>
                  {job.attempt_number > 1 && (
                    <span className="category-tag">
                      Попытка {job.attempt_number}
                    </span>
                  )}
                </div>
                <div className="job-submeta">
                  <span>{job.source_name}</span>
                  <span>·</span>
                  <span>{getFormatBadgeLabel(job)}</span>
                  <span>·</span>
                  <span>ID {job.job_id}</span>
                </div>
              </div>

              <div className="job-actions-group">
                {isRunning && (
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => onCancelJob(job.job_id)}
                  >
                    <XCircle size={16} strokeWidth={1.5} />
                    <span>Отменить</span>
                  </button>
                )}

                {isCompleted && job.file_available && (
                  <a
                    href={getJobDownloadUrl(job.job_id)}
                    download={job.filename || undefined}
                    className="btn btn-primary"
                  >
                    <Download size={16} strokeWidth={1.5} />
                    <span>Скачать файл</span>
                  </a>
                )}

                {(isFailed || isCancelled || (isCompleted && !job.file_available)) && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={isRetrying}
                    onClick={() => onRetryJob(job.job_id)}
                  >
                    <RotateCcw size={16} strokeWidth={1.5} />
                    <span>{isRetrying ? 'Запуск...' : 'Повторить'}</span>
                  </button>
                )}

                {!isRunning && (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => onDeleteJob(job.job_id)}
                    aria-label={`Удалить задачу ${job.title} из истории`}
                    title="Удалить запись из истории"
                  >
                    <Trash2 size={16} strokeWidth={1.5} />
                  </button>
                )}
              </div>
            </div>

            {isRunning && (
              <div>
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-label={`Прогресс: ${job.title}`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={
                    job.progress_known ? Math.round(clampedPct) : undefined
                  }
                >
                  {job.progress_known ? (
                    <div
                      className="progress-fill"
                      style={{
                        transform: `scaleX(${clampedPct / 100})`,
                      }}
                    />
                  ) : (
                    <div className="progress-indeterminate" />
                  )}
                </div>
              </div>
            )}

            <div className="job-status-footer">
              <div
                style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
              >
                {isCompleted && (
                  <span
                    className="icon-box"
                    style={{
                      color: job.file_available
                        ? 'var(--accent)'
                        : 'var(--text-muted)',
                    }}
                  >
                    <CheckCircle2 size={16} strokeWidth={1.5} />
                  </span>
                )}
                {isFailed && (
                  <span
                    className="icon-box"
                    style={{ color: 'var(--danger)' }}
                  >
                    <AlertTriangle size={16} strokeWidth={1.5} />
                  </span>
                )}
                {isCancelled && (
                  <span
                    className="icon-box"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    <Ban size={16} strokeWidth={1.5} />
                  </span>
                )}
                <span>
                  {isFailed
                    ? job.error_message || 'Ошибка обработки потока'
                    : isCompleted && !job.file_available
                    ? 'Завершено ранее — временный файл удалён с сервера'
                    : job.stage_label}
                </span>
              </div>

              <div className="job-telemetry-meta mono">
                {isRunning && (
                  <>
                    {job.progress_known ? (
                      <span>{clampedPct.toFixed(0)}%</span>
                    ) : (
                      <span>Обработка...</span>
                    )}
                    {speedStr && (
                      <>
                        <span>·</span>
                        <span>{speedStr}</span>
                      </>
                    )}
                    {etaStr && (
                      <>
                        <span>·</span>
                        <span>осталось {etaStr}</span>
                      </>
                    )}
                  </>
                )}
                {isCompleted && formatBytes(job.file_size_bytes)}
                {isFailed && (job.error_code || 'FAILED')}
                {isCancelled && 'ОТМЕНЕНО'}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}
