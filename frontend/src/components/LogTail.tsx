import React, { useState, useMemo } from 'react';
import { LogLine } from '../types';
import { formatTime } from '../lib/format';
import { Terminal, Pause, Play, Trash2, Search, Filter } from 'lucide-react';

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
        return 'text-rose-400 font-bold bg-rose-500/10 px-1 rounded';
      case 'WARNING':
      case 'WARN':
        return 'text-amber-400 font-medium bg-amber-500/10 px-1 rounded';
      default:
        return 'text-sky-400/80';
    }
  };

  return (
    <div className="glass-panel p-5 rounded-xl w-full flex flex-col h-[340px]">
      {/* Log Header Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-sky-400" />
          <h2 className="text-sm font-semibold tracking-wide text-slate-200">
            Live Ingested Log Stream
          </h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
            {filteredLogs.length} events
          </span>
          {isPaused && (
            <span className="text-[11px] font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
              PAUSED
            </span>
          )}
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Search box */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-slate-950/70 border border-slate-800 rounded-lg pl-8 pr-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500/50 w-36 sm:w-48 transition-all"
            />
          </div>

          {/* Service quick chips */}
          {services.length > 0 && (
            <div className="flex items-center gap-1 text-[11px]">
              <Filter className="w-3 h-3 text-slate-500" />
              {services.map((svc) => (
                <button
                  key={svc}
                  onClick={() => setServiceFilter(serviceFilter === svc ? null : svc)}
                  className={`px-2 py-0.5 rounded font-mono transition-colors ${
                    serviceFilter === svc
                      ? 'bg-sky-500/25 text-sky-200 border border-sky-500/40'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                  }`}
                >
                  {svc}
                </button>
              ))}
            </div>
          )}

          {/* Pause / Resume Button */}
          <button
            onClick={handleTogglePause}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold transition-colors border ${
              isPaused
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 hover:bg-amber-500/30'
                : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            {isPaused ? <Play className="w-3 h-3 fill-current" /> : <Pause className="w-3 h-3" />}
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>

          {/* Clear Button */}
          <button
            onClick={() => setClearedBefore(Date.now())}
            className="p-1 rounded bg-slate-800 text-slate-400 hover:text-rose-400 hover:bg-slate-700 transition-colors"
            title="Clear display logs"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Log Terminal Screen */}
      <div className="flex-1 overflow-y-auto bg-slate-950/80 rounded-lg p-3 font-mono text-xs border border-slate-800/80 space-y-1 select-text">
        {filteredLogs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-600 text-xs">
            Waiting for log stream lines…
          </div>
        ) : (
          filteredLogs.map((line, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 hover:bg-white/[0.03] px-1 py-0.5 rounded leading-relaxed transition-colors"
            >
              <span className="text-slate-500 text-[11px] shrink-0">
                {formatTime(line.ts)}
              </span>

              <span className={`text-[11px] shrink-0 font-bold ${getLevelStyle(line.level)}`}>
                {line.level.padEnd(5)}
              </span>

              <span
                onClick={() => setServiceFilter(serviceFilter === line.service ? null : line.service)}
                className="text-slate-400 font-semibold cursor-pointer hover:text-sky-300 transition-colors shrink-0"
              >
                [{line.service || 'unknown'}]
              </span>

              <span className="text-slate-200 break-all flex-1">
                {line.message || line.raw}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
