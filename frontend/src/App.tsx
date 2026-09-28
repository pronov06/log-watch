import React from 'react';
import { useLiveFeed } from './hooks/useLiveFeed';
import { Header } from './components/Header';
import { KpiCards } from './components/KpiCards';
import { ErrorRateChart } from './components/ErrorRateChart';
import { AlertFeed } from './components/AlertFeed';
import { LogTail } from './components/LogTail';
import { AlertToast } from './components/AlertToast';

export const App: React.FC = () => {
  const {
    metrics,
    alerts,
    activeAlerts,
    baseline,
    logs,
    config,
    connection,
    latestMetric,
    eventAgeSec,
    acknowledgeAlert,
    triggerSimulation,
  } = useLiveFeed();

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100 flex flex-col font-sans selection:bg-sky-500/20 selection:text-sky-300">
      {/* Sticky Header */}
      <Header
        connection={connection}
        config={config}
        onSimulate={triggerSimulation}
        activeAlertCount={activeAlerts.length}
        eventAgeSec={eventAgeSec}
        ingestLagMs={latestMetric?.ingest_lag_ms_p95 ?? null}
      />

      {/* Main Dashboard Container */}
      <main className="flex-1 w-full max-w-[1600px] mx-auto p-4 sm:p-6 space-y-5">
        {/* Row 1: KPI Summary Metric Cards */}
        <KpiCards
          latestMetric={latestMetric}
          baseline={baseline}
          activeAlerts={activeAlerts}
          windowSeconds={config?.window_seconds}
        />

        {/* Row 2: Visual Chart & Alert Feed Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
          {/* Main Chart Area (7 columns on desktop) */}
          <div className="lg:col-span-7 space-y-5">
            <ErrorRateChart
              metrics={metrics}
              alerts={alerts}
              config={config}
            />

            {/* Ingested Log Stream */}
            <LogTail logs={logs} />
          </div>

          {/* Alert Feed Area (5 columns on desktop) */}
          <div className="lg:col-span-5">
            <AlertFeed
              alerts={alerts}
              onAcknowledge={acknowledgeAlert}
            />
          </div>
        </div>
      </main>

      {/* Floating Alert Toasts for High/Critical Breaches */}
      <AlertToast alerts={alerts} />

      {/* Footer */}
      <footer className="w-full border-t border-white/5 py-3 px-6 text-center text-[11px] text-slate-500 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span>Accentra Operational Observability Platform</span>
          <span>•</span>
          <span className="font-mono text-slate-400">
            Window: {config?.window_seconds ?? 60}s | Eval: {config?.eval_interval_sec ?? 5}s
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            Detector Engine Active
          </span>
        </div>
      </footer>
    </div>
  );
};

export default App;
