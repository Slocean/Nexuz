/**
 * In-app recording float — fixed panel (not Dialog/portal), so it stays inside the window.
 */
import React from 'react';
import { CircleDot, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function RecordingBanner({
  open,
  onStop,
  mode = 'coord',
}: {
  open: boolean;
  onStop: () => void;
  mode?: 'coord' | 'frida_ui' | string;
}) {
  if (!open) return null;

  const isFrida = mode === 'frida_ui';

  return (
    <div
      className="fixed top-16 right-4 z-[90] w-[min(320px,calc(100vw-2rem))] pointer-events-auto"
      role="status"
      aria-live="polite"
    >
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--popover)] text-[var(--popover-foreground)] shadow-2xl backdrop-blur-xl p-4 space-y-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 h-8 w-8 rounded-xl bg-rose-500/15 flex items-center justify-center shrink-0">
            <CircleDot className="w-4 h-4 text-rose-500 animate-pulse" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-display font-semibold text-sm text-[var(--popover-foreground)]">
              正在录制 · {isFrida ? 'Frida UI' : '坐标'}
            </div>
            <p className="text-[12px] leading-relaxed mt-0.5 text-[var(--muted-foreground)]">
              {isFrida
                ? '请在游戏内点击 UI 控件（Button/Toggle/Dropdown）。左右键会自动记录。'
                : '正在记录鼠标与键盘操作，左右键会自动写入节点。'}{' '}
              点下方停止，或顶栏「停止录制」，或按{' '}
              <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[11px]">
                Ctrl+Shift+F10
              </kbd>
            </p>
          </div>
        </div>
        <Button type="button" variant="destructive" className="w-full" onClick={onStop}>
          <Square className="w-3.5 h-3.5 fill-current" />
          停止录制
        </Button>
      </div>
    </div>
  );
}
