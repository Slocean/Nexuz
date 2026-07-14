/**
 * In-app tip while a flow is running / paused / at breakpoint.
 */
import React from 'react';
import { Pause, Square, Keyboard } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function RunningBanner({
  open,
  execStatus,
  onPause,
  onStop,
}: {
  open: boolean;
  execStatus: string;
  onPause: () => void;
  onStop: () => void;
}) {
  if (!open) return null;

  let status = '运行中';
  if (execStatus === 'paused') status = '已暂停';
  else if (execStatus === 'breakpoint') status = '断点暂停';
  else if (execStatus === 'stopping') status = '停止中';

  const canPause = execStatus === 'running';
  const canStop = execStatus !== 'idle' && execStatus !== 'stopping';

  return (
    <div
      className="fixed top-16 right-4 z-[90] w-[min(300px,calc(100vw-2rem))] pointer-events-auto"
      role="status"
      aria-live="polite"
    >
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--popover)] text-[var(--popover-foreground)] shadow-2xl backdrop-blur-xl p-3.5 space-y-2.5">
        <div className="flex items-start gap-2.5">
          <div className="mt-0.5 h-8 w-8 rounded-xl bg-emerald-500/15 flex items-center justify-center shrink-0">
            <Keyboard className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-sm">流程{status}</div>
            <p className="text-xs leading-relaxed mt-1 text-[var(--muted-foreground)] space-y-0.5">
              <span className="block">
                暂停{' '}
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[11px]">
                  X+F5
                </kbd>
              </span>
              <span className="block">
                结束{' '}
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[11px]">
                  X+F4
                </kbd>
              </span>
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="flex-1"
            disabled={!canPause}
            onClick={onPause}
          >
            <Pause className="w-3.5 h-3.5" />
            暂停
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            className="flex-1"
            disabled={!canStop}
            onClick={onStop}
          >
            <Square className="w-3 h-3 fill-current" />
            结束
          </Button>
        </div>
      </div>
    </div>
  );
}
