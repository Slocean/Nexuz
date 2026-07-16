import React, { useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  ZoomPanStage,
  type ImagePoint,
  type ImageRegion,
} from './ZoomPanStage';

export type ScreenshotCapture = {
  data_url: string;
  width: number;
  height: number;
  left: number;
  top: number;
  coord_space?: Record<string, unknown>;
};

export type ScreenshotPickMode = 'point' | 'region' | 'template';

export type ScreenshotPickResult =
  | { ok: true; kind: 'point'; x: number; y: number; color: string | null; ix: number; iy: number }
  | {
      ok: true;
      kind: 'region' | 'template';
      region: [number, number, number, number];
      x1: number;
      y1: number;
      x2: number;
      y2: number;
    }
  | { ok: false; cancelled: true }
  | { ok: false; error: string };

function sampleColorFromImage(
  dataUrl: string,
  ix: number,
  iy: number,
): Promise<string | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          resolve(null);
          return;
        }
        ctx.drawImage(img, 0, 0);
        const x = Math.max(0, Math.min(img.naturalWidth - 1, Math.floor(ix)));
        const y = Math.max(0, Math.min(img.naturalHeight - 1, Math.floor(iy)));
        const d = ctx.getImageData(x, y, 1, 1).data;
        const hex =
          '#' +
          [d[0], d[1], d[2]]
            .map((n) => n.toString(16).padStart(2, '0'))
            .join('')
            .toUpperCase();
        resolve(hex);
      } catch {
        resolve(null);
      }
    };
    img.onerror = () => resolve(null);
    img.src = dataUrl;
  });
}

export function ScreenshotPickDialog({
  open,
  mode,
  capture,
  onClose,
}: {
  open: boolean;
  mode: ScreenshotPickMode;
  capture: ScreenshotCapture | null;
  onClose: (result: ScreenshotPickResult) => void;
}) {
  const [point, setPoint] = useState<ImagePoint | null>(null);
  const [region, setRegion] = useState<ImageRegion | null>(null);
  const [previewColor, setPreviewColor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPoint(null);
    setRegion(null);
    setPreviewColor(null);
    setBusy(false);
  }, [open, capture?.data_url, mode]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose({ ok: false, cancelled: true });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const title = useMemo(() => {
    if (mode === 'point') return '截图取点';
    if (mode === 'template') return '截图截模板';
    return '截图框选';
  }, [mode]);

  const handlePickPoint = async (pt: ImagePoint) => {
    setPoint(pt);
    if (capture?.data_url) {
      const color = await sampleColorFromImage(capture.data_url, pt.ix, pt.iy);
      setPreviewColor(color);
    }
  };

  const canConfirm =
    mode === 'point' ? !!point : !!(region && region.x2 - region.x1 >= 2 && region.y2 - region.y1 >= 2);

  const handleConfirm = async () => {
    if (!capture || busy) return;
    setBusy(true);
    try {
      if (mode === 'point' && point) {
        const color =
          previewColor ??
          (await sampleColorFromImage(capture.data_url, point.ix, point.iy));
        const x = capture.left + point.ix;
        const y = capture.top + point.iy;
        onClose({
          ok: true,
          kind: 'point',
          x,
          y,
          color,
          ix: point.ix,
          iy: point.iy,
        });
        return;
      }
      if ((mode === 'region' || mode === 'template') && region) {
        const x1 = capture.left + region.x1;
        const y1 = capture.top + region.y1;
        const x2 = capture.left + region.x2;
        const y2 = capture.top + region.y2;
        onClose({
          ok: true,
          kind: mode,
          region: [x1, y1, x2, y2],
          x1,
          y1,
          x2,
          y2,
        });
        return;
      }
    } finally {
      setBusy(false);
    }
  };

  const screenHint =
    mode === 'point' && point && capture
      ? `屏幕 (${capture.left + point.ix}, ${capture.top + point.iy})`
      : region && capture
        ? `区域 [${capture.left + region.x1}, ${capture.top + region.y1}]–[${capture.left + region.x2}, ${capture.top + region.y2}]`
        : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose({ ok: false, cancelled: true });
      }}
    >
      <DialogContent className="max-w-[min(96vw,88rem)] w-[min(96vw,88rem)] h-[min(92vh,56rem)] p-4 flex flex-col gap-3">
        <DialogHeader className="shrink-0">
          <DialogTitle className="text-sm">{title}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 min-h-0 flex flex-col">
          {capture?.data_url ? (
            <ZoomPanStage
              src={capture.data_url}
              alt="桌面截图"
              mode={mode === 'point' ? 'point' : 'region'}
              selectedPoint={point}
              selectedRegion={region}
              onPickPoint={(pt) => {
                void handlePickPoint(pt);
              }}
              onPickRegion={setRegion}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center rounded-lg bg-black/5 dark:bg-black/40">
              <p className="text-xs opacity-50">无截图</p>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0 min-h-8">
          {mode === 'point' && previewColor && (
            <span className="inline-flex items-center gap-2 text-xs font-mono opacity-80">
              <span
                className="inline-block w-4 h-4 rounded border border-black/20 dark:border-white/20"
                style={{ background: previewColor }}
              />
              {previewColor}
            </span>
          )}
          {screenHint && <span className="text-xs font-mono opacity-60">{screenHint}</span>}
          <span className="flex-1" />
          <DialogFooter className="p-0 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onClose({ ok: false, cancelled: true })}
            >
              取消
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!canConfirm || busy}
              onClick={() => void handleConfirm()}
            >
              {mode === 'template' ? '截取模板' : '确认'}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default ScreenshotPickDialog;
