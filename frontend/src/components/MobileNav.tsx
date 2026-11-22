import {
  Activity,
  CheckCircle2,
  Compass,
  Moon,
  Settings,
  Smartphone,
  Sun,
} from 'lucide-react';
import type { NavTab, ThemeMode } from '../types';

interface MobileNavProps {
  activeTab: NavTab;
  onSelectTab: (tab: NavTab) => void;
  activeJobsCount: number;
  downloadableCount: number;
  theme: ThemeMode;
  onToggleTheme: () => void;
  onOpenSafariGuide: () => void;
}

export function MobileNav({
  activeTab,
  onSelectTab,
  activeJobsCount,
  downloadableCount,
  theme,
  onToggleTheme,
  onOpenSafariGuide,
}: MobileNavProps) {
  const isStandalone =
    typeof window !== 'undefined' &&
    (window.matchMedia('(display-mode: standalone)').matches ||
      Boolean((navigator as Navigator & { standalone?: boolean }).standalone));

  return (
    <>
      <header className="mobile-header">
        <div className="brand-identity">
          <div className="brand-mark" aria-hidden="true">
            N
            <span className="brand-tally" />
          </div>
          <div>
            <div className="brand-title">NEXUS Media</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {!isStandalone && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onOpenSafariGuide}
              aria-label="Установка PWA на iPhone"
              style={{ padding: '0 10px' }}
            >
              <Smartphone size={16} strokeWidth={1.5} />
              <span>iOS PWA</span>
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onToggleTheme}
            aria-label="Переключить тему"
            style={{ padding: '0 10px' }}
          >
            {theme === 'dark' ? (
              <Sun size={16} strokeWidth={1.5} />
            ) : (
              <Moon size={16} strokeWidth={1.5} />
            )}
          </button>
        </div>
      </header>

      <nav className="mobile-bottom-nav" aria-label="Мобильная навигация">
        <button
          type="button"
          className={`mobile-nav-btn ${activeTab === 'home' ? 'active' : ''}`}
          aria-current={activeTab === 'home' ? 'page' : undefined}
          onClick={() => onSelectTab('home')}
        >
          <Compass size={18} strokeWidth={1.5} />
          <span>Инспектор</span>
        </button>

        <button
          type="button"
          className={`mobile-nav-btn ${activeTab === 'active' ? 'active' : ''}`}
          aria-current={activeTab === 'active' ? 'page' : undefined}
          onClick={() => onSelectTab('active')}
        >
          <Activity size={18} strokeWidth={1.5} />
          <span>Задачи ({activeJobsCount})</span>
        </button>

        <button
          type="button"
          className={`mobile-nav-btn ${activeTab === 'completed' ? 'active' : ''}`}
          aria-current={activeTab === 'completed' ? 'page' : undefined}
          onClick={() => onSelectTab('completed')}
        >
          <CheckCircle2 size={18} strokeWidth={1.5} />
          <span>История ({downloadableCount})</span>
        </button>

        <button
          type="button"
          className={`mobile-nav-btn ${activeTab === 'settings' ? 'active' : ''}`}
          aria-current={activeTab === 'settings' ? 'page' : undefined}
          onClick={() => onSelectTab('settings')}
        >
          <Settings size={18} strokeWidth={1.5} />
          <span>Настройки</span>
        </button>
      </nav>
    </>
  );
}
