import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

interface SimControlsProps {
  onSimulate: (scenario: 'spike' | 'ramp' | 'flood' | 'outage' | 'recover', durationSec?: number, errorRatio?: number) => void;
  isSimEnabled: boolean;
}

const SCENARIOS = [
  { id: 'spike', duration: 60, ratio: 0.35, title: 'Error spike', detail: 'Jumps to 35% errors for a minute', btn: 'sim-spike-btn' },
  { id: 'ramp', duration: 90, ratio: 0.5, title: 'Slow ramp', detail: 'Creeps up to 50% over 90 s', btn: 'sim-ramp-btn' },
  { id: 'flood', duration: 60, ratio: 0.05, title: 'Traffic flood', detail: '10× volume, slightly more errors', btn: 'sim-flood-btn' },
  { id: 'outage', duration: 45, ratio: 0.95, title: 'Outage', detail: '95% errors, then the service goes quiet', btn: 'sim-outage-btn' },
] as const;

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
      <div className="flex items-center gap-2">
        {activeScenario && (
          <button
            onClick={handleRecover}
            className="btn-quiet"
            title="End simulation and restore normal traffic"
            id="simulate-recover-btn"
          >
            Stop {activeScenario}
          </button>
        )}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="btn-primary"
          id="simulate-dropdown-btn"
          aria-expanded={isOpen}
        >
          <span>Inject incident</span>
          <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>
      </div>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 mt-2 w-72 bg-paper border border-line shadow-[0_8px_24px_-12px_rgba(31,31,31,0.25)] z-50 text-[13px]">
            <p className="px-4 pt-3 pb-2 text-xs text-muted border-b border-line">
              Writes simulated traffic to the tailed log. Detection sees it like any real log.
            </p>
            <ul>
              {SCENARIOS.map((s) => (
                <li key={s.id}>
                  <button
                    onClick={() => handleTrigger(s.id, s.duration, s.ratio)}
                    className="w-full text-left px-4 py-2.5 hover:bg-cream transition-colors flex items-baseline justify-between gap-3"
                    id={s.btn}
                  >
                    <span className="font-medium">{s.title}</span>
                    <span className="text-xs text-muted text-right">{s.detail}</span>
                  </button>
                </li>
              ))}
            </ul>
            <button
              onClick={handleRecover}
              className="w-full text-left px-4 py-2.5 border-t border-line text-forest font-medium hover:bg-forest-soft transition-colors"
              id="sim-quick-recover-btn"
            >
              Back to normal traffic
            </button>
          </div>
        </>
      )}
    </div>
  );
};
