import {
  HardDrive,
  Lock,
  ShieldCheck,
  Smartphone,
  SunMoon,
  Trash2,
} from 'lucide-react';
import { formatBytes } from '../api';
import type {
  HealthResponse,
  ProviderInfo,
  ThemeMode,
  UserPreferences,
} from '../types';

interface SettingsViewProps {
  preferences: UserPreferences;
  onUpdatePreferences: (patch: Partial<UserPreferences>) => void;
  health: HealthResponse | null;
  providers: ProviderInfo[];
  onCleanupStorage: () => void;
  cleaning: boolean;
  cleanupMessage: string | null;
  onOpenSafariGuide: () => void;
  authRequired: boolean;
  onLogout: () => void;
}

const BITRATES: Array<128 | 192 | 256 | 320> = [128, 192, 256, 320];

export function SettingsView({
  preferences,
  onUpdatePreferences,
  health,
  providers,
  onCleanupStorage,
  cleaning,
  cleanupMessage,
  onOpenSafariGuide,
  authRequired,
  onLogout,
}: SettingsViewProps) {
  return (
    <div className="settings-grid">
      {/* Appearance & Defaults */}
      <section className="surface-card" aria-label="Настройки интерфейса и экспорта">
        <div className="card-section-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="icon-box">
              <SunMoon size={18} strokeWidth={1.5} />
            </span>
            <h3 className="card-title">Интерфейс и параметры по умолчанию</h3>
          </div>
        </div>

        <div className="setting-row">
          <div>
            <div style={{ fontSize: '14px', fontWeight: 500 }}>
              Тема оформления
            </div>
            <div className="card-subtitle">
              Графитовая тёмная или светлая студийная палитра
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            {(['dark', 'light'] as ThemeMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`btn ${
                  preferences.theme === mode ? 'btn-primary' : 'btn-secondary'
                }`}
                onClick={() => onUpdatePreferences({ theme: mode })}
              >
                {mode === 'dark' ? 'Тёмная' : 'Светлая'}
              </button>
            ))}
          </div>
        </div>

        <div className="setting-row">
          <div>
            <div style={{ fontSize: '14px', fontWeight: 500 }}>
              Битрейт аудиоэкспорта MP3
            </div>
            <div className="card-subtitle">
              Значение по умолчанию для конвертации аудио через FFmpeg
            </div>
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            {BITRATES.map((kbps) => (
              <button
                key={kbps}
                type="button"
                className={`keycap-btn ${
                  preferences.defaultAudioBitrate === kbps ? 'selected' : ''
                }`}
                style={
                  preferences.defaultAudioBitrate === kbps
                    ? {
                        borderColor: 'var(--accent)',
                        color: 'var(--text-primary)',
                      }
                    : undefined
                }
                onClick={() =>
                  onUpdatePreferences({ defaultAudioBitrate: kbps })
                }
              >
                {kbps}k
              </button>
            ))}
          </div>
        </div>

        <div className="setting-row">
          <div>
            <div style={{ fontSize: '14px', fontWeight: 500 }}>
              Установка PWA на iPhone и Android
            </div>
            <div className="card-subtitle">
              Автономный режим экрана «Домой» в Safari и Chrome
            </div>
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onOpenSafariGuide}
          >
            <Smartphone size={16} strokeWidth={1.5} />
            <span>Инструкция Safari</span>
          </button>
        </div>
      </section>

      {/* Backend Node, SQLite & Storage Telemetry */}
      <section className="surface-card" aria-label="Состояние узла обработки и хранилища">
        <div className="card-section-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="icon-box">
              <HardDrive size={18} strokeWidth={1.5} />
            </span>
            <h3 className="card-title">Сервер обработки и база истории</h3>
          </div>
          <span className="category-tag">
            {health?.status === 'ok' ? 'Активен' : 'Нет связи'}
          </span>
        </div>

        <div className="spec-ledger" style={{ borderTop: 'none', paddingTop: 0 }}>
          <div className="spec-row">
            <span className="spec-label">Движок FFmpeg / ffprobe</span>
            <span className="spec-value">
              {health?.ffmpeg_available ? 'Доступен' : 'Не обнаружен'}
            </span>
          </div>
          <div className="spec-row">
            <span className="spec-label">Версия экстрактора yt-dlp</span>
            <span className="spec-value">{health?.ytdlp_version || '—'}</span>
          </div>
          <div className="spec-row">
            <span className="spec-label">База истории SQLite</span>
            <span className="spec-value">
              {health?.database
                ? `Схема v${health.database.schema_version} · записей: ${health.database.persisted_jobs}`
                : '—'}
            </span>
          </div>
          <div className="spec-row">
            <span className="spec-label">Подключения SSE (Live)</span>
            <span className="spec-value">
              {health?.database ? `${health.database.active_sse_clients}` : '—'}
            </span>
          </div>
          <div className="spec-row">
            <span className="spec-label">Лимит файла и длительности</span>
            <span className="spec-value">
              {health
                ? `${health.limits.max_file_size_mb} МБ · ${health.limits.max_duration_minutes} мин`
                : '—'}
            </span>
          </div>
          <div className="spec-row">
            <span className="spec-label">Занято временными файлами</span>
            <span className="spec-value">
              {health ? formatBytes(health.storage.used_bytes) : '—'}
            </span>
          </div>
          <div className="spec-row">
            <span className="spec-label">Защита кодом доступа</span>
            <span className="spec-value">
              {authRequired ? 'Включена (Cookie)' : 'Только локально'}
            </span>
          </div>
        </div>

        <div
          style={{
            marginTop: '20px',
            paddingTop: '16px',
            borderTop: '1px solid var(--border-hairline)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            flexWrap: 'wrap',
          }}
        >
          <span className="card-subtitle">
            {cleanupMessage ||
              `Автоочистка временных файлов через ${
                health?.limits.job_ttl_minutes || 60
              } мин (история SQLite сохраняется)`}
          </span>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {authRequired && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onLogout}
              >
                <Lock size={16} strokeWidth={1.5} />
                <span>Заблокировать</span>
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={cleaning}
              onClick={onCleanupStorage}
            >
              <Trash2 size={16} strokeWidth={1.5} />
              <span>
                {cleaning ? 'Очистка...' : 'Очистить временные файлы'}
              </span>
            </button>
          </div>
        </div>
      </section>

      {/* Supported Providers & Security Policy */}
      <section
        className="surface-card"
        style={{ gridColumn: '1 / -1' }}
        aria-label="Архитектура провайдеров и политика безопасности"
      >
        <div className="card-section-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="icon-box">
              <ShieldCheck size={18} strokeWidth={1.5} />
            </span>
            <div>
              <h3 className="card-title">
                Поддерживаемые источники и правила ответственной обработки
              </h3>
              <p className="card-subtitle">
                NEXUS Media работает только с открытыми публичными ссылками и
                разрешёнными прямыми медиафайлами. Обход DRM, закрытых
                аккаунтов и авторизации отключён на уровне архитектуры
              </p>
            </div>
          </div>
        </div>

        <div className="provider-list">
          {providers.map((prov) => (
            <div key={prov.id} className="provider-item">
              <div className="provider-item-top">
                <span className="provider-name">{prov.name}</span>
                <span className="category-tag">
                  {prov.status === 'active'
                    ? 'Публичный доступ'
                    : 'Ограниченный публичный режим'}
                </span>
              </div>
              <p className="provider-notes">{prov.notes}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
