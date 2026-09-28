import React from 'react';
import { MetricPoint, BaselineState, Alert } from '../types';
import { formatPct, formatZ, getSeverityColor } from '../lib/format';
import { AlertCircle, TrendingUp, Zap, Sparkles, ShieldCheck } from 'lucide-react';

interface KpiCardsProps {
  latestMetric: MetricPoint | null;
  baseline: BaselineState | null;
  activeAlerts: Alert[];
  windowSeconds?: number;
}

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

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5 w-full">
      {/* 1. Current Error Rate */}
      <div className="glass-panel p-4 rounded-xl relative overflow-hidden transition-all hover:border-slate-600/60">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span className="font-medium tracking-wide">Error Rate ({windowSeconds}s)</span>
          <AlertCircle className={`w-4 h-4 ${getSeverityColor(severity)}`} />
        </div>
        <div className="flex items-baseline gap-2">
          <span className={`text-2xl font-extrabold tracking-tight ${getSeverityColor(severity)}`}>
            {formatPct(currentRate)}
          </span>
          {latestMetric?.errors !== undefined && (
            <span className="text-xs text-slate-500 font-mono">
              ({latestMetric.errors}/{latestMetric.total})
            </span>
          )}
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-[11px] text-slate-400">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-slate-500" />
          <span>Status:</span>
          <span className={`font-semibold ${getSeverityColor(severity)}`}>{severity}</span>
          {latestMetric?.fast_error_rate != null && (
            <span className="ml-auto font-mono text-orange-300/90" title="Fast window rate (alerts only when severe)">
              fast {formatPct(latestMetric.fast_error_rate)}
            </span>
          )}
        </div>
      </div>

      {/* 2. Learned Baseline */}
      <div className="glass-panel p-4 rounded-xl relative overflow-hidden transition-all hover:border-slate-600/60">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span className="font-medium tracking-wide" title="Center ± robust spread the current rate is compared with">
            Baseline · {baseline?.method ?? 'median/MAD'}
          </span>
          <Sparkles className="w-4 h-4 text-sky-400" />
        </div>
        {isWarmingUp ? (
          <div>
            <div className="text-lg font-bold text-amber-300 flex items-center gap-1.5">
              <span>Learning…</span>
              <span className="text-xs font-mono text-slate-400">
                ({baseline?.samples ?? 0}/{baseline?.warmup_needed ?? 24})
              </span>
            </div>
            {/* Progress Bar */}
            <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2 overflow-hidden">
              <div
                className="bg-gradient-to-r from-amber-500 to-sky-400 h-1.5 rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, Math.max(5, warmupPct))}%` }}
              />
            </div>
          </div>
        ) : (
          <div>
            <div className="text-2xl font-extrabold tracking-tight text-slate-100">
              {formatPct(baseline?.mean)}
              <span className="text-xs font-normal text-slate-400 ml-1">
                ± {formatPct(baseline?.std)}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-slate-400 flex items-center gap-1">
              <span>Upper band:</span>
              <span className="font-mono text-slate-300 font-semibold">
                {formatPct(baseline?.upper_band)}
              </span>
            </div>
            {baseline?.seasonal_min_days != null && (
              <div className="mt-0.5 text-[11px] text-slate-500" data-testid="baseline-source">
                {baseline.source === 'seasonal'
                  ? 'vs same time on past days'
                  : `rolling · same-hour after ${baseline.seasonal_days ?? 0}/${baseline.seasonal_min_days} days`}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 3. Z-Score Deviation */}
      <div className="glass-panel p-4 rounded-xl relative overflow-hidden transition-all hover:border-slate-600/60">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span className="font-medium tracking-wide">Z-Score Deviation</span>
          <TrendingUp className="w-4 h-4 text-indigo-400" />
        </div>
        <div className="flex items-baseline gap-1.5">
          <span
            className={`text-2xl font-extrabold tracking-tight ${
              zScore >= 3.0 ? getSeverityColor(severity) : 'text-slate-200'
            }`}
          >
            {isWarmingUp ? '—' : `${formatZ(zScore)}σ`}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400 flex items-center gap-1">
          <span>Threshold:</span>
          <span className="font-mono text-slate-300">≥ 3.0σ</span>
        </div>
      </div>

      {/* 4. Active Breaches */}
      <div className="glass-panel p-4 rounded-xl relative overflow-hidden transition-all hover:border-slate-600/60">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span className="font-medium tracking-wide">Active Alerts</span>
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
        </div>
        <div className="flex items-baseline gap-2">
          <span
            className={`text-2xl font-extrabold tracking-tight ${
              activeAlerts.length > 0 ? 'text-rose-400' : 'text-emerald-400'
            }`}
          >
            {activeAlerts.length}
          </span>
          <span className="text-xs text-slate-400">
            {activeAlerts.length === 1 ? 'alert open' : 'alerts open'}
          </span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          {activeAlerts.length > 0 ? (
            <span className="text-rose-300 font-semibold animate-pulse">Breach in progress</span>
          ) : (
            <span className="text-emerald-400 font-medium">All systems normal</span>
          )}
        </div>
      </div>

      {/* 5. Traffic Ingestion Rate */}
      <div className="glass-panel p-4 rounded-xl relative overflow-hidden transition-all hover:border-slate-600/60 col-span-2 md:col-span-1">
        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
          <span className="font-medium tracking-wide">Traffic Throughput</span>
          <Zap className="w-4 h-4 text-amber-400" />
        </div>
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-extrabold tracking-tight text-slate-100 font-mono">
            {eps.toFixed(1)}
          </span>
          <span className="text-xs text-slate-400">events/s</span>
        </div>
        <div className="mt-1 text-[11px] text-slate-400">
          Total window:{' '}
          <span className="font-mono text-slate-300 font-semibold">
            {latestMetric?.total ?? 0}
          </span>
        </div>
      </div>
    </div>
  );
};
