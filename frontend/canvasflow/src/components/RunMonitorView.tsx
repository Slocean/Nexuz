import React, { useEffect, useMemo, useRef } from 'react';
import { Activity, Pause, Play, Square, Terminal } from 'lucide-react';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';
import { ResourceMonitorPanel } from './ResourceMonitorHud';
import { useFlowStore } from '@/store/flowModelStore';

type Props = {
  flowName?: string;
  nodeLabel?: string;
  onPause?: () => void;
  onResume?: () => void;
  onStop?: () => void;
  execStatus?: string;
  themeName?: ThemeName;
  themeMode?: ThemeMode;
  hotkeyLabels?: {
    start_run?: string;
    stop_run?: string;
    pause_run?: string;
  };
};

function truncate(s: string, n: number) {
  const t = String(s || '');
  if (t.length <= n) return t;
  return `${t.slice(0, Math.max(1, n - 1))}…`;
}

function levelColor(level?: string): string {
  const l = String(level || '').toLowerCase();
  if (l === 'error' || l === 'fatal') return '#fb7185';
  if (l === 'warn' || l === 'warning') return '#fbbf24';
  if (l === 'success' || l === 'ok') return '#34d399';
  return '#94a3b8';
}

function formatTs(ts?: number): string {
  try {
    return new Date(ts || Date.now()).toLocaleTimeString('zh-CN', { hour12: false });
  } catch {
    return '';
  }
}

/** Compact run UI — pause/stop/resume are the same App handlers as the main toolbar. */
export default function RunMonitorView({
  flowName = '',
  nodeLabel = '—',
  onPause,
  onResume,
  onStop,
  execStatus = 'running',
  themeName = 'Ocean',
  themeMode = 'dark',
  hotkeyLabels,
}: Props) {
  const colors = getThemeColors(themeName, themeMode);
  const paused = execStatus === 'paused' || execStatus === 'breakpoint';
  const statusColor = paused ? '#F59E0B' : '#34D399';
  const name = flowName || '未命名流程';
  const pauseKey = hotkeyLabels?.pause_run || 'X+F5';
  const stopKey = hotkeyLabels?.stop_run || 'X+F4';

  const logs = useFlowStore((s) => s.logs);
  const runLogs = useMemo(() => {
    const rows = (logs || []).filter((l: any) => {
      const cat = String(l?.category || 'runtime');
      return cat === 'runtime' || cat === 'system' || !l?.category;
    });
    return rows.slice(-200);
  }, [logs]);

  const logEndRef = useRef<HTMLDivElement>(null);
  const logBoxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = logBoxRef.current;
    if (!box) return;
    // Stick to bottom when user is already near the end
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 48;
    if (nearBottom || runLogs.length < 8) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [runLogs]);

  return (
    <div
      className="h-full w-full flex flex-col overflow-hidden"
      style={{ background: '#0c0e14', color: '#e8eef8' }}
    >
      <div
        className="shrink-0 pt-2.5 pb-2 flex items-center justify-center gap-3"
        style={{ WebkitAppRegion: 'drag', paddingLeft: 15, paddingRight: 15 } as React.CSSProperties}
      >
        <img
          src={`${import.meta.env.BASE_URL}logo.png`}
          alt=""
          className="h-12 w-12 object-contain shrink-0"
          draggable={false}
        />
        <div className="min-w-0 flex items-center gap-2">
          <img
            src={`${import.meta.env.BASE_URL}logo2.png`}
            alt="Nexuz"
            className="h-6 w-auto max-w-[7rem] object-contain object-left shrink-0"
            draggable={false}
          />
          <div className="min-w-0 flex items-center gap-1.5 text-[12.5px] tracking-[0.14em] uppercase text-slate-400">
            <Activity className="w-3 h-3 shrink-0" />
            <span className="truncate">Run Monitor</span>
          </div>
        </div>
      </div>

      <div
        className="shrink-0 pb-1 flex items-start justify-between gap-2"
        style={{ WebkitAppRegion: 'drag', paddingLeft: 15, paddingRight: 15 } as React.CSSProperties}
      >
        <div
          className="min-w-0 text-lg font-bold leading-snug truncate"
          style={{ color: colors.primary }}
          title={name}
        >
          {truncate(name, 22)}
        </div>
        <div
          className="shrink-0 text-sm font-bold tracking-wide leading-snug pt-0.5 whitespace-nowrap"
          style={{ color: statusColor }}
        >
          {paused ? '已暂停 · Paused' : '运行中 · Live'}
        </div>
      </div>

      <div
        className="pb-2 text-[12.5px] text-slate-400 truncate"
        style={{ paddingLeft: 15, paddingRight: 15 }}
        title={nodeLabel}
      >
        节点 {truncate(nodeLabel, 40)}
      </div>

      <div className="shrink-0">
        <ResourceMonitorPanel variant="page" hideBrand />
      </div>

      <div
        className="flex-1 min-h-0 flex flex-col pt-2 pb-1"
        style={{ WebkitAppRegion: 'no-drag', paddingLeft: 15, paddingRight: 15 } as React.CSSProperties}
      >
        <div
          className="flex-1 min-h-0 flex flex-col overflow-hidden rounded-lg border"
          style={{
            background: '#0d1117',
            borderColor: 'rgba(255,255,255,0.1)',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04)',
          }}
        >
          <div
            className="shrink-0 flex items-center gap-2 px-2.5 py-1.5 border-b"
            style={{
              background: '#161b22',
              borderColor: 'rgba(255,255,255,0.08)',
            }}
          >
            <span className="inline-flex gap-1">
              <span className="w-2 h-2 rounded-full bg-[#ff5f56]" />
              <span className="w-2 h-2 rounded-full bg-[#ffbd2e]" />
              <span className="w-2 h-2 rounded-full bg-[#27c93f]" />
            </span>
            <Terminal className="w-3 h-3 text-slate-400" />
            <span className="text-[11px] font-mono text-slate-400 tracking-wide">
              run.log
            </span>
            <span className="ml-auto text-[10px] font-mono text-slate-500">
              {runLogs.length} lines
            </span>
          </div>
          <div
            ref={logBoxRef}
            className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-2.5 py-2 font-mono text-[12px] leading-relaxed select-text"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            {runLogs.length === 0 ? (
              <div className="text-slate-500 py-2"># waiting for runtime logs…</div>
            ) : (
              runLogs.map((log: any, i: number) => {
                const color = levelColor(log.level);
                const ts = formatTs(log.ts);
                return (
                  <div
                    key={`${log.ts || 0}-${i}-${String(log.message || '').slice(0, 20)}`}
                    className="whitespace-pre-wrap break-all py-[1px]"
                    style={{ color, overflowWrap: 'anywhere' }}
                  >
                    <span className="text-slate-500 mr-2">{ts}</span>
                    <span className="text-slate-600 mr-1.5">
                      [{String(log.level || 'info').toUpperCase()}]
                    </span>
                    {log.message}
                  </div>
                );
              })
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>

      <div
        className="shrink-0 py-3 grid grid-cols-2 gap-2"
        style={{ WebkitAppRegion: 'no-drag', paddingLeft: 15, paddingRight: 15 } as React.CSSProperties}
      >
        {paused ? (
          <button
            type="button"
            onClick={() => onResume?.()}
            disabled={execStatus === 'stopping'}
            className="h-10 rounded-xl font-semibold text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
            style={{
              background: 'rgba(52, 211, 153, 0.12)',
              border: '1px solid rgba(52, 211, 153, 0.22)',
              color: '#6ee7b7',
            }}
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            继续
            <span className="text-[12.5px] opacity-80 font-mono font-normal">
              {hotkeyLabels?.start_run || 'X+F3'}
            </span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onPause?.()}
            disabled={execStatus === 'stopping'}
            className="h-10 rounded-xl font-semibold text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
            style={{
              background: 'rgba(251, 191, 36, 0.12)',
              border: '1px solid rgba(251, 191, 36, 0.22)',
              color: '#fcd34d',
            }}
          >
            <Pause className="w-3.5 h-3.5" />
            暂停
            <span className="text-[12.5px] opacity-70 font-mono font-normal">{pauseKey}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => onStop?.()}
          disabled={execStatus === 'stopping'}
          className="h-10 rounded-xl font-semibold text-sm inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
          style={{
            background: 'rgba(251, 113, 133, 0.12)',
            border: '1px solid rgba(251, 113, 133, 0.22)',
            color: '#fda4af',
          }}
        >
          <Square className="w-3 h-3 fill-current" />
          {execStatus === 'stopping' ? '停止中' : '结束'}
          <span className="text-[12.5px] opacity-80 font-mono font-normal">{stopKey}</span>
        </button>
      </div>
    </div>
  );
}
