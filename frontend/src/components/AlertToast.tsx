import React, { useEffect, useState } from 'react';
import { Alert } from '../types';
import { formatPct, formatZ } from '../lib/format';
import { X } from 'lucide-react';

interface AlertToastProps {
  alerts: Alert[];
}

export const AlertToast: React.FC<AlertToastProps> = ({ alerts }) => {
  const [toasts, setToasts] = useState<Alert[]>([]);

  // Show toast when a new OPENED alert arrives with severity >= MEDIUM
  useEffect(() => {
    if (!alerts.length) return;
    const latest = alerts[0];
    if (
      latest.status === 'OPEN' &&
      latest.event === 'OPENED' &&
      ['MEDIUM', 'HIGH', 'CRITICAL'].includes(latest.severity)
    ) {
      setToasts((prev) => {
        if (prev.some((t) => t.id === latest.id)) return prev;
        return [latest, ...prev.slice(0, 2)];
      });
    }
  }, [alerts]);

  const dismissToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Auto-dismiss non-CRITICAL alerts after 6 seconds
  useEffect(() => {
    if (!toasts.length) return;
    const timers = toasts.map((t) => {
      if (t.severity !== 'CRITICAL') {
        return window.setTimeout(() => dismissToast(t.id), 6000);
      }
      return null;
    });

    return () => {
      timers.forEach((t) => t && window.clearTimeout(t));
    };
  }, [toasts]);

  if (!toasts.length) return null;

  return (
    <div className="fixed bottom-4 right-4 left-4 sm:left-auto z-50 flex flex-col gap-2 sm:w-96 pointer-events-none" role="status">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto bg-ink text-cream border-l-[3px] border-sev-critical px-4 py-3 shadow-[0_10px_30px_-12px_rgba(0,0,0,0.5)]"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] uppercase tracking-[0.08em] text-cream/60">
                New {toast.severity.toLowerCase()} incident · {formatZ(toast.z_score)}σ
              </p>
              <p className="text-sm font-medium mt-1">{toast.title}</p>
              <p className="text-xs font-mono text-cream/70 mt-1">
                {formatPct(toast.error_rate)} errors, usually {formatPct(toast.baseline_mean)}
              </p>
            </div>
            <button
              onClick={() => dismissToast(toast.id)}
              className="text-cream/60 hover:text-cream p-0.5 transition-colors"
              aria-label="Dismiss"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
