import { useEffect } from 'react';
import { Share, Smartphone, X } from 'lucide-react';

interface SafariInstallSheetProps {
  open: boolean;
  onClose: () => void;
}

export function SafariInstallSheet({ open, onClose }: SafariInstallSheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="sheet-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="safari-guide-title"
      onClick={onClose}
    >
      <div className="sheet-panel" onClick={(e) => e.stopPropagation()}>
        <div className="card-section-header" style={{ marginBottom: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="icon-box">
              <Smartphone size={18} strokeWidth={1.5} />
            </span>
            <h2 id="safari-guide-title" className="card-title">
              Установка NEXUS Media на iPhone (Safari PWA)
            </h2>
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onClose}
            aria-label="Закрыть инструкцию"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        <p className="card-subtitle">
          Приложение поддерживает автономную оболочку (standalone mode),
          системные отступы iOS (safe-area) и сохранение готовых файлов в
          приложение «Файлы» на iPhone и iPad.
        </p>

        <ol className="steps-list">
          <li className="step-item">
            <span className="step-num">1</span>
            <div>
              Откройте адрес NEXUS Media в браузере <strong>Safari</strong> на
              iPhone (по защищённому соединению HTTPS или в локальной сети с
              доверенным сертификатом).
            </div>
          </li>
          <li className="step-item">
            <span className="step-num">2</span>
            <div>
              Нажмите кнопку <strong>Поделиться</strong>{' '}
              <Share
                size={14}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              в нижней панели Safari.
            </div>
          </li>
          <li className="step-item">
            <span className="step-num">3</span>
            <div>
              Выберите пункт <strong>На экран «Домой»</strong> (Add to Home
              Screen) и нажмите <strong>Добавить</strong>.
            </div>
          </li>
          <li className="step-item">
            <span className="step-num">4</span>
            <div>
              Для работы за пределами домашней сети разместите фронтенд и
              FastAPI-сервер за HTTPS-прокси (Caddy, Nginx или Tailscale Serve),
              так как обработка потоков и FFmpeg выполняются на сервере.
            </div>
          </li>
        </ol>

        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            Понятно
          </button>
        </div>
      </div>
    </div>
  );
}
