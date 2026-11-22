import { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowRight,
  CheckCircle2,
  Download,
  FileAudio,
  FileImage,
  Film,
  RotateCcw,
  Search,
  Trash2,
} from 'lucide-react';
import { formatBytes, formatTimestamp, getJobDownloadUrl } from '../api';
import type { JobResponse } from '../types';

type HistoryFilter = 'all' | 'available' | 'archived';

interface CompletedViewProps {
  historyJobs: JobResponse[];
  retryingJobId: string | null;
  onCleanupAll: () => void;
  onRetryJob: (jobId: string) => void;
  onDeleteJob: (jobId: string) => void;
  onDownloadTriggered?: (filename: string) => void;
  cleaning: boolean;
  onGoToInspector: () => void;
}

export function CompletedView({
  historyJobs,
  retryingJobId,
  onCleanupAll,
  onRetryJob,
  onDeleteJob,
  onDownloadTriggered,
  cleaning,
  onGoToInspector,
}: CompletedViewProps) {
  const [filter, setFilter] = useState<HistoryFilter>('all');
  const [query, setQuery] = useState<string>('');

  const availableCount = useMemo(
    () => historyJobs.filter((j) => j.status === 'completed' && j.file_available).length,
    [historyJobs]
  );

  const archivedCount = useMemo(
    () =>
      historyJobs.filter(
        (j) =>
          j.status === 'failed' ||
          j.status === 'cancelled' ||
          (j.status === 'completed' && !j.file_available)
      ).length,
    [historyJobs]
  );

  const filteredJobs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return historyJobs.filter((job) => {
      if (filter === 'available' && !(job.status === 'completed' && job.file_available)) {
        return false;
      }
      if (filter === 'archived' && job.status === 'completed' && job.file_available) {
        return false;
      }
      if (q) {
        const hay = `${job.title} ${job.filename || ''} ${job.source_name}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [historyJobs, filter, query]);

  if (historyJobs.length === 0) {
    return (
      <section className="surface-card empty-state">
        <span className="icon-box">
          <CheckCircle2 size={24} strokeWidth={1.5} />
        </span>
        <h3 className="card-title">История загрузок пуста</h3>
        <p className="card-subtitle">
          Завершённые экспорты видео MP4, аудиоэкспорты MP3 и оригинальные
          изображения сохраняются в локальной базе SQLite и отображаются здесь
        </p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onGoToInspector}
          style={{ marginTop: '8px' }}
        >
          <span>Проверить новую ссылку</span>
          <ArrowRight size={16} strokeWidth={1.5} />
        </button>
      </section>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="history-toolbar">
        <div
          className="filter-group"
          role="tablist"
          aria-label="Фильтр истории"
        >
          <button
            type="button"
            role="tab"
            aria-selected={filter === 'all'}
            className={`filter-pill ${filter === 'all' ? 'active' : ''}`}
            onClick={() => setFilter('all')}
          >
            <span>Все</span>
            <span className="mono">{historyJobs.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filter === 'available'}
            className={`filter-pill ${filter === 'available' ? 'active' : ''}`}
            onClick={() => setFilter('available')}
          >
            <span>Доступны файлы</span>
            <span className="mono">{availableCount}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={filter === 'archived'}
            className={`filter-pill ${filter === 'archived' ? 'active' : ''}`}
            onClick={() => setFilter('archived')}
          >
            <span>Архив и ошибки</span>
            <span className="mono">{archivedCount}</span>
          </button>
        </div>

        <div className="history-toolbar-right">
          <div className="search-input-wrap">
            <span className="search-input-icon" aria-hidden="true">
              <Search size={15} strokeWidth={1.5} />
            </span>
            <input
              type="search"
              className="input-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск по истории"
              aria-label="Поиск по истории загрузок"
            />
          </div>

          <button
            type="button"
            className="btn btn-secondary"
            disabled={cleaning || availableCount === 0}
            onClick={onCleanupAll}
            title="Удаляет временные файлы с диска, сохраняя записи в истории SQLite"
          >
            <Trash2 size={16} strokeWidth={1.5} />
            <span>
              {cleaning ? 'Очистка...' : 'Очистить файлы с диска'}
            </span>
          </button>
        </div>
      </div>

      {filteredJobs.length === 0 ? (
        <section className="surface-card empty-state" style={{ padding: '32px 24px' }}>
          <span className="icon-box">
            <Archive size={22} strokeWidth={1.5} />
          </span>
          <h3 className="card-title">По текущему фильтру записей нет</h3>
          <p className="card-subtitle">
            Попробуйте сбросить поиск или переключить вкладку фильтра
          </p>
        </section>
      ) : (
        <div className="jobs-list" aria-label="История и готовые файлы">
          {filteredJobs.map((job) => {
            const isDownloadable =
              job.status === 'completed' && job.file_available;
            const isExpiredCompleted =
              job.status === 'completed' && !job.file_available;
            const isFailed = job.status === 'failed';
            const isCancelled = job.status === 'cancelled';
            const isRetrying = retryingJobId === job.job_id;

            return (
              <article key={job.job_id} className="job-card">
                <div className="job-card-header">
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '12px',
                      minWidth: 0,
                    }}
                  >
                    <span
                      className="icon-box"
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: '8px',
                        backgroundColor: 'var(--bg-raised)',
                        border: '1px solid var(--border-hairline)',
                        color: isFailed
                          ? 'var(--danger)'
                          : isDownloadable
                          ? 'var(--accent)'
                          : 'var(--text-muted)',
                      }}
                    >
                      {isFailed ? (
                        <AlertTriangle size={18} strokeWidth={1.5} />
                      ) : job.export_category === 'video' ? (
                        <Film size={18} strokeWidth={1.5} />
                      ) : job.export_category === 'audio_export' ? (
                        <FileAudio size={18} strokeWidth={1.5} />
                      ) : (
                        <FileImage size={18} strokeWidth={1.5} />
                      )}
                    </span>

                    <div className="job-title-wrap">
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          flexWrap: 'wrap',
                        }}
                      >
                        <h3 className="job-title">
                          {job.filename || job.title}
                        </h3>
                        {isExpiredCompleted && (
                          <span className="category-tag">
                            Архив · файл удалён
                          </span>
                        )}
                        {isFailed && (
                          <span
                            className="category-tag"
                            style={{
                              borderColor: 'rgba(229, 72, 77, 0.3)',
                              color: 'var(--danger)',
                            }}
                          >
                            {job.error_code === 'INTERRUPTED_BY_RESTART'
                              ? 'Прервано перезапуском'
                              : 'Ошибка'}
                          </span>
                        )}
                        {isCancelled && (
                          <span className="category-tag">Отменено</span>
                        )}
                        {job.attempt_number > 1 && (
                          <span className="category-tag">
                            Попытка {job.attempt_number}
                          </span>
                        )}
                      </div>

                      <div className="job-submeta">
                        <span>{job.source_name}</span>
                        <span>·</span>
                        <span>
                          {job.export_category === 'audio_export'
                            ? `Аудиоэкспорт MP3 (${job.audio_bitrate_kbps} кбит/с)`
                            : job.export_category === 'image'
                            ? `Оригинал (${(
                                job.output_ext || 'IMG'
                              ).toUpperCase()})`
                            : `Видео MP4 (${job.resolution_label || 'Оригинал'})`}
                        </span>
                        {job.file_size_bytes ? (
                          <>
                            <span>·</span>
                            <span>{formatBytes(job.file_size_bytes)}</span>
                          </>
                        ) : null}
                        <span>·</span>
                        <span>{formatTimestamp(job.completed_at || job.created_at)}</span>
                      </div>
                    </div>
                  </div>

                  <div className="job-actions-group">
                    {isDownloadable ? (
                      <a
                        href={getJobDownloadUrl(job.job_id)}
                        download={job.filename || undefined}
                        className="btn btn-primary"
                        onClick={() =>
                          onDownloadTriggered?.(job.filename || job.title)
                        }
                      >
                        <Download size={16} strokeWidth={1.5} />
                        <span>Скачать на устройство</span>
                      </a>
                    ) : (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={isRetrying}
                        onClick={() => onRetryJob(job.job_id)}
                      >
                        <RotateCcw size={16} strokeWidth={1.5} />
                        <span>
                          {isRetrying ? 'Запуск...' : 'Повторить экспорт'}
                        </span>
                      </button>
                    )}

                    <button
                      type="button"
                      className="btn btn-ghost"
                      onClick={() => onDeleteJob(job.job_id)}
                      aria-label={`Удалить запись ${job.title}`}
                      title="Удалить запись из истории SQLite"
                    >
                      <Trash2 size={16} strokeWidth={1.5} />
                    </button>
                  </div>
                </div>

                {(job.error_message || job.transcoding_note) && (
                  <div className="job-status-footer">
                    <span>
                      {isFailed
                        ? job.error_message
                        : `Тракт обработки: ${job.transcoding_note}`}
                    </span>
                    <span className="mono" style={{ fontSize: '12px' }}>
                      {isDownloadable
                        ? `.${job.output_ext || job.export_format}`
                        : isExpiredCompleted
                        ? 'история сохранена'
                        : job.error_code || '—'}
                    </span>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
