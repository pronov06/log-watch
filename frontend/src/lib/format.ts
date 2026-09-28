import { Severity } from '../types';

export function formatPct(val: number | null | undefined, decimals = 1): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return `${(val * 100).toFixed(decimals)}%`;
}

export function formatZ(val: number | null | undefined): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return val.toFixed(1);
}

export function formatTime(isoString: string): string {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch {
    return isoString;
  }
}

export function formatRelativeTime(isoString: string): string {
  if (!isoString) return '';
  try {
    const diff = Math.max(0, Math.floor((Date.now() - new Date(isoString).getTime()) / 1000));
    if (diff < 5) return 'just now';
    if (diff < 60) return `${diff}s ago`;
    const mins = Math.floor(diff / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    return `${hours}h ago`;
  } catch {
    return isoString;
  }
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const remSec = s % 60;
  return `${m}m ${remSec}s`;
}

export function getSeverityColor(sev: Severity): string {
  switch (sev) {
    case 'CRITICAL':
      return 'text-sev-critical';
    case 'HIGH':
      return 'text-sev-high';
    case 'MEDIUM':
      return 'text-sev-medium';
    case 'LOW':
      return 'text-sev-low';
    default:
      return 'text-sev-ok';
  }
}

/** Tag style for a severity: a hairline outline in the severity colour, no fills or glows. */
export function getSeverityBg(sev: Severity): string {
  switch (sev) {
    case 'CRITICAL':
      return 'text-sev-critical border-sev-critical';
    case 'HIGH':
      return 'text-sev-high border-sev-high';
    case 'MEDIUM':
      return 'text-sev-medium border-sev-medium';
    case 'LOW':
      return 'text-sev-low border-sev-low';
    default:
      return 'text-sev-ok border-sev-ok';
  }
}

/** Solid severity swatch, used for the thin rule on the left of an alert. */
export function getSeverityRule(sev: Severity): string {
  switch (sev) {
    case 'CRITICAL':
      return 'bg-sev-critical';
    case 'HIGH':
      return 'bg-sev-high';
    case 'MEDIUM':
      return 'bg-sev-medium';
    case 'LOW':
      return 'bg-sev-low';
    default:
      return 'bg-line';
  }
}
