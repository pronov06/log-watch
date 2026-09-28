import React, { useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
  CartesianGrid,
} from 'recharts';
import { MetricPoint, Alert, AppConfig } from '../types';
import { formatTime } from '../lib/format';

interface ErrorRateChartProps {
  metrics: MetricPoint[];
  alerts: Alert[];
  config: AppConfig | null;
}

export const ErrorRateChart: React.FC<ErrorRateChartProps> = ({
  metrics,
  alerts,
  config,
}) => {
  const mainWindow = config?.window_seconds ?? 60;
  const fastWindow = config?.fast_window_seconds ?? 0;

  // Format data points for recharts
  const chartData = useMemo(() => {
    return metrics.map((m) => {
      const timeStr = formatTime(m.ts);
      return {
        ...m,
        timeStr,
        ratePct: Number((m.error_rate * 100).toFixed(2)),
        fastRatePct: m.fast_error_rate != null ? Number((m.fast_error_rate * 100).toFixed(2)) : null,
        upperBandPct: m.upper_band !== null ? Number((m.upper_band * 100).toFixed(2)) : null,
        baselineMeanPct: m.baseline_mean !== null ? Number((m.baseline_mean * 100).toFixed(2)) : null,
      };
    });
  }, [metrics]);

  // Compute alert intervals for shading
  const alertIntervals = useMemo(() => {
    if (!alerts.length || !metrics.length) return [];
    const oldestTs = metrics[0].ts;
    const newestTs = metrics[metrics.length - 1].ts;

    return alerts
      .filter((a) => a.opened_at <= newestTs && (!a.resolved_at || a.resolved_at >= oldestTs))
      .map((a) => {
        const start = formatTime(a.opened_at < oldestTs ? oldestTs : a.opened_at);
        const end = formatTime(!a.resolved_at || a.resolved_at > newestTs ? newestTs : a.resolved_at);
        return {
          id: a.id,
          x1: start,
          x2: end,
          severity: a.peak_severity || a.severity,
        };
      });
  }, [alerts, metrics]);

  // Determine max Y scale (minimum 10%, max auto with headroom)
  const maxY = useMemo(() => {
    let max = 10;
    chartData.forEach((d) => {
      if (d.ratePct > max) max = d.ratePct;
      if (d.fastRatePct && d.fastRatePct > max) max = d.fastRatePct;
      if (d.upperBandPct && d.upperBandPct > max) max = d.upperBandPct;
    });
    return Math.min(100, Math.ceil(max * 1.25));
  }, [chartData]);

  const minAbsRatePct = config?.min_abs_rate ? config.min_abs_rate * 100 : 5.0;

  return (
    <section className="flex flex-col">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 pb-3 border-b border-ink">
        <h2 className="text-xl">Error rate against its baseline</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span className="w-4 h-[2px] bg-sev-critical" /> observed · {mainWindow}s
          </span>
          {fastWindow > 0 && (
            <span className="flex items-center gap-1.5" title={`Fast window alerts only at ${config?.fast_min_severity ?? 'HIGH'} or above`}>
              <span className="w-4 border-t border-dashed border-sev-high" /> fast · {fastWindow}s
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-2.5 bg-forest/15 border-t border-forest" /> normal band
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-4 border-t border-dotted border-muted" /> {minAbsRatePct}% floor
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="h-[300px] sm:h-[340px] w-full mt-4">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 10, right: 15, left: -20, bottom: 0 }}
          >
            <defs>
              <linearGradient id="bandGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2C3E2E" stopOpacity={0.14} />
                <stop offset="95%" stopColor="#2C3E2E" stopOpacity={0.04} />
              </linearGradient>
              <linearGradient id="rateGlow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#9B2C1F" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#9B2C1F" stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="#D3D3C7" vertical={false} />

            <XAxis
              dataKey="timeStr"
              stroke="#6B6B66"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#1F1F1F' }}
              minTickGap={40}
            />

            <YAxis
              stroke="#6B6B66"
              fontSize={11}
              domain={[0, maxY]}
              tickFormatter={(v) => `${v}%`}
              tickLine={false}
              axisLine={{ stroke: '#1F1F1F' }}
            />

            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || !payload.length) return null;
                const d = payload[0].payload;
                return (
                  <div className="bg-paper border border-line px-3 py-2 text-xs space-y-0.5 shadow-[0_6px_18px_-10px_rgba(31,31,31,0.35)]">
                    <div className="font-mono text-muted mb-1">{d.timeStr}</div>
                    <div className="flex justify-between gap-4">
                      <span className="text-muted">Observed</span>
                      <span className="font-mono font-medium text-sev-critical">{d.ratePct}%</span>
                    </div>
                    {d.fastRatePct !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-muted">Fast window</span>
                        <span className="font-mono text-sev-high">{d.fastRatePct}%</span>
                      </div>
                    )}
                    {d.baseline_source && (
                      <div className="flex justify-between gap-4">
                        <span className="text-muted">Reference</span>
                        <span className="font-mono">
                          {d.baseline_source === 'seasonal' ? 'same time, past days' : 'rolling'}
                        </span>
                      </div>
                    )}
                    {d.baselineMeanPct !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-muted">Baseline</span>
                        <span className="font-mono text-forest">{d.baselineMeanPct}%</span>
                      </div>
                    )}
                    {d.upperBandPct !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-muted">Upper band</span>
                        <span className="font-mono">{d.upperBandPct}%</span>
                      </div>
                    )}
                    {d.z !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-muted">Deviation</span>
                        <span className="font-mono">{d.z.toFixed(2)}σ</span>
                      </div>
                    )}
                    <div className="flex justify-between gap-4 pt-1 mt-1 border-t border-line">
                      <span className="text-muted">Errors / events</span>
                      <span className="font-mono">{d.errors} / {d.total}</span>
                    </div>
                  </div>
                );
              }}
            />

            {/* Alert interval highlighting */}
            {alertIntervals.map((interval) => (
              <ReferenceArea
                key={interval.id}
                x1={interval.x1}
                x2={interval.x2}
                fill="#9B2C1F"
                fillOpacity={0.07}
                stroke="#9B2C1F"
                strokeOpacity={0.3}
                strokeDasharray="2 2"
              />
            ))}

            {/* Min Abs Rate Threshold Line */}
            <ReferenceLine
              y={minAbsRatePct}
              stroke="#6B6B66"
              strokeDasharray="1 3"
              strokeWidth={1}
            />

            {/* Baseline Upper Band Area */}
            <Area
              type="monotone"
              dataKey="upperBandPct"
              stroke="#2C3E2E"
              strokeWidth={1}
              fill="url(#bandGradient)"
              isAnimationActive={false}
            />

            {/* Fast-window rate (dual-window detection) */}
            {fastWindow > 0 && (
              <Line
                type="monotone"
                dataKey="fastRatePct"
                stroke="#B4501F"
                strokeOpacity={0.75}
                strokeWidth={1.25}
                strokeDasharray="4 3"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            )}

            {/* Error Rate Line */}
            <Line
              type="monotone"
              dataKey="ratePct"
              stroke="#9B2C1F"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};
