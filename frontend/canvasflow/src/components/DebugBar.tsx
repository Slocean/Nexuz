import React from 'react';
import { Bug, Play, StepForward, Square, Pause } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ThemeName, ThemeMode } from '../types';
import { getThemeColors } from '../theme';

interface DebugBarProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
  execStatus: string;
  breakpointCount: number;
  onContinue: () => void;
  onStep: () => void;
  onStop: () => void;
  onPause?: () => void;
}

/** Floating debug controls above the canvas (browser-devtools style). */
export default function DebugBar({
  themeName,
  themeMode,
  execStatus,
  breakpointCount,
  onContinue,
  onStep,
  onStop,
  onPause,
}: DebugBarProps) {
  const colors = getThemeColors(themeName, themeMode);
  const isIdle = execStatus === 'idle';
  const isBusy =
    execStatus === 'running' ||
    execStatus === 'paused' ||
    execStatus === 'breakpoint' ||
    execStatus === 'stopping';
  const atBreak = execStatus === 'breakpoint' || execStatus === 'paused';
  const canContinue = atBreak;
  const canStep = isIdle || atBreak || execStatus === 'running';
  const canStop = isBusy && execStatus !== 'stopping';
  const canPause = execStatus === 'running' && !!onPause;

  let statusLabel = '待命';
  if (execStatus === 'running') statusLabel = '运行中';
  else if (execStatus === 'breakpoint') statusLabel = '断点暂停';
  else if (execStatus === 'paused') statusLabel = '已暂停';
  else if (execStatus === 'stopping') statusLabel = '停止中';

  return (
    <div className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-30 flex flex-col items-center gap-1">
      <div
        className="pointer-events-auto flex flex-nowrap items-center gap-1 rounded-2xl border px-1.5 py-1 shadow-lg backdrop-blur-md"
        style={{
          backgroundColor: colors.surface + 'F2',
          borderColor: colors.border,
          color: colors.text,
        }}
      >
        <div
          className="flex flex-nowrap items-center gap-1.5 px-2.5 py-1 rounded-xl text-xs font-medium whitespace-nowrap shrink-0"
          style={{ backgroundColor: 'rgba(245, 158, 11, 0.12)', color: '#d97706' }}
          title="调试模式已开启"
        >
          <Bug className="w-3.5 h-3.5 shrink-0" />
          <span className="shrink-0">调试</span>
          <span className="opacity-50 shrink-0">·</span>
          <span className="opacity-90 shrink-0">{statusLabel}</span>
          {breakpointCount > 0 ? (
            <>
              <span className="opacity-50 shrink-0">·</span>
              <span className="opacity-70 shrink-0">{breakpointCount} 断点</span>
            </>
          ) : null}
        </div>

        <div className="w-px h-5 bg-black/10 dark:bg-white/10 mx-0.5 shrink-0" />

        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 gap-1 shrink-0"
          disabled={!canContinue}
          onClick={onContinue}
          title="继续到下一个断点"
        >
          <Play className="w-3.5 h-3.5 fill-current" />
          <span>继续</span>
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 gap-1 shrink-0"
          disabled={!canStep || execStatus === 'stopping'}
          onClick={onStep}
          title={isIdle ? '从入口单步开始' : '执行下一节点后暂停'}
        >
          <StepForward className="w-3.5 h-3.5" />
          <span>单步</span>
        </Button>

        {canPause ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 gap-1 shrink-0"
            onClick={onPause}
            title="暂停"
          >
            <Pause className="w-3.5 h-3.5" />
            <span>暂停</span>
          </Button>
        ) : null}

        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 gap-1 shrink-0 text-rose-500"
          disabled={!canStop}
          onClick={onStop}
          title="停止调试"
        >
          <Square className="w-3 h-3" />
          <span>停止</span>
        </Button>
      </div>
      {isIdle ? (
        <p className="pointer-events-none text-[11px] opacity-50 text-center px-2 whitespace-nowrap">
          点击节点左侧圆点设置断点，然后点「运行」或「单步」
        </p>
      ) : null}
    </div>
  );
}
