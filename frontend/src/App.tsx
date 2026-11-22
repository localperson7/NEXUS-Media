import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, WifiOff } from 'lucide-react';
import {
  ApiError,
  cancelMediaJob,
  cleanupFinishedJobs,
  createMediaJob,
  deleteMediaJob,
  fetchAuthStatus,
  fetchHealth,
  fetchJobs,
  fetchProviders,
  inspectMediaUrl,
  logoutSession,
  mergeJobUpdate,
  retryMediaJob,
} from './api';
import { AccessLockView } from './components/AccessLockView';
import { ActiveJobsView } from './components/ActiveJobsView';
import { CompletedView } from './components/CompletedView';
import { FormatSelector } from './components/FormatSelector';
import { MediaInspector } from './components/MediaInspector';
import { MobileNav } from './components/MobileNav';
import { SafariInstallSheet } from './components/SafariInstallSheet';
import { SettingsView } from './components/SettingsView';
import { Sidebar } from './components/Sidebar';
import { useJobEvents } from './hooks/useJobEvents';
import type {
  ExportFormat,
  HealthResponse,
  JobResponse,
  MediaInspectResponse,
  NavTab,
  ProviderInfo,
  UserPreferences,
} from './types';

const PREFS_STORAGE_KEY = 'nexus_media_preferences_v1';

function loadPreferences(): UserPreferences {
  try {
    const raw = localStorage.getItem(PREFS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        theme: parsed.theme === 'light' ? 'light' : 'dark',
        defaultAudioBitrate: [128, 192, 256, 320].includes(
          parsed.defaultAudioBitrate
        )
          ? parsed.defaultAudioBitrate
          : 192,
        preferredExportCategory:
          parsed.preferredExportCategory === 'audio_export'
            ? 'audio_export'
            : 'video',
      };
    }
  } catch {
    // Default preferences
  }
  return {
    theme: 'dark',
    defaultAudioBitrate: 192,
    preferredExportCategory: 'video',
  };
}

const TAB_TITLES: Record<NavTab, { title: string; meta: string }> = {
  home: {
    title: 'Инспектор медиапотоков',
    meta: 'MP4 · MP3 Аудиоэкспорт · Оригиналы изображений',
  },
  active: {
    title: 'Текущие задачи обработки',
    meta: 'Потоковые обновления SSE · yt-dlp / FFmpeg',
  },
  completed: {
    title: 'История и готовые файлы',
    meta: 'Локальная база SQLite · выдача на устройство',
  },
  settings: {
    title: 'Настройки и источники',
    meta: 'Параметры узла, SQLite и политика SSRF',
  },
};

export function App() {
  const [activeTab, setActiveTab] = useState<NavTab>('home');
  const [preferences, setPreferences] =
    useState<UserPreferences>(loadPreferences);

  const [authChecked, setAuthChecked] = useState<boolean>(false);
  const [authRequired, setAuthRequired] = useState<boolean>(false);
  const [authenticated, setAuthenticated] = useState<boolean>(true);

  const [url, setUrl] = useState<string>('');
  const [inspecting, setInspecting] = useState<boolean>(false);
  const [inspectError, setInspectError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [inspectedMedia, setInspectedMedia] =
    useState<MediaInspectResponse | null>(null);
  const [submittingJob, setSubmittingJob] = useState<boolean>(false);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const [jobs, setJobs] = useState<JobResponse[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [cleaning, setCleaning] = useState<boolean>(false);
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null);
  const [safariGuideOpen, setSafariGuideOpen] = useState<boolean>(false);

  // Sync theme attribute & theme-color meta tag
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', preferences.theme);
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) {
      metaTheme.setAttribute(
        'content',
        preferences.theme === 'dark' ? '#141415' : '#fafafa'
      );
    }
    try {
      localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      // Ignore storage quota issues
    }
  }, [preferences]);

  const updatePreferences = (patch: Partial<UserPreferences>) => {
    setPreferences((prev) => ({ ...prev, ...patch }));
  };

  const toggleTheme = () => {
    updatePreferences({
      theme: preferences.theme === 'dark' ? 'light' : 'dark',
    });
  };

  const checkAuth = useCallback(async () => {
    try {
      const st = await fetchAuthStatus();
      setAuthRequired(st.auth_required);
      setAuthenticated(st.authenticated);
    } catch {
      // If server is temporarily unreachable, stay in app shell and show offline banner
    } finally {
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await fetchHealth();
      setHealth(h);
      if (h.auth_required && h.authenticated === false) {
        setAuthRequired(true);
        setAuthenticated(false);
      }
    } catch {
      setHealth(null);
    }
  }, []);

  const refreshSystemState = useCallback(async () => {
    if (!authenticated) return;
    try {
      const [h, j] = await Promise.all([fetchHealth(), fetchJobs()]);
      setHealth(h);
      setJobs(j);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthRequired(true);
        setAuthenticated(false);
      } else {
        setHealth(null);
      }
    }
  }, [authenticated]);

  // Subscribe to Server-Sent Events with iOS Safari foreground/background suspension recovery
  const { sseState, serverReachable, forceReconnect } = useJobEvents({
    enabled: authChecked && authenticated,
    setJobs,
    onTerminalTransition: refreshHealth,
    onResumeSync: refreshHealth,
  });

  useEffect(() => {
    if (!authChecked || !authenticated) return;
    refreshSystemState();
    fetchProviders()
      .then(setProviders)
      .catch(() => {});
  }, [authChecked, authenticated, refreshSystemState]);

  useEffect(() => {
    if (activeTab !== 'settings' || !authenticated) return;
    refreshHealth();
  }, [activeTab, authenticated, refreshHealth]);

  useEffect(() => {
    if (!actionNotice) return;
    const t = window.setTimeout(() => setActionNotice(null), 4000);
    return () => window.clearTimeout(t);
  }, [actionNotice]);

  const handleApiAuthError = (err: unknown): boolean => {
    if (err instanceof ApiError && err.status === 401) {
      setAuthRequired(true);
      setAuthenticated(false);
      return true;
    }
    return false;
  };

  const handleInspect = async (overrideUrl?: string) => {
    const target = (overrideUrl ?? url).trim();
    if (!target) return;
    setInspecting(true);
    setInspectError(null);
    try {
      const res = await inspectMediaUrl(target);
      setInspectedMedia(res);
    } catch (err) {
      if (handleApiAuthError(err)) return;
      setInspectedMedia(null);
      if (err instanceof ApiError) {
        setInspectError({ code: err.code, message: err.message });
      } else {
        setInspectError({
          code: 'SERVER_OFFLINE',
          message:
            'Сервер NEXUS Media недоступен. Проверьте подключение к домашней сети или Tailscale.',
        });
      }
    } finally {
      setInspecting(false);
    }
  };

  const handleStartExport = async (params: {
    url: string;
    export_format: ExportFormat;
    resolution_id?: string | null;
    audio_bitrate_kbps: number;
  }) => {
    setSubmittingJob(true);
    setInspectError(null);
    try {
      const newJob = await createMediaJob(params);
      setJobs((prev) => mergeJobUpdate(prev, newJob));
      setActiveTab('active');
    } catch (err) {
      if (handleApiAuthError(err)) return;
      if (err instanceof ApiError) {
        setInspectError({ code: err.code, message: err.message });
      } else {
        setInspectError({
          code: 'JOB_CREATE_ERROR',
          message: 'Не удалось создать задачу экспорта медиафайла.',
        });
      }
    } finally {
      setSubmittingJob(false);
    }
  };

  const handleCancelJob = async (jobId: string) => {
    try {
      const updated = await cancelMediaJob(jobId);
      setJobs((prev) => mergeJobUpdate(prev, updated));
    } catch (err) {
      if (!handleApiAuthError(err)) {
        refreshSystemState();
      }
    }
  };

  const handleRetryJob = async (jobId: string) => {
    setRetryingJobId(jobId);
    setActionNotice(null);
    try {
      const retried = await retryMediaJob(jobId);
      setJobs((prev) => mergeJobUpdate(prev, retried));
      setActiveTab('active');
    } catch (err) {
      if (handleApiAuthError(err)) return;
      if (err instanceof ApiError) {
        setActionNotice(`Повторный запуск не удался: ${err.message}`);
      } else {
        setActionNotice('Не удалось перезапустить задачу обработки');
      }
    } finally {
      setRetryingJobId(null);
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    try {
      await deleteMediaJob(jobId);
      setJobs((prev) => prev.filter((j) => j.job_id !== jobId));
      refreshHealth();
    } catch (err) {
      if (!handleApiAuthError(err)) {
        setActionNotice('Не удалось удалить запись из истории');
      }
    }
  };

  const handleCleanupStorage = async () => {
    setCleaning(true);
    setCleanupMessage(null);
    try {
      const res = await cleanupFinishedJobs();
      setCleanupMessage(res.message);
      await refreshSystemState();
    } catch (err) {
      if (!handleApiAuthError(err)) {
        setCleanupMessage('Не удалось выполнить очистку временного каталога');
      }
    } finally {
      setCleaning(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logoutSession();
    } finally {
      setAuthenticated(false);
      setJobs([]);
      setInspectedMedia(null);
    }
  };

  const activeJobsCount = useMemo(
    () =>
      jobs.filter(
        (j) =>
          j.status === 'queued' ||
          j.status === 'downloading' ||
          j.status === 'converting'
      ).length,
    [jobs]
  );

  const downloadableCount = useMemo(
    () =>
      jobs.filter((j) => j.status === 'completed' && j.file_available).length,
    [jobs]
  );

  const historyJobs = useMemo(
    () =>
      jobs.filter(
        (j) =>
          j.status === 'completed' ||
          j.status === 'failed' ||
          j.status === 'cancelled'
      ),
    [jobs]
  );

  if (authChecked && authRequired && !authenticated) {
    return (
      <AccessLockView
        onAuthenticated={() => {
          setAuthenticated(true);
          forceReconnect();
        }}
      />
    );
  }

  const currentHeader = TAB_TITLES[activeTab];
  const showOfflineBanner =
    sseState === 'offline' || (!serverReachable && sseState === 'reconnecting');

  return (
    <div className="app-shell">
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        activeJobsCount={activeJobsCount}
        downloadableCount={downloadableCount}
        theme={preferences.theme}
        onToggleTheme={toggleTheme}
        health={health}
        sseState={sseState}
        onOpenSafariGuide={() => setSafariGuideOpen(true)}
      />

      <div className="app-content-column">
        <MobileNav
          activeTab={activeTab}
          onSelectTab={setActiveTab}
          activeJobsCount={activeJobsCount}
          downloadableCount={downloadableCount}
          theme={preferences.theme}
          onToggleTheme={toggleTheme}
          onOpenSafariGuide={() => setSafariGuideOpen(true)}
        />

        <main className="main-workspace">
          <div className="workspace-topbar">
            <div className="topbar-title-group">
              <h1 className="page-title">{currentHeader.title}</h1>
              <span className="page-context-meta">{currentHeader.meta}</span>
            </div>

            {activeJobsCount > 0 && activeTab !== 'active' && (
              <div className="topbar-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setActiveTab('active')}
                >
                  <span className="signal-dot" />
                  <span>В обработке: {activeJobsCount}</span>
                </button>
              </div>
            )}
          </div>

          {showOfflineBanner && (
            <div
              className="alert-box alert-warning offline-banner"
              role="status"
              aria-live="polite"
            >
              <div className="offline-banner-text">
                <span className="icon-box" style={{ color: 'var(--warning)' }}>
                  <WifiOff size={18} strokeWidth={1.5} />
                </span>
                <div>
                  <div style={{ fontWeight: 500 }}>
                    {sseState === 'offline'
                      ? 'Устройство не подключено к сети'
                      : 'Нет связи с сервером обработки NEXUS Media'}
                  </div>
                  <div className="card-subtitle">
                    Убедитесь, что домашний сервер запущен и Tailscale активен на iPhone
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  forceReconnect();
                  refreshSystemState();
                }}
              >
                <RefreshCw size={15} strokeWidth={1.5} />
                <span>Повторить</span>
              </button>
            </div>
          )}

          {actionNotice && (
            <div
              className="alert-box alert-warning"
              role="status"
              aria-live="polite"
              style={{ marginBottom: '16px' }}
            >
              <span>{actionNotice}</span>
            </div>
          )}

          {activeTab === 'home' && (
            <div className="inspector-stack">
              <MediaInspector
                url={url}
                onChangeUrl={setUrl}
                onInspect={handleInspect}
                onClearError={() => setInspectError(null)}
                inspecting={inspecting}
                error={inspectError}
              />

              {inspectedMedia && (
                <div className={inspecting ? 'workbench-dimmed' : undefined}>
                  <FormatSelector
                    media={inspectedMedia}
                    defaultAudioBitrate={preferences.defaultAudioBitrate}
                    submitting={submittingJob}
                    onStartExport={handleStartExport}
                  />
                </div>
              )}
            </div>
          )}

          {activeTab === 'active' && (
            <ActiveJobsView
              jobs={jobs}
              retryingJobId={retryingJobId}
              onCancelJob={handleCancelJob}
              onRetryJob={handleRetryJob}
              onDeleteJob={handleDeleteJob}
              onGoToInspector={() => setActiveTab('home')}
            />
          )}

          {activeTab === 'completed' && (
            <CompletedView
              historyJobs={historyJobs}
              retryingJobId={retryingJobId}
              onCleanupAll={handleCleanupStorage}
              onRetryJob={handleRetryJob}
              onDeleteJob={handleDeleteJob}
              onDownloadTriggered={(name) =>
                setActionNotice(
                  `Файл «${name}» передан в загрузки браузера / приложение «Файлы»`
                )
              }
              cleaning={cleaning}
              onGoToInspector={() => setActiveTab('home')}
            />
          )}

          {activeTab === 'settings' && (
            <SettingsView
              preferences={preferences}
              onUpdatePreferences={updatePreferences}
              health={health}
              providers={providers}
              onCleanupStorage={handleCleanupStorage}
              cleaning={cleaning}
              cleanupMessage={cleanupMessage}
              onOpenSafariGuide={() => setSafariGuideOpen(true)}
              authRequired={authRequired}
              onLogout={handleLogout}
            />
          )}
        </main>
      </div>

      <SafariInstallSheet
        open={safariGuideOpen}
        onClose={() => setSafariGuideOpen(false)}
      />
    </div>
  );
}
