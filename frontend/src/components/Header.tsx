import React from 'react';
import { ConnectionStatus, AppConfig } from '../types';
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

const CONNECTION: Record<ConnectionStatus, { label: string; dot: string; hint: string }> = {
  live: { label: 'Live', dot: 'bg-forest', hint: 'Streaming over WebSocket' },
  polling: { label: 'Polling', dot: 'bg-sev-medium', hint: 'WebSocket unavailable — polling every 2 s' },
  reconnecting: { label: 'Reconnecting…', dot: 'bg-sev-medium animate-pulse', hint: 'Lost the stream, retrying' },
  offline: { label: 'Offline', dot: 'bg-sev-critical', hint: 'Backend unreachable' },
};

export const Header: React.FC<HeaderProps> = ({
  connection,
  config,
  onSimulate,
  activeAlertCount,
  eventAgeSec,
  ingestLagMs,
}) => {
  const stale = eventAgeSec !== null && eventAgeSec > STALE_AFTER_SEC;
  const conn = CONNECTION[connection] ?? CONNECTION.offline;

  return (
    <header className="sticky top-0 z-30 bg-cream/95 backdrop-blur-[2px] border-b border-line">
      <div className="max-w-[1440px] mx-auto px-4 sm:px-8 h-16 flex items-center justify-between gap-4">
        {/* Wordmark */}
        <div className="flex items-baseline gap-3 min-w-0">
          <h1 className="font-serif text-[26px] leading-none tracking-tight">Accentra</h1>
          <span className="hidden md:inline text-[13px] text-muted truncate">
            watching your logs so you don&rsquo;t have to
          </span>
        </div>

        {/* Status line + actions */}
        <div className="flex items-center gap-5 text-[13px]">
          {activeAlertCount > 0 && (
            <span className="hidden sm:inline font-medium text-sev-critical">
              {activeAlertCount} open {activeAlertCount === 1 ? 'incident' : 'incidents'}
            </span>
          )}

          <span
            className={`hidden lg:inline font-mono text-xs ${stale ? 'text-sev-critical' : 'text-muted'}`}
            title="Time since the last server event, and p95 delay from a log line being written to it being analysed"
            data-testid="freshness"
          >
            {eventAgeSec === null ? 'no events yet' : `updated ${eventAgeSec}s ago`}
            {ingestLagMs !== null && ` · lag ${Math.round(ingestLagMs)}ms`}
          </span>

          <span className="hidden md:inline font-mono text-xs text-muted" title="Where alerts are published">
            {config?.publish_mode === 'aws' ? 'CloudWatch + SNS' : 'dry run'}
          </span>

          <span className="flex items-center gap-2" title={conn.hint}>
            <span className={`w-2 h-2 rounded-full ${conn.dot}`} />
            <span className="font-medium">{conn.label}</span>
          </span>

          <SimControls onSimulate={onSimulate} isSimEnabled={config?.sim_enabled ?? true} />
        </div>
      </div>
    </header>
  );
};
