export type Severity = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type AlertEvent = 'OPENED' | 'ESCALATED' | 'RESOLVED';
export type AlertStatus = 'OPEN' | 'RESOLVED';

export interface TopError {
  message: string;
  count: number;
}

export interface PublishStatus {
  [publisher: string]: 'ok' | 'failed' | 'skipped' | string;
}

export interface Alert {
  id: string;
  key: string;
  status: AlertStatus;
  event: AlertEvent;
  severity: Severity;
  peak_severity: Severity;
  title: string;
  error_rate: number;
  baseline_mean: number;
  baseline_std: number;
  z_score: number;
  window_seconds: number;
  window_total: number;
  window_errors: number;
  top_errors: TopError[];
  opened_at: string;
  updated_at: string;
  resolved_at: string | null;
  detection_latency_sec: number | null;
  acknowledged: boolean;
  acknowledged_by: string | null;
  publish_status: PublishStatus;
}

export interface MetricPoint {
  ts: string;
  error_rate: number;
  total: number;
  errors: number;
  events_per_sec: number;
  baseline_mean: number | null;
  baseline_std: number | null;
  upper_band: number | null;
  lower_band: number | null;
  z: number | null;
  severity: Severity;
  ingest_lag_ms_p95: number | null;
  baseline_source: BaselineSource | null;
  fast_error_rate: number | null;
  fast_z: number | null;
  triggered_by: string | null;
}

export type BaselineSource = 'rolling' | 'seasonal';

export interface BaselineState {
  method: string;
  source: BaselineSource;
  seasonal_days?: number;
  seasonal_min_days?: number;
  ready: boolean;
  samples: number;
  warmup_needed: number;
  warmup_pct: number;
  mean: number;
  std: number;
  upper_band: number;
  lower_band: number;
}

export interface LogLine {
  ts: string;
  level: string;
  service: string;
  message: string;
  raw: string;
}

export interface AppConfig {
  window_seconds: number;
  fast_window_seconds: number;
  fast_min_severity: Severity;
  eval_interval_sec: number;
  min_events_in_window: number;
  baseline_method: 'mad' | 'ewma';
  seasonal_enabled: boolean;
  min_abs_rate: number;
  z_low: number;
  z_medium: number;
  z_high: number;
  z_critical: number;
  abs_rate_critical: number;
  confirm_ticks: number;
  resolve_ticks: number;
  baseline_warmup_samples: number;
  publish_mode: 'dry_run' | 'aws' | string;
  sim_enabled: boolean;
}

export interface Envelope<T = unknown> {
  type: 'snapshot' | 'metric' | 'alert' | 'alert_update' | 'baseline' | 'log' | 'heartbeat' | 'pong';
  seq: number;
  ts: string;
  data: T;
}

export type AlertPatch = Pick<Alert, 'id'> & Partial<Alert>;

export interface PollResponse {
  envelopes: Envelope[];
  latest_seq: number;
  boot_id: string;
}

export interface SnapshotData {
  boot_id: string;
  metrics: MetricPoint[];
  active_alerts: Alert[];
  baseline: BaselineState;
  config: AppConfig;
}

export type ConnectionStatus = 'live' | 'reconnecting' | 'polling' | 'offline';
