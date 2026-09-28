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
    <div className="min-h-screen bg-cream text-ink flex flex-col">
      <Header
        connection={connection}
        config={config}
        onSimulate={triggerSimulation}
        activeAlertCount={activeAlerts.length}
        eventAgeSec={eventAgeSec}
        ingestLagMs={latestMetric?.ingest_lag_ms_p95 ?? null}
      />

      <main className="flex-1 w-full max-w-[1440px] mx-auto px-4 sm:px-8 pb-10">
        <KpiCards
          latestMetric={latestMetric}
          baseline={baseline}
          activeAlerts={activeAlerts}
          windowSeconds={config?.window_seconds}
        />

        {/* Chart + logs on the left, incidents on the right. Slightly wider left column on purpose. */}
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-x-10 gap-y-10 mt-10">
          <div className="space-y-10 min-w-0">
            <ErrorRateChart metrics={metrics} alerts={alerts} config={config} />
            <LogTail logs={logs} />
          </div>
          <div className="min-w-0 lg:border-l lg:border-line lg:pl-10">
            <AlertFeed alerts={alerts} onAcknowledge={acknowledgeAlert} />
          </div>
        </div>
      </main>

      <AlertToast alerts={alerts} />

      <footer className="border-t border-line">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-8 py-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>
            <span className="font-serif italic text-ink">Log Watch</span> — log anomaly detection, built for the hackathon
          </span>
          <span className="font-mono">
            window {config?.window_seconds ?? 60}s
            {config?.fast_window_seconds ? ` + ${config.fast_window_seconds}s fast` : ''} · every{' '}
            {config?.eval_interval_sec ?? 5}s · {config?.baseline_method === 'ewma' ? 'EWMA' : 'median/MAD'}
          </span>
        </div>
      </footer>
    </div>
  );
};

export default App;
