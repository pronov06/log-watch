import { useState, useEffect, useRef, useCallback } from 'react';
import {
  MetricPoint,
  Alert,
  LogLine,
  BaselineState,
  AppConfig,
  Envelope,
  SnapshotData,
  PollResponse,
  AlertPatch,
  ConnectionStatus,
} from '../types';

const MAX_METRICS = 720;
const MAX_LOGS = 200;
const MAX_ALERTS = 200;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15000;
const MAX_WS_FAILURES_BEFORE_POLL = 3;
const POLLING_INTERVAL_MS = 2000;

export function useLiveFeed() {
  const [metrics, setMetrics] = useState<MetricPoint[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [activeAlerts, setActiveAlerts] = useState<Alert[]>([]);
  const [baseline, setBaseline] = useState<BaselineState | null>(null);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus>('reconnecting');
  const [latestMetric, setLatestMetric] = useState<MetricPoint | null>(null);

  const lastSeqRef = useRef<number>(0);
  const bootIdRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const wsFailuresRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pollingIntervalRef = useRef<number | null>(null);
  const isMountedRef = useRef<boolean>(true);

  // Helper to dedupe and cap alerts
  const handleAlertUpdate = useCallback((alert: Alert) => {
    setAlerts((prev) => {
      const idx = prev.findIndex((a) => a.id === alert.id);
      let updated: Alert[];
      if (idx >= 0) {
        updated = [...prev];
        updated[idx] = alert;
      } else {
        updated = [alert, ...prev];
      }
      return updated.slice(0, MAX_ALERTS);
    });

    setActiveAlerts((prev) => {
      if (alert.status === 'RESOLVED') {
        return prev.filter((a) => a.id !== alert.id);
      }
      const idx = prev.findIndex((a) => a.id === alert.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = alert;
        return next;
      }
      return [alert, ...prev];
    });
  }, []);

  // Process any incoming envelope
  const processEnvelope = useCallback(
    (envelope: Envelope) => {
      // A snapshot always re-bases the cursor: after a server restart seq starts
      // again from 0, and every later envelope would otherwise look stale.
      if (envelope.type === 'snapshot') {
        lastSeqRef.current = envelope.seq;
      } else if (envelope.seq) {
        if (envelope.seq <= lastSeqRef.current) return; // stale or duplicate
        lastSeqRef.current = envelope.seq;
      }

      switch (envelope.type) {
        case 'snapshot': {
          const snap = envelope.data as SnapshotData;
          if (snap.boot_id) bootIdRef.current = snap.boot_id;
          if (snap.metrics) {
            setMetrics(snap.metrics.slice(-MAX_METRICS));
            if (snap.metrics.length > 0) {
              setLatestMetric(snap.metrics[snap.metrics.length - 1]);
            }
          }
          if (snap.active_alerts) {
            setActiveAlerts(snap.active_alerts);
            setAlerts((prev) => {
              const combined = [...snap.active_alerts];
              prev.forEach((a) => {
                if (!combined.some((c) => c.id === a.id)) combined.push(a);
              });
              return combined.slice(0, MAX_ALERTS);
            });
          }
          if (snap.baseline) {
            setBaseline(snap.baseline);
          }
          if (snap.config) {
            setConfig(snap.config);
          }
          break;
        }

        case 'metric': {
          const pt = envelope.data as MetricPoint;
          setLatestMetric(pt);
          setMetrics((prev) => {
            const next = [...prev, pt];
            if (next.length > MAX_METRICS) return next.slice(-MAX_METRICS);
            return next;
          });
          break;
        }

        case 'alert': {
          const alert = envelope.data as Alert;
          handleAlertUpdate(alert);
          break;
        }

        case 'alert_update': {
          const patch = envelope.data as AlertPatch;
          const apply = (list: Alert[]) =>
            list.map((a) => (a.id === patch.id ? { ...a, ...patch } : a));
          setAlerts(apply);
          setActiveAlerts(apply);
          break;
        }

        case 'baseline': {
          setBaseline(envelope.data as BaselineState);
          break;
        }

        case 'log': {
          const line = envelope.data as LogLine;
          setLogs((prev) => {
            const next = [line, ...prev];
            if (next.length > MAX_LOGS) return next.slice(0, MAX_LOGS);
            return next;
          });
          break;
        }

        case 'heartbeat':
          // Keep-alive acknowledged
          break;
      }
    },
    [handleAlertUpdate]
  );

  // Polling fallback worker
  const pollFallback = useCallback(async () => {
    try {
      const res = await fetch(`/api/poll?since_seq=${lastSeqRef.current}`);
      if (!res.ok) throw new Error('Poll failed');
      const data: PollResponse = await res.json();
      if (!isMountedRef.current) return;
      // Server restarted: its seq counter reset, so our cursor is meaningless.
      // Rewind and let the next poll fetch everything the new process buffered.
      if (bootIdRef.current && data.boot_id !== bootIdRef.current) {
        bootIdRef.current = data.boot_id;
        lastSeqRef.current = 0;
        return;
      }
      bootIdRef.current = data.boot_id;
      for (const env of data.envelopes ?? []) {
        processEnvelope(env);
      }
    } catch {
      // Backend unreachable; the next interval retries.
    }
  }, [processEnvelope]);

  // Connect WebSocket
  const connectWs = useCallback(() => {
    if (!isMountedRef.current) return;
    if (wsRef.current && (wsRef.current.readyState === WebSocket.CONNECTING || wsRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      const socket = new WebSocket(wsUrl);
      wsRef.current = socket;

      socket.onopen = () => {
        if (!isMountedRef.current) {
          socket.close();
          return;
        }
        setConnection('live');
        wsFailuresRef.current = 0;
        if (pollingIntervalRef.current) {
          window.clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
      };

      socket.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          const envelope: Envelope = JSON.parse(event.data);
          processEnvelope(envelope);
        } catch {
          // ignore malformed frame
        }
      };

      socket.onerror = () => {
        // error will trigger close
      };

      socket.onclose = () => {
        if (!isMountedRef.current || wsRef.current !== socket) return;
        wsRef.current = null;
        wsFailuresRef.current += 1;

        if (wsFailuresRef.current >= MAX_WS_FAILURES_BEFORE_POLL) {
          setConnection('polling');
          if (!pollingIntervalRef.current) {
            pollingIntervalRef.current = window.setInterval(pollFallback, POLLING_INTERVAL_MS);
          }
        } else {
          setConnection('reconnecting');
        }

        // Exponential backoff
        const delay = Math.min(
          INITIAL_BACKOFF_MS * Math.pow(2, wsFailuresRef.current - 1),
          MAX_BACKOFF_MS
        );
        if (reconnectTimeoutRef.current) window.clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = window.setTimeout(connectWs, delay);
      };
    } catch {
      wsFailuresRef.current += 1;
      setConnection('reconnecting');
      if (reconnectTimeoutRef.current) window.clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = window.setTimeout(connectWs, INITIAL_BACKOFF_MS);
    }
  }, [pollFallback, processEnvelope]);

  // Initial hydration via REST
  useEffect(() => {
    isMountedRef.current = true;

    async function hydrate() {
      try {
        const [cfgRes, metricsRes, alertsRes] = await Promise.all([
          fetch('/api/config').then((r) => (r.ok ? r.json() : null)),
          fetch('/api/metrics?minutes=30').then((r) => (r.ok ? r.json() : [])),
          fetch('/api/alerts?limit=50').then((r) => (r.ok ? r.json() : [])),
        ]);

        if (!isMountedRef.current) return;
        if (cfgRes) setConfig(cfgRes);
        if (Array.isArray(metricsRes) && metricsRes.length > 0) {
          setMetrics(metricsRes.slice(-MAX_METRICS));
          setLatestMetric(metricsRes[metricsRes.length - 1]);
        }
        if (Array.isArray(alertsRes)) {
          setAlerts(alertsRes);
          setActiveAlerts(alertsRes.filter((a: Alert) => a.status === 'OPEN'));
        }
      } catch (err) {
        console.warn('Initial hydration failed:', err);
      } finally {
        connectWs();
      }
    }

    hydrate();

    return () => {
      isMountedRef.current = false;
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) window.clearTimeout(reconnectTimeoutRef.current);
      if (pollingIntervalRef.current) window.clearInterval(pollingIntervalRef.current);
    };
  }, [connectWs]);

  // Action: Acknowledge alert
  const acknowledgeAlert = useCallback(async (alertId: string, by = 'analyst') => {
    try {
      const res = await fetch(`/api/alerts/${alertId}/ack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ by }),
      });
      if (res.ok) {
        setAlerts((prev) =>
          prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true, acknowledged_by: by } : a))
        );
        setActiveAlerts((prev) =>
          prev.map((a) => (a.id === alertId ? { ...a, acknowledged: true, acknowledged_by: by } : a))
        );
      }
    } catch (err) {
      console.error('Failed to acknowledge alert:', err);
    }
  }, []);

  // Action: Trigger simulated anomaly
  const triggerSimulation = useCallback(
    async (scenario: 'spike' | 'ramp' | 'flood' | 'outage' | 'recover', durationSec = 60, errorRatio = 0.35) => {
      if (scenario === 'recover') {
        await fetch('/api/sim/recover', { method: 'POST' });
      } else {
        await fetch('/api/sim/spike', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            duration_sec: durationSec,
            error_ratio: errorRatio,
            scenario: scenario,
          }),
        });
      }
    },
    []
  );

  return {
    metrics,
    alerts,
    activeAlerts,
    baseline,
    logs,
    config,
    connection,
    latestMetric,
    acknowledgeAlert,
    triggerSimulation,
  };
}
