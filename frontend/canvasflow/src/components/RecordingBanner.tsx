/**
 * In-app recording float (shadcn Dialog, non-modal).
 */
import React from 'react';
import { CircleDot, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export default function RecordingBanner({
  open,
  onStop,
}: {
  open: boolean;
  onStop: () => void;
}) {
  return (
    <Dialog open={open} modal={false}>
      <DialogContent
        showClose={false}
        showOverlay={false}
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
        className="fixed top-16 right-4 left-auto translate-x-0 translate-y-0 w-[min(320px,calc(100vw-2rem))] gap-3 p-4 shadow-2xl data-[state=open]:zoom-in-95"
      >
        <DialogHeader className="pr-0 space-y-1.5">
          <DialogTitle className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-rose-500/15">
              <CircleDot className="h-3.5 w-3.5 text-rose-500 animate-pulse" />
            </span>
            正在录制
          </DialogTitle>
          <DialogDescription>
            正在记录鼠标与键盘操作。完成后点击停止，节点会追加到画布。也可按{' '}
            <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[10px]">
              Ctrl+Shift+F10
            </kbd>
          </DialogDescription>
        </DialogHeader>
        <Button type="button" variant="destructive" className="w-full" onClick={onStop}>
          <Square className="w-3.5 h-3.5 fill-current" />
          停止录制
        </Button>
      </DialogContent>
    </Dialog>
  );
}
