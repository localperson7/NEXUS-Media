import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchJobs, mergeJobUpdate } from '../api';
import type { JobResponse, SSEConnectionState } from '../types';

interface UseJobEventsOptions {
  enabled: boolean;
  setJobs: React.Dispatch<React.SetStateAction<JobResponse[]>>;
  onTerminalTransition?: () => void;
  onResumeSync?: () => void;
}

interface UseJobEventsResult {
  sseState: SSEConnectionState;
  serverReachable: boolean;
  forceReconnect: () => void;
}

export function useJobEvents({
  enabled,
  setJobs,
  onTerminalTransition,
  onResumeSync,
}: UseJobEventsOptions): UseJobEventsResult {
  const [sseState, setSseState] = useState<SSEConnectionState>(
    typeof navigator !== 'undefined' && !navigator.onLine
      ? 'offline'
      : 'connecting'
  );
  const [serverReachable, setServerReachable] = useState<boolean>(true);
  const [reconnectTick, setReconnectTick] = useState<number>(0);

  const lastEventIdRef = useRef<number>(0);
  const terminalCallbackRef = useRef(onTerminalTransition);
  const resumeCallbackRef = useRef(onResumeSync);
  terminalCallbackRef.current = onTerminalTransition;
  resumeCallbackRef.current = onResumeSync;

  const forceReconnect = useCallback(() => {
    setReconnectTick((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    if (typeof EventSource === 'undefined') {
      setSseState('fallback');
      return;
    }

    let closed = false;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let retryDelayMs = 1500;

    const cleanupSource = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (source) {
        source.close();
        source = null;
      }
    };

    const syncImmediately = () => {
      fetchJobs()
        .then((list) => {
          if (closed) return;
          setJobs(list);
          setServerReachable(true);
        })
        .catch(() => {
          if (closed) return;
          setServerReachable(false);
        });
      resumeCallbackRef.current?.();
    };

    const connect = () => {
      if (closed) return;
      if (typeof navigator !== 'undefined' && !navigator.onLine) {
        setSseState('offline');
        setServerReachable(false);
        return;
      }

      cleanupSource();
      const query =
        lastEventIdRef.current > 0
          ? `?last_event_id=${lastEventIdRef.current}`
          : '';
      const es = new EventSource(`/api/jobs/events${query}`);
      source = es;

      es.onopen = () => {
        if (closed) return;
        retryDelayMs = 1500;
        setSseState('live');
        setServerReachable(true);
      };

      es.addEventListener('snapshot', (rawEvt) => {
        if (closed) return;
        const msgEvt = rawEvt as MessageEvent<string>;
        const numericId = Number(msgEvt.lastEventId);
        if (!Number.isNaN(numericId) && numericId > lastEventIdRef.current) {
          lastEventIdRef.current = numericId;
        }
        try {
          const parsed = JSON.parse(msgEvt.data) as {
            jobs?: JobResponse[];
            event_seq?: number;
          };
          if (
            typeof parsed.event_seq === 'number' &&
            parsed.event_seq > lastEventIdRef.current
          ) {
            lastEventIdRef.current = parsed.event_seq;
          }
          if (Array.isArray(parsed.jobs)) {
            setJobs(parsed.jobs);
          }
          setServerReachable(true);
        } catch {
          // Ignore malformed frame
        }
      });

      es.addEventListener('job_update', (rawEvt) => {
        if (closed) return;
        const msgEvt = rawEvt as MessageEvent<string>;
        const numericId = Number(msgEvt.lastEventId);
        if (!Number.isNaN(numericId)) {
          if (numericId <= lastEventIdRef.current) {
            return;
          }
          lastEventIdRef.current = numericId;
        }
        try {
          const updated = JSON.parse(msgEvt.data) as JobResponse;
          setJobs((prev) => mergeJobUpdate(prev, updated));
          setServerReachable(true);
          if (
            updated.status === 'completed' ||
            updated.status === 'failed' ||
            updated.status === 'cancelled'
          ) {
            terminalCallbackRef.current?.();
          }
        } catch {
          // Ignore malformed frame
        }
      });

      es.addEventListener('job_deleted', (rawEvt) => {
        if (closed) return;
        const msgEvt = rawEvt as MessageEvent<string>;
        const numericId = Number(msgEvt.lastEventId);
        if (!Number.isNaN(numericId)) {
          if (numericId <= lastEventIdRef.current) {
            return;
          }
          lastEventIdRef.current = numericId;
        }
        try {
          const parsed = JSON.parse(msgEvt.data) as { job_id?: string };
          if (parsed.job_id) {
            setJobs((prev) => prev.filter((j) => j.job_id !== parsed.job_id));
            terminalCallbackRef.current?.();
          }
        } catch {
          // Ignore malformed frame
        }
      });

      es.onerror = () => {
        if (closed) return;
        cleanupSource();
        if (typeof navigator !== 'undefined' && !navigator.onLine) {
          setSseState('offline');
          setServerReachable(false);
          return;
        }
        setSseState('reconnecting');
        setServerReachable(false);
        reconnectTimer = window.setTimeout(() => {
          retryDelayMs = Math.min(12000, Math.round(retryDelayMs * 1.6));
          connect();
        }, retryDelayMs);
      };
    };

    // Recover cleanly when iOS Safari wakes the PWA from background suspension
    const handleVisibilityChange = () => {
      if (closed) return;
      if (document.visibilityState === 'visible') {
        retryDelayMs = 1500;
        syncImmediately();
        connect();
      }
    };

    // Recover cleanly on iOS Safari bfcache restoration
    const handlePageShow = (evt: PageTransitionEvent) => {
      if (closed) return;
      if (evt.persisted) {
        retryDelayMs = 1500;
        syncImmediately();
        connect();
      }
    };

    const handleOnline = () => {
      if (closed) return;
      retryDelayMs = 1500;
      setSseState('reconnecting');
      syncImmediately();
      connect();
    };

    const handleOffline = () => {
      if (closed) return;
      cleanupSource();
      setSseState('offline');
      setServerReachable(false);
    };

    connect();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('pageshow', handlePageShow);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      closed = true;
      cleanupSource();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('pageshow', handlePageShow);
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [enabled, setJobs, reconnectTick]);

  // Fallback gentle polling ONLY when SSE is reconnecting/fallback (never while live or offline)
  useEffect(() => {
    if (!enabled || sseState === 'live' || sseState === 'offline') return;
    const pollTimer = window.setInterval(() => {
      fetchJobs()
        .then((list) => {
          setJobs(list);
          setServerReachable(true);
        })
        .catch(() => {
          setServerReachable(false);
        });
    }, 4000);
    return () => window.clearInterval(pollTimer);
  }, [enabled, sseState, setJobs]);

  return { sseState, serverReachable, forceReconnect };
}
