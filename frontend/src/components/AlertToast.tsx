import React, { useEffect, useState } from 'react';
import { Alert } from '../types';
import { formatPct, formatZ, getSeverityBg } from '../lib/format';
import { ShieldAlert, X } from 'lucide-react';

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
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto p-4 rounded-xl glass-panel-glow border shadow-2xl transition-all duration-300 transform translate-y-0 ${
            toast.severity === 'CRITICAL'
              ? 'border-rose-500/80 bg-slate-900/95 shadow-rose-950/40'
              : 'border-amber-500/80 bg-slate-900/95 shadow-amber-950/40'
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <div
                className={`p-1.5 rounded-lg ${
                  toast.severity === 'CRITICAL' ? 'bg-rose-500/20 text-rose-400' : 'bg-amber-500/20 text-amber-400'
                }`}
              >
                <ShieldAlert className="w-4 h-4 animate-bounce" />
              </div>
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`text-[10px] font-extrabold px-1.5 py-0.5 rounded border uppercase ${getSeverityBg(
                      toast.severity
                    )}`}
                  >
                    {toast.severity} ALERT
                  </span>
                  <span className="text-[11px] font-mono text-slate-400">
                    Z={formatZ(toast.z_score)}σ
                  </span>
                </div>
                <h4 className="text-xs font-semibold text-slate-100">{toast.title}</h4>
                <div className="mt-1 text-[11px] text-slate-400 font-mono">
                  Rate: <span className="text-rose-400 font-bold">{formatPct(toast.error_rate)}</span> |
                  Baseline: {formatPct(toast.baseline_mean)}
                </div>
              </div>
            </div>

            <button
              onClick={() => dismissToast(toast.id)}
              className="text-slate-400 hover:text-white p-1 rounded-md hover:bg-slate-800 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
