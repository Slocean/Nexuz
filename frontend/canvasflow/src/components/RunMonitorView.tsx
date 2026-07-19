import React from 'react';
import { Activity, Pause, Play, Square } from 'lucide-react';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';
import { ResourceMonitorPanel } from './ResourceMonitorHud';

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

  return (
    <div
      className="h-full w-full flex flex-col overflow-hidden"
      style={{ background: '#0c0e14', color: '#e8eef8' }}
    >
      <div
        className="shrink-0 px-3 pt-2.5 pb-2 flex items-center justify-center gap-3"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
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
          <div className="min-w-0 flex items-center gap-1.5 text-[10px] tracking-[0.14em] uppercase text-slate-400">
            <Activity className="w-3 h-3 shrink-0" />
            <span className="truncate">Run Monitor</span>
          </div>
        </div>
      </div>

      <div
        className="shrink-0 px-3 pb-1 flex items-start justify-between gap-2"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
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

      <div className="px-3 pb-2 text-[11px] text-slate-400 truncate" title={nodeLabel}>
        节点 {truncate(nodeLabel, 40)}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <ResourceMonitorPanel variant="page" hideBrand />
      </div>

      <div
        className="shrink-0 p-3 grid grid-cols-2 gap-2"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
      >
        {paused ? (
          <button
            type="button"
            onClick={() => onResume?.()}
            disabled={execStatus === 'stopping'}
            className="h-10 rounded-xl font-semibold text-sm inline-flex flex-col items-center justify-center gap-0 disabled:opacity-40 leading-tight"
            style={{ background: colors.primary, color: '#fff' }}
          >
            <span className="inline-flex items-center gap-1">
              <Play className="w-3.5 h-3.5 fill-current" />
              继续
            </span>
            <span className="text-[9px] opacity-80 font-mono">
              {hotkeyLabels?.start_run || 'X+F3'}
            </span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onPause?.()}
            disabled={execStatus === 'stopping'}
            className="h-10 rounded-xl font-semibold text-sm inline-flex flex-col items-center justify-center gap-0 disabled:opacity-40 leading-tight"
            style={{ background: '#F59E0B', color: '#121623' }}
          >
            <span className="inline-flex items-center gap-1">
              <Pause className="w-3.5 h-3.5" />
              暂停
            </span>
            <span className="text-[9px] opacity-70 font-mono">{pauseKey}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => onStop?.()}
          disabled={execStatus === 'stopping'}
          className="h-10 rounded-xl font-semibold text-sm inline-flex flex-col items-center justify-center gap-0 disabled:opacity-40 leading-tight"
          style={{ background: '#FF453A', color: '#fff' }}
        >
          <span className="inline-flex items-center gap-1">
            <Square className="w-3 h-3 fill-current" />
            {execStatus === 'stopping' ? '停止中' : '结束'}
          </span>
          <span className="text-[9px] opacity-80 font-mono">{stopKey}</span>
        </button>
      </div>
    </div>
  );
}
