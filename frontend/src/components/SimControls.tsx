import React, { useState } from 'react';
import { Play, RotateCcw, ChevronDown, Flame, TrendingUp, Waves, ZapOff } from 'lucide-react';

interface SimControlsProps {
  onSimulate: (scenario: 'spike' | 'ramp' | 'flood' | 'outage' | 'recover', durationSec?: number, errorRatio?: number) => void;
  isSimEnabled: boolean;
}

export const SimControls: React.FC<SimControlsProps> = ({ onSimulate, isSimEnabled }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);

  if (!isSimEnabled) return null;

  const handleTrigger = (scenario: 'spike' | 'ramp' | 'flood' | 'outage', duration = 60, ratio = 0.35) => {
    setActiveScenario(scenario);
    onSimulate(scenario, duration, ratio);
    setIsOpen(false);
  };

  const handleRecover = () => {
    setActiveScenario(null);
    onSimulate('recover');
    setIsOpen(false);
  };

  return (
    <div className="relative inline-block text-left">
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-500 hover:to-blue-500 text-white text-xs font-semibold shadow-md shadow-sky-600/20 transition-all border border-sky-400/20 active:scale-95"
          id="simulate-dropdown-btn"
        >
          <Play className="w-3.5 h-3.5 fill-current" />
          <span>Simulate</span>
          <ChevronDown className="w-3 h-3 text-sky-200" />
        </button>

        {activeScenario && (
          <button
            onClick={handleRecover}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600/20 border border-emerald-500/40 hover:bg-emerald-600/30 text-emerald-300 text-xs font-semibold transition-all active:scale-95"
            title="End simulation and restore normal traffic"
            id="simulate-recover-btn"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Recover</span>
          </button>
        )}
      </div>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-2 w-64 rounded-xl glass-panel-glow bg-slate-900/95 border border-slate-700/80 shadow-2xl z-50 p-2 text-xs divide-y divide-slate-800">
            <div className="px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Live Anomaly Injection
            </div>
            <div className="py-1 space-y-0.5">
              <button
                onClick={() => handleTrigger('spike', 60, 0.35)}
                className="w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-slate-800/80 text-left transition-colors group"
                id="sim-spike-btn"
              >
                <div className="p-1 rounded bg-rose-500/20 text-rose-400 group-hover:scale-110 transition-transform">
                  <Flame className="w-3.5 h-3.5" />
                </div>
                <div>
                  <div className="font-semibold text-slate-200">Error Spike (35%)</div>
                  <div className="text-[11px] text-slate-400">Instant jump to 35% error rate for 60s</div>
                </div>
              </button>

              <button
                onClick={() => handleTrigger('ramp', 90, 0.50)}
                className="w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-slate-800/80 text-left transition-colors group"
                id="sim-ramp-btn"
              >
                <div className="p-1 rounded bg-amber-500/20 text-amber-400 group-hover:scale-110 transition-transform">
                  <TrendingUp className="w-3.5 h-3.5" />
                </div>
                <div>
                  <div className="font-semibold text-slate-200">Gradual Ramp</div>
                  <div className="text-[11px] text-slate-400">Linear increase up to 50% over 90s</div>
                </div>
              </button>

              <button
                onClick={() => handleTrigger('flood', 60, 0.05)}
                className="w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-slate-800/80 text-left transition-colors group"
                id="sim-flood-btn"
              >
                <div className="p-1 rounded bg-sky-500/20 text-sky-400 group-hover:scale-110 transition-transform">
                  <Waves className="w-3.5 h-3.5" />
                </div>
                <div>
                  <div className="font-semibold text-slate-200">Traffic Flood</div>
                  <div className="text-[11px] text-slate-400">10x volume increase with normal error ratio</div>
                </div>
              </button>

              <button
                onClick={() => handleTrigger('outage', 45, 0.95)}
                className="w-full flex items-start gap-2.5 px-2.5 py-2 rounded-lg hover:bg-slate-800/80 text-left transition-colors group"
                id="sim-outage-btn"
              >
                <div className="p-1 rounded bg-red-600/20 text-red-400 group-hover:scale-110 transition-transform">
                  <ZapOff className="w-3.5 h-3.5" />
                </div>
                <div>
                  <div className="font-semibold text-slate-200">Severe Outage (95%)</div>
                  <div className="text-[11px] text-slate-400">Catastrophic service crash</div>
                </div>
              </button>
            </div>

            <div className="pt-1.5 pb-0.5">
              <button
                onClick={handleRecover}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 font-semibold transition-colors"
                id="sim-quick-recover-btn"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Restore Normal Traffic</span>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};
