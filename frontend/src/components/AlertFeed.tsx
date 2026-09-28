import React, { useState } from 'react';
import { Alert, Severity } from '../types';
import {
  formatPct,
  formatZ,
  formatRelativeTime,
  formatDuration,
  getSeverityBg,
  getSeverityRule,
} from '../lib/format';

interface AlertFeedProps {
  alerts: Alert[];
  onAcknowledge: (id: string) => void;
}

const FILTERS = ['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const;

export const AlertFeed: React.FC<AlertFeedProps> = ({ alerts, onAcknowledge }) => {
  const [filterSeverity, setFilterSeverity] = useState<Severity | 'ALL'>('ALL');

  const filteredAlerts = alerts.filter((a) => {
    if (filterSeverity === 'ALL') return true;
    return a.severity === filterSeverity || a.peak_severity === filterSeverity;
  });

  return (
    <section className="flex flex-col">
      <div className="flex items-baseline justify-between gap-3 pb-3 border-b border-ink">
        <h2 className="text-xl">
          Incidents <span className="font-sans text-sm text-muted align-middle ml-1">{filteredAlerts.length}</span>
        </h2>
        <div className="flex items-center text-xs" role="tablist" aria-label="Filter by severity">
          {FILTERS.map((sev) => (
            <button
              key={sev}
              onClick={() => setFilterSeverity(sev)}
              role="tab"
              aria-selected={filterSeverity === sev}
              className={`px-2 py-1 transition-colors border-b-2 -mb-[1px] ${
                filterSeverity === sev ? 'border-forest text-ink font-medium' : 'border-transparent text-muted hover:text-ink'
              }`}
            >
              {sev === 'ALL' ? 'All' : sev.charAt(0) + sev.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="lg:max-h-[860px] overflow-y-auto">
        {filteredAlerts.length === 0 ? (
          <div className="py-12 text-sm text-muted max-w-xs">
            <p className="font-serif italic text-lg text-ink">Nothing to report.</p>
            <p className="mt-1">
              {filterSeverity === 'ALL'
                ? 'When the error rate breaks away from its baseline, the incident shows up here with its likely cause.'
                : `No ${filterSeverity.toLowerCase()} incidents in this session.`}
            </p>
          </div>
        ) : (
          <ol>
            {filteredAlerts.map((alert) => {
              const isOpen = alert.status === 'OPEN';
              const durationSec =
                alert.resolved_at && alert.opened_at
                  ? (new Date(alert.resolved_at).getTime() - new Date(alert.opened_at).getTime()) / 1000
                  : null;

              return (
                <li key={alert.id} className="relative border-b border-line py-5 pl-4">
                  {/* Severity rule: the only colour on a resolved alert */}
                  <span
                    className={`absolute left-0 top-5 bottom-5 w-[3px] ${isOpen ? getSeverityRule(alert.severity) : 'bg-line'}`}
                    aria-hidden
                  />

                  <div className="flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2">
                      <span className={`px-1.5 py-px border font-medium tracking-wide ${getSeverityBg(alert.severity)}`}>
                        {alert.severity}
                      </span>
                      <span className={isOpen ? 'text-sev-critical font-medium' : 'text-muted'}>
                        {isOpen ? 'Open' : `Resolved${durationSec ? ` after ${formatDuration(durationSec)}` : ''}`}
                      </span>
                    </div>
                    <span className="text-muted font-mono" title={alert.opened_at}>
                      {formatRelativeTime(alert.opened_at)}
                      {alert.detection_latency_sec != null && (
                        <span title="First breaching evaluation → alert opened">
                          {' '}· caught in {alert.detection_latency_sec.toFixed(1)}s
                        </span>
                      )}
                    </span>
                  </div>

                  <h3 className={`font-sans text-[15px] font-medium mt-2 ${isOpen ? 'text-ink' : 'text-ink/70'}`}>
                    {alert.title}
                  </h3>

                  <dl className="mt-2 grid grid-cols-4 gap-2 text-xs font-mono">
                    <Figure label="rate" value={formatPct(alert.error_rate)} strong />
                    <Figure label="usual" value={formatPct(alert.baseline_mean)} />
                    <Figure label="deviation" value={`${formatZ(alert.z_score)}σ`} />
                    <Figure label="errors" value={`${alert.window_errors}/${alert.window_total}`} />
                  </dl>

                  {alert.top_errors && alert.top_errors.length > 0 && (
                    <div className="mt-3">
                      <p className="label mb-1">Most frequent errors</p>
                      <ul className="text-xs font-mono">
                        {alert.top_errors.slice(0, 3).map((err, idx) => (
                          <li key={idx} className="flex justify-between gap-3 py-0.5">
                            <span className="truncate" title={err.message}>{err.message}</span>
                            <span className="text-muted shrink-0">×{err.count}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-3 text-muted">
                      {Object.keys(alert.publish_status ?? {}).length === 0 ? (
                        <span>publishing…</span>
                      ) : (
                        Object.entries(alert.publish_status).map(([name, status]) => (
                          <PublishBadge key={name} name={name} status={status} />
                        ))
                      )}
                    </div>

                    {alert.acknowledged ? (
                      <span className="text-muted">Acknowledged by {alert.acknowledged_by || 'analyst'}</span>
                    ) : (
                      <button onClick={() => onAcknowledge(alert.id)} className="btn-quiet !py-1 !text-xs">
                        Acknowledge
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
};

const Figure: React.FC<{ label: string; value: string; strong?: boolean }> = ({ label, value, strong }) => (
  <div>
    <dt className="text-[10px] uppercase tracking-[0.08em] text-muted font-sans">{label}</dt>
    <dd className={strong ? 'text-ink font-medium' : 'text-ink/80'}>{value}</dd>
  </div>
);

const PUBLISHER_LABELS: Record<string, string> = {
  cloudwatch: 'CloudWatch',
  sns: 'SNS',
  console: 'local log',
};

const STATUS_MARK: Record<string, { mark: string; cls: string }> = {
  ok: { mark: '✓', cls: 'text-forest' },
  failed: { mark: '✗', cls: 'text-sev-critical' },
  skipped: { mark: '–', cls: 'text-muted' },
};

const PublishBadge: React.FC<{ name: string; status: string }> = ({ name, status }) => {
  const label = PUBLISHER_LABELS[name] ?? name;
  const { mark, cls } = STATUS_MARK[status] ?? { mark: '?', cls: 'text-sev-medium' };
  return (
    <span title={`${name}: ${status}`}>
      {label} <span className={`${cls} font-medium`}>{mark}</span>
    </span>
  );
};
