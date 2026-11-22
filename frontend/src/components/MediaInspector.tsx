import React, { useEffect, useRef, useState } from 'react';
import {
  AlertCircle,
  Check,
  ClipboardPaste,
  Link2,
  Loader2,
  Search,
  X,
} from 'lucide-react';

interface MediaInspectorProps {
  url: string;
  onChangeUrl: (val: string) => void;
  onInspect: (targetUrl?: string) => void;
  onClearError?: () => void;
  inspecting: boolean;
  error: { code: string; message: string } | null;
}

const PUBLIC_SAMPLES = [
  {
    label: 'YouTube 4K (Big Buck Bunny)',
    url: 'https://www.youtube.com/watch?v=aqz-KE-bpKQ',
  },
  {
    label: 'YouTube 240p (Me at the zoo)',
    url: 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
  },
  {
    label: 'Прямое видео MP4 (MDN CC0)',
    url: 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
  },
  {
    label: 'Оригинал JPG (Wikimedia)',
    url: 'https://upload.wikimedia.org/wikipedia/commons/a/a7/Camponotus_flavomarginatus_ant.jpg',
  },
];

function getErrorHeading(code: string): string {
  switch (code) {
    case 'SOURCE_NETWORK_TIMEOUT':
    case 'INSPECT_TIMEOUT':
      return 'Источник не отвечает (таймаут сети / TLS)';
    case 'DNS_RESOLUTION_FAILED':
      return 'Домен источника не найден';
    case 'SSRF_BLOCKED':
    case 'UNSUPPORTED_PROTOCOL':
    case 'CREDENTIALS_IN_URL':
      return 'Заблокировано политикой безопасности';
    case 'PRIVATE_OR_AUTH_REQUIRED':
    case 'DRM_PROTECTED':
    case 'SOURCE_FORBIDDEN':
      return 'Доступ ограничен платформой';
    case 'SOURCE_RATE_LIMITED':
    case 'RATE_LIMITED':
      return 'Временное ограничение частоты запросов';
    case 'MEDIA_UNAVAILABLE':
      return 'Медиафайл недоступен';
    case 'SERVER_OFFLINE':
      return 'Нет связи с сервером NEXUS Media';
    default:
      return 'Не удалось проанализировать ссылку';
  }
}

export function MediaInspector({
  url,
  onChangeUrl,
  onInspect,
  onClearError,
  inspecting,
  error,
}: MediaInspectorProps) {
  const [pasteFeedback, setPasteFeedback] = useState<'idle' | 'pasted' | 'denied'>('idle');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (pasteFeedback === 'idle') return;
    const t = window.setTimeout(() => setPasteFeedback('idle'), 1800);
    return () => window.clearTimeout(t);
  }, [pasteFeedback]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim() || inspecting) return;
    onInspect();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      if (error && onClearError) {
        onClearError();
      } else if (url) {
        onChangeUrl('');
      }
    }
  };

  const isTouchDevice =
    typeof window !== 'undefined' &&
    window.matchMedia('(pointer: coarse)').matches;

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text && text.trim()) {
        onChangeUrl(text.trim());
        setPasteFeedback('pasted');
        inputRef.current?.focus();
      }
    } catch {
      setPasteFeedback('denied');
      inputRef.current?.focus();
    }
  };

  return (
    <section className="surface-card" aria-label="Инспекция медиассылки">
      <div className="card-section-header">
        <div>
          <h2 className="card-title">Источник медиапотока</h2>
          <p className="card-subtitle">
            Вставьте ссылку на открытое видео, аудио или оригинальное
            изображение, которое вы имеете право сохранить
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} noValidate>
        <div className="url-input-bar">
          <div className="url-input-wrapper">
            <span className="url-input-icon" aria-hidden="true">
              <Link2 size={18} strokeWidth={1.5} />
            </span>
            <input
              ref={inputRef}
              type="url"
              className="input-url"
              value={url}
              onChange={(e) => onChangeUrl(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="https://www.youtube.com/watch?v=... или прямая ссылка на файл"
              aria-label="Ссылка на медиафайл"
              aria-invalid={Boolean(error)}
              autoComplete="off"
              spellCheck={false}
              required
            />
            <div className="input-quick-actions">
              {url ? (
                <button
                  type="button"
                  className="keycap-btn"
                  onClick={() => {
                    onChangeUrl('');
                    onClearError?.();
                    inputRef.current?.focus();
                  }}
                  aria-label="Очистить поле ссылки"
                >
                  <X size={14} strokeWidth={1.5} />
                  <span>Сброс</span>
                </button>
              ) : (
                <button
                  type="button"
                  className="keycap-btn"
                  onClick={handlePaste}
                  title="Вставить из буфера обмена"
                >
                  {pasteFeedback === 'pasted' ? (
                    <>
                      <Check size={14} strokeWidth={1.5} />
                      <span>Вставлено</span>
                    </>
                  ) : (
                    <>
                      <ClipboardPaste size={14} strokeWidth={1.5} />
                      <span>
                        {pasteFeedback === 'denied'
                          ? isTouchDevice
                            ? 'Вставьте в поле'
                            : 'Ctrl+V'
                          : 'Буфер'}
                      </span>
                    </>
                  )}
                </button>
              )}
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            disabled={inspecting || !url.trim()}
          >
            {inspecting ? (
              <>
                <Loader2 size={18} strokeWidth={1.5} className="spin-icon" />
                <span>Анализ потока...</span>
              </>
            ) : (
              <>
                <Search size={18} strokeWidth={1.5} />
                <span>Проверить источник</span>
              </>
            )}
          </button>
        </div>
      </form>

      {inspecting && (
        <div
          className="inspect-loading-strip"
          role="status"
          aria-live="polite"
        >
          <div className="progress-track" aria-hidden="true">
            <div className="progress-indeterminate" />
          </div>
          <span className="card-subtitle">
            Проверка URL на SSRF, чтение метаданных и списка реальных разрешений источника...
          </span>
        </div>
      )}

      {error && (
        <div
          className="alert-box alert-error"
          role="alert"
          aria-live="polite"
          style={{ marginTop: '16px' }}
        >
          <span className="icon-box" style={{ color: 'var(--danger)' }}>
            <AlertCircle size={18} strokeWidth={1.5} />
          </span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 500, marginBottom: '2px' }}>
              {getErrorHeading(error.code)}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>
              {error.message}
            </div>
            <div className="alert-code">Код: {error.code}</div>
          </div>
          {onClearError && (
            <button
              type="button"
              className="btn btn-ghost"
              onClick={onClearError}
              aria-label="Скрыть сообщение об ошибке"
              style={{ height: '28px', padding: '0 6px' }}
            >
              <X size={16} strokeWidth={1.5} />
            </button>
          )}
        </div>
      )}

      <div className="source-strip">
        <div className="source-tags">
          <span className="source-tag">YouTube</span>
          <span className="source-tag">TikTok</span>
          <span className="source-tag">Instagram</span>
          <span className="source-tag">Pinterest</span>
          <span className="source-tag">Прямые файлы (MP4 / MP3 / JPG / PNG)</span>
        </div>

        <div className="sample-links">
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Примеры для проверки:
          </span>
          {PUBLIC_SAMPLES.map((sample) => (
            <button
              key={sample.url}
              type="button"
              className="sample-btn"
              disabled={inspecting}
              onClick={() => {
                onChangeUrl(sample.url);
                onInspect(sample.url);
              }}
            >
              {sample.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
