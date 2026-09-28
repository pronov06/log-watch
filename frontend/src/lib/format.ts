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
      return 'text-rose-400';
    case 'HIGH':
      return 'text-red-400';
    case 'MEDIUM':
      return 'text-amber-400';
    case 'LOW':
      return 'text-yellow-300';
    default:
      return 'text-emerald-400';
  }
}

export function getSeverityBg(sev: Severity): string {
  switch (sev) {
    case 'CRITICAL':
      return 'bg-rose-500/10 text-rose-300 border-rose-500/30';
    case 'HIGH':
      return 'bg-red-500/10 text-red-300 border-red-500/30';
    case 'MEDIUM':
      return 'bg-amber-500/10 text-amber-300 border-amber-500/30';
    case 'LOW':
      return 'bg-yellow-500/10 text-yellow-300 border-yellow-500/30';
    default:
      return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30';
  }
}
