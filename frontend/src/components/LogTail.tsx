import React, { useState, useMemo } from 'react';
import { LogLine } from '../types';
import { formatTime } from '../lib/format';
import { Search } from 'lucide-react';

interface LogTailProps {
  logs: LogLine[];
}

export const LogTail: React.FC<LogTailProps> = ({ logs }) => {
  const [isPaused, setIsPaused] = useState(false);
  const [serviceFilter, setServiceFilter] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [clearedBefore, setClearedBefore] = useState<number>(0);

  // Available services
  const services = useMemo(() => {
    const set = new Set<string>();
    logs.forEach((l) => {
      if (l.service) set.add(l.service);
    });
    return Array.from(set).sort();
  }, [logs]);

  // Frozen logs when paused
  const [frozenLogs, setFrozenLogs] = useState<LogLine[]>([]);

  const handleTogglePause = () => {
    if (!isPaused) {
      setFrozenLogs(logs);
      setIsPaused(true);
    } else {
      setIsPaused(false);
    }
  };

  const displayLogs = isPaused ? frozenLogs : logs;

  const filteredLogs = useMemo(() => {
    return displayLogs.filter((l) => {
      if (new Date(l.ts).getTime() < clearedBefore) return false;
      if (serviceFilter && l.service !== serviceFilter) return false;
      if (searchTerm) {
        const query = searchTerm.toLowerCase();
        const matchMsg = l.message?.toLowerCase().includes(query);
        const matchRaw = l.raw?.toLowerCase().includes(query);
        const matchSvc = l.service?.toLowerCase().includes(query);
        if (!matchMsg && !matchRaw && !matchSvc) return false;
      }
      return true;
    });
  }, [displayLogs, clearedBefore, serviceFilter, searchTerm]);

  const getLevelStyle = (level: string) => {
    switch (level?.toUpperCase()) {
      case 'ERROR':
      case 'FATAL':
      case 'CRITICAL':
        return 'text-[#F2A38F]';
      case 'WARNING':
      case 'WARN':
        return 'text-[#E3C77F]';
      default:
        return 'text-cream/45';
    }
  };

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-3 pb-3 border-b border-ink">
        <h2 className="text-xl">
          Log stream{' '}
          <span className="font-sans text-sm text-muted align-middle ml-1">
            {filteredLogs.length} lines{isPaused && ' · paused'}
          </span>
        </h2>

        <div className="flex items-center gap-2">
          <label className="relative">
            <Search className="w-3.5 h-3.5 text-muted absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Filter lines"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-paper border border-line rounded pl-7 pr-2 py-1 text-[13px] placeholder:text-muted focus:outline-none focus:border-forest w-32 sm:w-44 transition-colors"
            />
          </label>
          <button onClick={handleTogglePause} className={isPaused ? 'btn-primary !py-1' : 'btn-quiet !py-1'}>
            {isPaused ? 'Resume' : 'Pause'}
          </button>
          <button onClick={() => setClearedBefore(Date.now())} className="btn-quiet !py-1" title="Clear display logs">
            Clear
          </button>
        </div>
      </div>

      {services.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-xs">
          <span className="text-muted">Service</span>
          {services.map((svc) => (
            <button
              key={svc}
              onClick={() => setServiceFilter(serviceFilter === svc ? null : svc)}
              className={`font-mono transition-colors ${
                serviceFilter === svc ? 'text-forest underline underline-offset-4 decoration-2' : 'text-muted hover:text-ink'
              }`}
            >
              {svc}
            </button>
          ))}
        </div>
      )}

      {/* Terminal: the one dark surface, in forest rather than black */}
      <div className="h-[300px] overflow-y-auto bg-forest-dark text-cream/90 font-mono text-[12px] leading-relaxed px-4 py-3 select-text">
        {filteredLogs.length === 0 ? (
          <p className="text-cream/50">
            {logs.length === 0 ? 'Waiting for the first log lines…' : 'No lines match this filter.'}
          </p>
        ) : (
          filteredLogs.map((line, idx) => (
            <div key={idx} className="flex gap-3 hover:bg-cream/[0.04] -mx-2 px-2">
              <span className="text-cream/40 shrink-0">{formatTime(line.ts)}</span>
              <span className={`shrink-0 w-12 ${getLevelStyle(line.level)}`}>{line.level.slice(0, 5)}</span>
              <button
                onClick={() => setServiceFilter(serviceFilter === line.service ? null : line.service)}
                className="text-cream/60 hover:text-cream shrink-0 hidden sm:inline"
              >
                {line.service || 'unknown'}
              </button>
              <span className="break-all flex-1">{line.message || line.raw}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
};
