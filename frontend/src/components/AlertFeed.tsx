import React, { useState } from 'react';
import { Alert, Severity } from '../types';
import {
  formatPct,
  formatZ,
  formatRelativeTime,
  formatDuration,
  getSeverityBg,
} from '../lib/format';
import {
  ShieldAlert,
  CheckCircle2,
  Clock,
  Cloud,
  Mail,
  Check,
  Filter,
  AlertTriangle,
  Terminal,
} from 'lucide-react';

interface AlertFeedProps {
  alerts: Alert[];
  onAcknowledge: (id: string) => void;
}

export const AlertFeed: React.FC<AlertFeedProps> = ({ alerts, onAcknowledge }) => {
  const [filterSeverity, setFilterSeverity] = useState<Severity | 'ALL'>('ALL');

  const filteredAlerts = alerts.filter((a) => {
    if (filterSeverity === 'ALL') return true;
    return a.severity === filterSeverity || a.peak_severity === filterSeverity;
  });

  return (
    <div className="glass-panel p-5 rounded-xl w-full flex flex-col h-[520px]">
      {/* Feed Header & Filters */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-rose-400" />
          <h2 className="text-sm font-semibold tracking-wide text-slate-200">
            Live Alert Feed
          </h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            {filteredAlerts.length}
          </span>
        </div>

        {/* Severity filter chips */}
        <div className="flex items-center gap-1 text-[11px]">
          <Filter className="w-3 h-3 text-slate-500 mr-1" />
          {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map((sev) => (
            <button
              key={sev}
              onClick={() => setFilterSeverity(sev)}
              className={`px-2 py-0.5 rounded font-medium transition-colors ${
                filterSeverity === sev
                  ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
              }`}
            >
              {sev}
            </button>
          ))}
        </div>
      </div>

      {/* Alerts List */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {filteredAlerts.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs">
            <CheckCircle2 className="w-8 h-8 text-emerald-500/40 mb-2" />
            <p>No alerts in current view</p>
            <p className="text-[11px] text-slate-600">The baseline is calm and within bounds</p>
          </div>
        ) : (
          filteredAlerts.map((alert) => {
            const isOpen = alert.status === 'OPEN';
            const durationSec =
              alert.resolved_at && alert.opened_at
                ? (new Date(alert.resolved_at).getTime() - new Date(alert.opened_at).getTime()) / 1000
                : null;

            return (
              <div
                key={alert.id}
                className={`p-3.5 rounded-xl border transition-all duration-300 ${
                  isOpen
                    ? 'bg-slate-900/90 border-rose-500/30 shadow-lg shadow-rose-950/20'
                    : 'bg-slate-900/50 border-slate-800 text-slate-300'
                }`}
              >
                {/* Header row: Severity + Status + Relative Time */}
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border uppercase tracking-wider ${getSeverityBg(
                        alert.severity
                      )}`}
                    >
                      {alert.severity}
                    </span>

                    <span
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded flex items-center gap-1 ${
                        isOpen
                          ? 'bg-rose-500/20 text-rose-300 animate-pulse'
                          : 'bg-emerald-500/15 text-emerald-300'
                      }`}
                    >
                      {isOpen ? (
                        <>
                          <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                          OPEN
                        </>
                      ) : (
                        <>
                          <Check className="w-3 h-3" />
                          RESOLVED {durationSec ? `(${formatDuration(durationSec)})` : ''}
                        </>
                      )}
                    </span>
                  </div>

                  <span
                    className="text-[11px] text-slate-400 font-mono flex items-center gap-1"
                    title={alert.opened_at}
                  >
                    <Clock className="w-3 h-3" />
                    {formatRelativeTime(alert.opened_at)}
                  </span>
                </div>

                {/* Title */}
                <h3 className="text-xs font-semibold text-slate-100 mb-1.5">
                  {alert.title}
                </h3>

                {/* Metrics Stats row */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400 mb-2 font-mono">
                  <div>
                    Rate:{' '}
                    <span className="text-rose-400 font-semibold">
                      {formatPct(alert.error_rate)}
                    </span>
                  </div>
                  <div>
                    Baseline:{' '}
                    <span className="text-sky-300">
                      {formatPct(alert.baseline_mean)}
                    </span>
                  </div>
                  <div>
                    Z-Score:{' '}
                    <span className="text-amber-300 font-semibold">
                      {formatZ(alert.z_score)}σ
                    </span>
                  </div>
                  <div>
                    Window:{' '}
                    <span className="text-slate-300">
                      {alert.window_errors}/{alert.window_total}
                    </span>
                  </div>
                </div>

                {/* Top Errors Section */}
                {alert.top_errors && alert.top_errors.length > 0 && (
                  <div className="bg-slate-950/60 rounded-lg p-2 mb-2.5 border border-slate-800/80">
                    <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1 flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3 text-amber-400" />
                      Root Causes (Top Errors in Window)
                    </div>
                    <div className="space-y-1">
                      {alert.top_errors.slice(0, 3).map((err, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between text-[11px] font-mono text-slate-300"
                        >
                          <span className="truncate max-w-[280px]" title={err.message}>
                            {err.message}
                          </span>
                          <span className="text-rose-400 font-bold ml-2">×{err.count}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Footer: Publisher Delivery Status & Ack */}
                <div className="flex items-center justify-between pt-1 border-t border-slate-800/60 text-xs">
                  {/* Publishers Status (real per-publisher result from the dispatcher) */}
                  <div className="flex items-center gap-2 text-[11px] text-slate-400">
                    {Object.keys(alert.publish_status ?? {}).length === 0 ? (
                      <span className="text-amber-400/80">publishing…</span>
                    ) : (
                      Object.entries(alert.publish_status).map(([name, status]) => (
                        <PublishBadge key={name} name={name} status={status} />
                      ))
                    )}
                  </div>

                  {/* Acknowledge Button */}
                  <div>
                    {alert.acknowledged ? (
                      <span className="text-[11px] text-slate-400 font-mono">
                        Ack by {alert.acknowledged_by || 'analyst'}
                      </span>
                    ) : (
                      <button
                        onClick={() => onAcknowledge(alert.id)}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] font-medium transition-colors border border-slate-700 active:scale-95"
                      >
                        Acknowledge
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

const PUBLISHER_LABELS: Record<string, { label: string; Icon: typeof Cloud }> = {
  cloudwatch: { label: 'CW', Icon: Cloud },
  sns: { label: 'SNS', Icon: Mail },
  console: { label: 'LOCAL', Icon: Terminal },
};

const STATUS_MARK: Record<string, { mark: string; cls: string }> = {
  ok: { mark: '✓', cls: 'text-emerald-400' },
  failed: { mark: '✗', cls: 'text-rose-400' },
  skipped: { mark: '–', cls: 'text-slate-500' },
};

const PublishBadge: React.FC<{ name: string; status: string }> = ({ name, status }) => {
  const { label, Icon } = PUBLISHER_LABELS[name] ?? { label: name.toUpperCase(), Icon: Cloud };
  const { mark, cls } = STATUS_MARK[status] ?? { mark: '?', cls: 'text-amber-400' };
  return (
    <div className="flex items-center gap-1" title={`${name}: ${status}`}>
      <Icon className="w-3 h-3 text-sky-400" />
      <span>{label}</span>
      <span className={`${cls} font-bold`}>{mark}</span>
    </div>
  );
};
