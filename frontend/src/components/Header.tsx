import React from 'react';
import { ConnectionStatus, AppConfig } from '../types';
import { Activity, ShieldAlert, Radio, RefreshCw, AlertTriangle, Cloud, Timer } from 'lucide-react';
import { SimControls } from './SimControls';

interface HeaderProps {
  connection: ConnectionStatus;
  config: AppConfig | null;
  onSimulate: (scenario: 'spike' | 'ramp' | 'flood' | 'outage' | 'recover', durationSec?: number, errorRatio?: number) => void;
  activeAlertCount: number;
  eventAgeSec: number | null;
  ingestLagMs: number | null;
}

// Heartbeats arrive every 15 s, metrics every eval tick; > 20 s of silence means a stalled feed.
const STALE_AFTER_SEC = 20;

export const Header: React.FC<HeaderProps> = ({
  connection,
  config,
  onSimulate,
  activeAlertCount,
  eventAgeSec,
  ingestLagMs,
}) => {
  const stale = eventAgeSec !== null && eventAgeSec > STALE_AFTER_SEC;
  const getStatusBadge = () => {
    switch (connection) {
      case 'live':
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold tracking-wide">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <Radio className="w-3.5 h-3.5" />
            <span>LIVE (WS)</span>
          </div>
        );
      case 'polling':
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-sky-500/10 border border-sky-500/30 text-sky-400 text-xs font-semibold tracking-wide">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>FALLBACK (POLLING)</span>
          </div>
        );
      case 'reconnecting':
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs font-semibold tracking-wide">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>RECONNECTING...</span>
          </div>
        );
      case 'offline':
      default:
        return (
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs font-semibold tracking-wide">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span>OFFLINE</span>
          </div>
        );
    }
  };

  return (
    <header className="sticky top-0 z-30 w-full glass-panel border-b border-white/10 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
      {/* Brand & Title */}
      <div className="flex items-center gap-3.5">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20 ring-1 ring-white/20">
          <Activity className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
              Accentra
              <span className="text-xs font-normal px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 border border-sky-500/25">
                v1.0
              </span>
            </h1>
            {activeAlertCount > 0 && (
              <span className="flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30 animate-pulse">
                <ShieldAlert className="w-3 h-3" />
                {activeAlertCount} {activeAlertCount === 1 ? 'BREACH' : 'BREACHES'}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 hidden sm:block">
            Real-Time Statistical Log Anomaly Detector • EWMA Baseline & Multi-Channel Alerting
          </p>
        </div>
      </div>

      {/* Controls & Statuses */}
      <div className="flex items-center gap-3">
        {/* AWS Mode badge */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700/60 text-slate-300 text-xs font-mono">
          <Cloud className="w-3.5 h-3.5 text-sky-400" />
          <span>{config?.publish_mode === 'aws' ? 'AWS (CW+SNS)' : 'DRY RUN'}</span>
        </div>

        {/* Freshness: last event age + p95 ingest lag (log line written → in the window) */}
        <div
          className={`hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono ${
            stale ? 'bg-rose-500/10 border-rose-500/40 text-rose-300' : 'bg-slate-800/80 border-slate-700/60 text-slate-300'
          }`}
          title="Time since the last server event, and p95 delay from a log line being written to it being analysed"
          data-testid="freshness"
        >
          <Timer className="w-3.5 h-3.5 text-sky-400" />
          <span>{eventAgeSec === null ? 'no events' : `${eventAgeSec}s ago`}</span>
          {ingestLagMs !== null && <span className="text-slate-500">· lag p95 {Math.round(ingestLagMs)}ms</span>}
        </div>

        {/* Connection status pill */}
        {getStatusBadge()}

        {/* Live Simulation Trigger Controls */}
        <SimControls onSimulate={onSimulate} isSimEnabled={config?.sim_enabled ?? true} />
      </div>
    </header>
  );
};
