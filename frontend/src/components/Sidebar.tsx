import {
  Activity,
  CheckCircle2,
  Compass,
  Moon,
  Settings,
  Smartphone,
  Sun,
} from 'lucide-react';
import type {
  HealthResponse,
  NavTab,
  SSEConnectionState,
  ThemeMode,
} from '../types';

interface SidebarProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  activeJobsCount: number;
  downloadableCount: number;
  theme: ThemeMode;
  onToggleTheme: () => void;
  health: HealthResponse | null;
  sseState: SSEConnectionState;
  onOpenSafariGuide: () => void;
}

export function Sidebar({
  activeTab,
  onSelectTab,
  activeJobsCount,
  downloadableCount,
  theme,
  onToggleTheme,
  health,
  sseState,
  onOpenSafariGuide,
}: SidebarProps) {
  const isOnline = health?.status === 'ok';
  const sseLabel =
    sseState === 'live'
      ? 'SSE поток активен'
      : sseState === 'reconnecting'
      ? 'Переподключение SSE...'
      : sseState === 'offline'
      ? 'Устройство офлайн'
      : sseState === 'fallback'
      ? 'Резервный опрос'
      : 'Подключение SSE...';

  return (
    <aside className="sidebar" aria-label="Основная навигация">
      <div>
        <div className="brand-header">
          <div className="brand-identity">
            <div className="brand-mark" aria-hidden="true">
              N
              <span className="brand-tally" />
            </div>
            <div>
              <div className="brand-title">NEXUS Media</div>
              <div className="brand-subtitle">Инспектор и экспорт</div>
            </div>
          </div>
        </div>

        <div className="nav-section-label">Рабочая область</div>
        <ul className="nav-list">
          <li>
            <button
              type="button"
              className={`nav-button ${activeTab === 'home' ? 'active' : ''}`}
              aria-current={activeTab === 'home' ? 'page' : undefined}
              onClick={() => onSelectTab('home')}
            >
              <span className="nav-button-left">
                <span className="icon-box">
                  <Compass size={18} strokeWidth={1.5} />
                </span>
                <span>Инспектор медиа</span>
              </span>
            </button>
          </li>

          <li>
            <button
              type="button"
              className={`nav-button ${activeTab === 'active' ? 'active' : ''}`}
              aria-current={activeTab === 'active' ? 'page' : undefined}
              onClick={() => onSelectTab('active')}
            >
              <span className="nav-button-left">
                <span className="icon-box">
                  <Activity size={18} strokeWidth={1.5} />
                </span>
                <span>Текущие задачи</span>
              </span>
              <span className="nav-count">{activeJobsCount}</span>
            </button>
          </li>

          <li>
            <button
              type="button"
              className={`nav-button ${activeTab === 'completed' ? 'active' : ''}`}
              aria-current={activeTab === 'completed' ? 'page' : undefined}
              onClick={() => onSelectTab('completed')}
            >
              <span className="nav-button-left">
                <span className="icon-box">
                  <CheckCircle2 size={18} strokeWidth={1.5} />
                </span>
                <span>История и файлы</span>
              </span>
              <span className="nav-count">{downloadableCount}</span>
            </button>
          </li>
        </ul>

        <div className="nav-section-label">Система</div>
        <ul className="nav-list">
          <li>
            <button
              type="button"
              className={`nav-button ${activeTab === 'settings' ? 'active' : ''}`}
              aria-current={activeTab === 'settings' ? 'page' : undefined}
              onClick={() => onSelectTab('settings')}
            >
              <span className="nav-button-left">
                <span className="icon-box">
                  <Settings size={18} strokeWidth={1.5} />
                </span>
                <span>Настройки и источники</span>
              </span>
            </button>
          </li>
          <li>
            <button
              type="button"
              className="nav-button"
              onClick={onOpenSafariGuide}
            >
              <span className="nav-button-left">
                <span className="icon-box">
                  <Smartphone size={18} strokeWidth={1.5} />
                </span>
                <span>Установка на iPhone</span>
              </span>
            </button>
          </li>
        </ul>
      </div>

      <div className="sidebar-footer">
        <div className="signal-status-stack">
          <div className="signal-status-row">
            <span className="signal-dot-wrap">
              <span className={`signal-dot ${isOnline ? '' : 'offline'}`} />
              <span>{isOnline ? 'Узел обработки активен' : 'Сервер недоступен'}</span>
            </span>
            <span className="mono">{health ? `v${health.version}` : '—'}</span>
          </div>
          <div className="signal-status-row">
            <span className="signal-dot-wrap" style={{ color: 'var(--text-muted)' }}>
              <span
                className={`signal-dot ${
                  sseState === 'live'
                    ? ''
                    : sseState === 'reconnecting'
                    ? 'warn'
                    : 'offline'
                }`}
              />
              <span>{sseLabel}</span>
            </span>
            <span className="mono">SQLite</span>
          </div>
        </div>

        <button
          type="button"
          className="btn btn-secondary"
          onClick={onToggleTheme}
          style={{ width: '100%', justifyContent: 'space-between' }}
        >
          <span>{theme === 'dark' ? 'Тёмная тема' : 'Светлая тема'}</span>
          <span className="icon-box">
            {theme === 'dark' ? (
              <Sun size={16} strokeWidth={1.5} />
            ) : (
              <Moon size={16} strokeWidth={1.5} />
            )}
          </span>
        </button>
      </div>
    </aside>
  );
}
