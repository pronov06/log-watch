import React from 'react';
import { MetricPoint, BaselineState, Alert } from '../types';
import { formatPct, formatZ, getSeverityColor } from '../lib/format';

interface KpiCardsProps {
  latestMetric: MetricPoint | null;
  baseline: BaselineState | null;
  activeAlerts: Alert[];
  windowSeconds?: number;
}

/** Status callout + a strip of figures. Not cards: one band, divided by rules. */
export const KpiCards: React.FC<KpiCardsProps> = ({
  latestMetric,
  baseline,
  activeAlerts,
  windowSeconds = 60,
}) => {
  const currentRate = latestMetric?.error_rate ?? 0;
  const severity = latestMetric?.severity ?? 'NONE';
  const zScore = latestMetric?.z ?? 0;
  const eps = latestMetric?.events_per_sec ?? 0;
  const isWarmingUp = baseline ? !baseline.ready : true;
  const warmupPct = baseline?.warmup_pct ?? 0;
  const open = activeAlerts.length;

  const headline = isWarmingUp
    ? 'Learning what normal looks like.'
    : open > 0
      ? `${open} ${open === 1 ? 'incident is' : 'incidents are'} open.`
      : 'All quiet.';
  const sub = isWarmingUp
    ? `Collecting ${baseline?.samples ?? 0} of ${baseline?.warmup_needed ?? 24} samples before alerts can fire.`
    : open > 0
      ? `Error rate is ${formatPct(currentRate)} against a usual ${formatPct(baseline?.mean)}.`
      : `Error rate is ${formatPct(currentRate)}, inside the expected range.`;

  return (
    <section className="mt-8 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] border border-line bg-paper">
      {/* Status callout */}
      <div className={`p-6 ${open > 0 ? 'bg-sev-critical' : 'bg-forest'} text-cream`}>
        <p className="text-[11px] uppercase tracking-[0.08em] text-cream/70">Right now</p>
        <h2 className="font-serif text-[28px] leading-tight mt-2 text-cream">{headline}</h2>
        <p className="text-sm text-cream/80 mt-2 max-w-sm">{sub}</p>
        {isWarmingUp && (
          <div className="mt-4 h-[3px] bg-cream/20" aria-label="warm-up progress">
            <div className="h-full bg-cream transition-[width] duration-500" style={{ width: `${Math.min(100, warmupPct)}%` }} />
          </div>
        )}
      </div>

      {/* Figures */}
      <dl className="grid grid-cols-2 md:grid-cols-4 [&>div]:p-5 [&>div]:border-line
                     [&>div:nth-child(n+3)]:border-t [&>div:nth-child(even)]:border-l
                     md:[&>div:nth-child(n+3)]:border-t-0 md:[&>div:not(:first-child)]:border-l">
        <div>
          <dt className="label">Error rate · {windowSeconds}s</dt>
          <dd className={`font-mono text-2xl mt-2 ${getSeverityColor(severity)}`}>{formatPct(currentRate)}</dd>
          <dd className="text-xs text-muted mt-1 font-mono">
            {latestMetric ? `${latestMetric.errors} of ${latestMetric.total}` : '—'}
            {latestMetric?.fast_error_rate != null && (
              <span title="Fast window rate (alerts only when severe)"> · fast {formatPct(latestMetric.fast_error_rate)}</span>
            )}
          </dd>
        </div>

        <div>
          <dt className="label" title="Center ± robust spread the current rate is compared with">
            Baseline
          </dt>
          <dd className="font-mono text-2xl mt-2">
            {isWarmingUp ? '—' : formatPct(baseline?.mean)}
            {!isWarmingUp && <span className="text-sm text-muted"> ±{formatPct(baseline?.std)}</span>}
          </dd>
          <dd className="text-xs text-muted mt-1" data-testid="baseline-source">
            {(baseline?.method ?? 'median/MAD').replace(' + same-hour', '')}
            {baseline?.seasonal_min_days != null &&
              (baseline.source === 'seasonal'
                ? ' · vs same time on past days'
                : ` · same-hour after ${baseline.seasonal_days ?? 0}/${baseline.seasonal_min_days} days`)}
          </dd>
        </div>

        <div>
          <dt className="label">Deviation</dt>
          <dd className={`font-mono text-2xl mt-2 ${zScore >= 3.0 ? getSeverityColor(severity) : ''}`}>
            {isWarmingUp ? '—' : `${formatZ(zScore)}σ`}
          </dd>
          <dd className="text-xs text-muted mt-1">
            alerts from 3.0σ · upper band {isWarmingUp ? '—' : formatPct(baseline?.upper_band)}
          </dd>
        </div>

        <div>
          <dt className="label">Throughput</dt>
          <dd className="font-mono text-2xl mt-2">
            {eps.toFixed(1)}
            <span className="text-sm text-muted"> ev/s</span>
          </dd>
          <dd className="text-xs text-muted mt-1">
            {open > 0 ? (
              <span className="text-sev-critical">{severity !== 'NONE' ? `${severity.toLowerCase()} breach` : 'alert open'}</span>
            ) : (
              `${latestMetric?.total ?? 0} events in window`
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
};
