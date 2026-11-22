import { useEffect, useState } from 'react';
import {
  Check,
  Cpu,
  Download,
  FileAudio,
  FileImage,
  Film,
  Loader2,
} from 'lucide-react';
import { formatBytes, formatDuration } from '../api';
import type {
  ExportFormat,
  ExportOption,
  MediaInspectResponse,
  ResolutionOption,
} from '../types';

interface FormatSelectorProps {
  media: MediaInspectResponse;
  defaultAudioBitrate: 128 | 192 | 256 | 320;
  submitting: boolean;
  onStartExport: (params: {
    url: string;
    export_format: ExportFormat;
    resolution_id?: string | null;
    audio_bitrate_kbps: number;
  }) => void;
}

const BITRATE_OPTIONS: Array<128 | 192 | 256 | 320> = [128, 192, 256, 320];

function getMediaTypeLabel(type: MediaInspectResponse['media_type']): string {
  if (type === 'video') return 'Видеопоток';
  if (type === 'audio') return 'Аудиопоток';
  return 'Изображение';
}

export function FormatSelector({
  media,
  defaultAudioBitrate,
  submitting,
  onStartExport,
}: FormatSelectorProps) {
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>(
    media.export_options[0]?.format || 'mp4'
  );
  const [selectedResolutionId, setSelectedResolutionId] = useState<string>('');
  const [audioBitrate, setAudioBitrate] = useState<128 | 192 | 256 | 320>(
    defaultAudioBitrate
  );

  useEffect(() => {
    const firstOpt = media.export_options[0];
    if (firstOpt) {
      setSelectedFormat(firstOpt.format);
      if (firstOpt.resolutions.length > 0) {
        setSelectedResolutionId(firstOpt.resolutions[0].id);
      } else {
        setSelectedResolutionId('');
      }
    }
  }, [media]);

  const activeOption: ExportOption | undefined =
    media.export_options.find((o) => o.format === selectedFormat) ||
    media.export_options[0];

  const activeResolution: ResolutionOption | undefined =
    activeOption?.resolutions.find((r) => r.id === selectedResolutionId) ||
    activeOption?.resolutions[0];

  const handleSelectOption = (opt: ExportOption) => {
    setSelectedFormat(opt.format);
    if (opt.resolutions.length > 0 && !selectedResolutionId) {
      setSelectedResolutionId(opt.resolutions[0].id);
    }
  };

  // Build signature studio technical passport string
  let passportRoute = '';
  let passportNote = '';
  let requiresTranscode = false;

  if (activeOption) {
    if (activeOption.format === 'mp4' && activeResolution) {
      const codec = (activeResolution.vcodec || 'H.264').split('.')[0];
      passportRoute = `[${codec} · ${activeResolution.id} → Контейнер MP4]`;
      passportNote = activeResolution.processing_note;
      requiresTranscode =
        activeResolution.requires_transcoding ||
        activeResolution.requires_muxing;
    } else if (activeOption.format === 'mp3') {
      passportRoute = `[Аудиоэкспорт · FFmpeg libmp3lame · ${audioBitrate} кбит/с → MP3]`;
      passportNote = activeOption.transcoding_note;
      requiresTranscode = activeOption.requires_transcoding;
    } else {
      const extUpper = (activeOption.output_ext || 'IMG').toUpperCase();
      passportRoute = `[Исходный файл · Без пережатия → ${extUpper}]`;
      passportNote = activeOption.transcoding_note;
      requiresTranscode = false;
    }
  }

  return (
    <div className="media-workbench-grid">
      {/* Left Moment: Media Signal Card */}
      <article className="surface-card" aria-label="Превью и паспорт медиафайла">
        <div className="card-section-header">
          <h3 className="card-title">Паспорт источника</h3>
          <span className="category-tag">{media.source_name}</span>
        </div>

        <div className="preview-frame">
          {media.thumbnail_url ? (
            <img
              src={media.thumbnail_url}
              alt={media.title}
              className="preview-img"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="preview-placeholder">
              {media.media_type === 'video' && (
                <Film size={28} strokeWidth={1.5} />
              )}
              {media.media_type === 'audio' && (
                <FileAudio size={28} strokeWidth={1.5} />
              )}
              {media.media_type === 'image' && (
                <FileImage size={28} strokeWidth={1.5} />
              )}
              <span>Превью кадра недоступно</span>
            </div>
          )}

          {media.duration_seconds !== null &&
            media.duration_seconds !== undefined && (
              <span className="preview-timecode">
                {formatDuration(media.duration_seconds)}
              </span>
            )}
        </div>

        <h4 className="media-title">{media.title}</h4>

        <div className="spec-ledger">
          <div className="spec-row">
            <span className="spec-label">Тип сигнала</span>
            <span className="spec-value">
              {getMediaTypeLabel(media.media_type)}
            </span>
          </div>

          <div className="spec-row">
            <span className="spec-label">Платформа / провайдер</span>
            <span className="spec-value">{media.source_name}</span>
          </div>

          {media.uploader && (
            <div className="spec-row">
              <span className="spec-label">Автор / канал</span>
              <span className="spec-value">{media.uploader}</span>
            </div>
          )}

          {media.width && media.height && (
            <div className="spec-row">
              <span className="spec-label">Максимальный кадр источника</span>
              <span className="spec-value">
                {media.width}×{media.height}
              </span>
            </div>
          )}

          {media.original_ext && (
            <div className="spec-row">
              <span className="spec-label">Исходный контейнер</span>
              <span className="spec-value">
                .{media.original_ext.toLowerCase()}
              </span>
            </div>
          )}

          {media.filesize_approx && (
            <div className="spec-row">
              <span className="spec-label">Оценка размера</span>
              <span className="spec-value">
                {formatBytes(media.filesize_approx)}
              </span>
            </div>
          )}
        </div>
      </article>

      {/* Right Moment: Format & Resolution Selector */}
      <section className="surface-card" aria-label="Выбор формата и разрешения">
        <div className="card-section-header">
          <div>
            <h3 className="card-title">Параметры экспорта</h3>
            <p className="card-subtitle">
              Выберите целевой формат сохранения. Показаны только реальные
              потоки источника
            </p>
          </div>
        </div>

        <div
          className="format-options-grid"
          role="radiogroup"
          aria-label="Целевой формат экспорта"
        >
          {media.export_options.map((opt) => {
            const isSelected = opt.format === activeOption?.format;
            return (
              <button
                key={opt.format}
                type="button"
                role="radio"
                aria-checked={isSelected}
                className={`format-card ${isSelected ? 'selected' : ''}`}
                onClick={() => handleSelectOption(opt)}
              >
                <div className="format-card-top">
                  <span className="format-card-title">
                    <span className="icon-box">
                      {opt.category === 'video' && (
                        <Film size={18} strokeWidth={1.5} />
                      )}
                      {opt.category === 'audio_export' && (
                        <FileAudio size={18} strokeWidth={1.5} />
                      )}
                      {opt.category === 'image' && (
                        <FileImage size={18} strokeWidth={1.5} />
                      )}
                    </span>
                    <span>{opt.label}</span>
                  </span>
                  <span className="category-tag">{opt.badge}</span>
                </div>
                <p className="format-card-desc">{opt.description}</p>
              </button>
            );
          })}
        </div>

        {/* Actual Video Resolutions List (Only when MP4 Video is selected) */}
        {activeOption?.format === 'mp4' &&
          activeOption.resolutions.length > 0 && (
            <div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: '10px',
                }}
              >
                <span
                  style={{
                    fontSize: '13px',
                    fontWeight: 500,
                    color: 'var(--text-primary)',
                  }}
                >
                  Доступные разрешения источника (
                  {activeOption.resolutions.length})
                </span>
                <span className="page-context-meta">
                  Без искусственного апскейла
                </span>
              </div>

              <div
                className="resolution-list"
                role="radiogroup"
                aria-label="Доступные разрешения видео"
              >
                {activeOption.resolutions.map((res) => {
                  const isResSelected = res.id === activeResolution?.id;
                  return (
                    <button
                      key={res.id}
                      type="button"
                      role="radio"
                      aria-checked={isResSelected}
                      className={`resolution-row ${
                        isResSelected ? 'selected' : ''
                      }`}
                      onClick={() => setSelectedResolutionId(res.id)}
                    >
                      <div className="resolution-main">
                        <span className="resolution-label">{res.label}</span>
                        <span className="resolution-note">
                          {res.processing_note}
                        </span>
                      </div>
                      <div className="resolution-meta">
                        {res.filesize_bytes ? (
                          <span>{formatBytes(res.filesize_bytes)}</span>
                        ) : null}
                        {isResSelected && (
                          <span
                            className="icon-box"
                            style={{ color: 'var(--accent)' }}
                          >
                            <Check size={16} strokeWidth={1.5} />
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

        {/* Audio Export Bitrate Selection (Only when MP3 Audio Export is selected) */}
        {activeOption?.format === 'mp3' && (
          <div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '10px',
              }}
            >
              <span
                style={{
                  fontSize: '13px',
                  fontWeight: 500,
                  color: 'var(--text-primary)',
                }}
              >
                Битрейт аудиоэкспорта MP3
              </span>
              <span className="page-context-meta">Кодек libmp3lame · 44.1 кГц</span>
            </div>

            <div
              className="bitrate-selector"
              role="radiogroup"
              aria-label="Битрейт MP3"
            >
              {BITRATE_OPTIONS.map((kbps) => (
                <button
                  key={kbps}
                  type="button"
                  role="radio"
                  aria-checked={audioBitrate === kbps}
                  className={`bitrate-btn ${
                    audioBitrate === kbps ? 'selected' : ''
                  }`}
                  onClick={() => setAudioBitrate(kbps)}
                >
                  {kbps} кбит/с
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Signature Detail: Monospace Technical Pipeline Passport */}
        <div className="pipeline-passport">
          <div className="passport-route">
            <span className="icon-box">
              <Cpu size={16} strokeWidth={1.5} />
            </span>
            <span>{passportRoute}</span>
          </div>
          <div className="passport-note">
            {requiresTranscode ? `FFmpeg: ${passportNote}` : passportNote}
          </div>
        </div>

        <button
          type="button"
          className="btn btn-primary btn-lg"
          style={{ width: '100%' }}
          disabled={submitting || !activeOption}
          onClick={() => {
            if (!activeOption) return;
            onStartExport({
              url: media.url,
              export_format: activeOption.format,
              resolution_id:
                activeOption.format === 'mp4'
                  ? activeResolution?.id || null
                  : null,
              audio_bitrate_kbps: audioBitrate,
            });
          }}
        >
          {submitting ? (
            <>
              <Loader2 size={18} strokeWidth={1.5} />
              <span>Запуск задачи обработки...</span>
            </>
          ) : (
            <>
              <Download size={18} strokeWidth={1.5} />
              <span>
                {activeOption?.format === 'mp3'
                  ? `Выполнить аудиоэкспорт MP3 (${audioBitrate} кбит/с)`
                  : activeOption?.format === 'image_original'
                  ? 'Подготовить оригинальное изображение'
                  : `Подготовить видео MP4 (${
                      activeResolution?.id || 'Оригинал'
                    })`}
              </span>
            </>
          )}
        </button>
      </section>
    </div>
  );
}
