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
import { LineChart as ChartIcon } from 'lucide-react';

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
  // Format data points for recharts
  const chartData = useMemo(() => {
    return metrics.map((m) => {
      const timeStr = formatTime(m.ts);
      return {
        ...m,
        timeStr,
        ratePct: Number((m.error_rate * 100).toFixed(2)),
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
      if (d.upperBandPct && d.upperBandPct > max) max = d.upperBandPct;
    });
    return Math.min(100, Math.ceil(max * 1.25));
  }, [chartData]);

  const minAbsRatePct = config?.min_abs_rate ? config.min_abs_rate * 100 : 5.0;

  return (
    <div className="glass-panel p-5 rounded-xl w-full flex flex-col h-[380px]">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ChartIcon className="w-4 h-4 text-sky-400" />
          <h2 className="text-sm font-semibold tracking-wide text-slate-200">
            Real-Time Error Rate vs. EWMA Baseline Band
          </h2>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 bg-rose-400 rounded-full" />
            <span className="text-slate-400">Observed Rate</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-2 bg-sky-400/20 border border-sky-400/40 rounded-sm" />
            <span className="text-slate-400">Baseline Band (3σ)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 bg-amber-400/60 border-t border-dashed border-amber-400" />
            <span className="text-slate-400">Min Abs Gate ({minAbsRatePct}%)</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="flex-1 w-full min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 10, right: 15, left: -20, bottom: 0 }}
          >
            <defs>
              <linearGradient id="bandGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="rateGlow" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
              </linearGradient>
            </defs>

            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />

            <XAxis
              dataKey="timeStr"
              stroke="#64748b"
              fontSize={11}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
              minTickGap={40}
            />

            <YAxis
              stroke="#64748b"
              fontSize={11}
              domain={[0, maxY]}
              tickFormatter={(v) => `${v}%`}
              tickLine={false}
              axisLine={{ stroke: '#334155' }}
            />

            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload || !payload.length) return null;
                const d = payload[0].payload;
                return (
                  <div className="glass-panel p-3 rounded-lg border border-slate-700 shadow-xl text-xs space-y-1">
                    <div className="font-mono text-slate-400 font-semibold mb-1">{d.timeStr}</div>
                    <div className="flex justify-between gap-4">
                      <span className="text-slate-400">Observed Rate:</span>
                      <span className="font-bold text-rose-400">{d.ratePct}%</span>
                    </div>
                    {d.baselineMeanPct !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-slate-400">Baseline Mean:</span>
                        <span className="font-mono text-sky-300">{d.baselineMeanPct}%</span>
                      </div>
                    )}
                    {d.upperBandPct !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-slate-400">Upper Threshold:</span>
                        <span className="font-mono text-indigo-300">{d.upperBandPct}%</span>
                      </div>
                    )}
                    {d.z !== null && (
                      <div className="flex justify-between gap-4">
                        <span className="text-slate-400">Z-Score:</span>
                        <span className="font-mono font-semibold text-amber-300">{d.z.toFixed(2)}σ</span>
                      </div>
                    )}
                    <div className="flex justify-between gap-4 pt-1 border-t border-slate-800 text-[11px]">
                      <span className="text-slate-500">Sample Count:</span>
                      <span className="text-slate-400 font-mono">{d.errors} / {d.total}</span>
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
                fill="#f43f5e"
                fillOpacity={0.12}
                stroke="#f43f5e"
                strokeOpacity={0.4}
                strokeDasharray="2 2"
              />
            ))}

            {/* Min Abs Rate Threshold Line */}
            <ReferenceLine
              y={minAbsRatePct}
              stroke="#f59e0b"
              strokeDasharray="3 3"
              strokeWidth={1}
            />

            {/* Baseline Upper Band Area */}
            <Area
              type="monotone"
              dataKey="upperBandPct"
              stroke="#38bdf8"
              strokeWidth={1.5}
              fill="url(#bandGradient)"
              isAnimationActive={false}
            />

            {/* Error Rate Line */}
            <Line
              type="monotone"
              dataKey="ratePct"
              stroke="#f43f5e"
              strokeWidth={2.5}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
