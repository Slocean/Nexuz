import React, { useEffect, useRef, useState } from 'react';

export type ImagePoint = { ix: number; iy: number };
export type ImageRegion = { x1: number; y1: number; x2: number; y2: number };

type InteractionMode = 'pan' | 'point' | 'region';

export interface ZoomPanStageProps {
  src: string;
  alt?: string;
  /** pan: preview only; point: click picks pixel; region: drag selects box */
  mode?: InteractionMode;
  /** Highlight selected image pixel (point mode) */
  selectedPoint?: ImagePoint | null;
  /** Highlight selected image region (region mode) */
  selectedRegion?: ImageRegion | null;
  onPickPoint?: (pt: ImagePoint) => void;
  onPickRegion?: (region: ImageRegion) => void;
  className?: string;
  hint?: string;
}

function clientToImage(
  clientX: number,
  clientY: number,
  stage: HTMLElement,
  img: HTMLImageElement,
  offset: { x: number; y: number },
  scale: number,
): ImagePoint | null {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (nw <= 0 || nh <= 0) return null;
  const rect = stage.getBoundingClientRect();
  const cx = rect.width / 2 + offset.x;
  const cy = rect.height / 2 + offset.y;
  const displayW = nw * scale;
  const displayH = nh * scale;
  const imgLeft = cx - displayW / 2;
  const imgTop = cy - displayH / 2;
  const ix = (clientX - rect.left - imgLeft) / scale;
  const iy = (clientY - rect.top - imgTop) / scale;
  if (ix < 0 || iy < 0 || ix >= nw || iy >= nh) return null;
  return { ix, iy };
}

function imageRectToStage(
  region: ImageRegion,
  stage: HTMLElement,
  img: HTMLImageElement,
  offset: { x: number; y: number },
  scale: number,
): { left: number; top: number; width: number; height: number } | null {
  const nw = img.naturalWidth;
  const nh = img.naturalHeight;
  if (nw <= 0 || nh <= 0) return null;
  const rect = stage.getBoundingClientRect();
  const cx = rect.width / 2 + offset.x;
  const cy = rect.height / 2 + offset.y;
  const displayW = nw * scale;
  const displayH = nh * scale;
  const imgLeft = cx - displayW / 2;
  const imgTop = cy - displayH / 2;
  const x1 = Math.min(region.x1, region.x2);
  const y1 = Math.min(region.y1, region.y2);
  const x2 = Math.max(region.x1, region.x2);
  const y2 = Math.max(region.y1, region.y2);
  return {
    left: imgLeft + x1 * scale,
    top: imgTop + y1 * scale,
    width: (x2 - x1) * scale,
    height: (y2 - y1) * scale,
  };
}

/**
 * Wheel zoom + drag pan stage. Optionally supports click-to-pick and drag-to-box.
 * Region mode: normal drag = box select; Alt / Space / middle button = pan.
 * Point mode: click (little movement) = pick; drag = pan.
 */
export function ZoomPanStage({
  src,
  alt = '',
  mode = 'pan',
  selectedPoint = null,
  selectedRegion = null,
  onPickPoint,
  onPickRegion,
  className = '',
  hint,
}: ZoomPanStageProps) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [grabbing, setGrabbing] = useState(false);
  const [spaceDown, setSpaceDown] = useState(false);
  const [draftRegion, setDraftRegion] = useState<ImageRegion | null>(null);
  const [overlayTick, setOverlayTick] = useState(0);

  const stageRef = useRef<HTMLDivElement | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const dragging = useRef(false);
  const panMode = useRef(false);
  const boxMode = useRef(false);
  const last = useRef({ x: 0, y: 0 });
  const downPt = useRef({ x: 0, y: 0 });
  const startImage = useRef<ImagePoint | null>(null);

  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
    setGrabbing(false);
    setDraftRegion(null);
  }, [src]);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.12 : 0.12;
      setScale((s) => Math.min(8, Math.max(0.2, Number((s + delta * Math.max(s, 0.5)).toFixed(3)))));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        setSpaceDown(true);
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') setSpaceDown(false);
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, []);

  // Recompute overlay when transform changes
  useEffect(() => {
    setOverlayTick((t) => t + 1);
  }, [scale, offset, selectedPoint, selectedRegion, draftRegion]);

  const wantsPan = (e: React.PointerEvent) => {
    if (mode === 'pan') return true;
    if (e.button === 1) return true;
    if (e.altKey || spaceDown) return true;
    if (mode === 'point') return false; // decided after move
    return false;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    const stage = stageRef.current;
    const img = imgRef.current;
    if (!stage || !img) return;

    dragging.current = true;
    last.current = { x: e.clientX, y: e.clientY };
    downPt.current = { x: e.clientX, y: e.clientY };
    startImage.current = clientToImage(e.clientX, e.clientY, stage, img, offset, scale);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    if (mode === 'region' && !wantsPan(e) && e.button === 0) {
      boxMode.current = true;
      panMode.current = false;
      if (startImage.current) {
        const p = startImage.current;
        setDraftRegion({ x1: p.ix, y1: p.iy, x2: p.ix, y2: p.iy });
      }
    } else if (mode === 'point' && e.button === 0 && !e.altKey && !spaceDown) {
      // Tentative: may become pan if moved
      boxMode.current = false;
      panMode.current = false;
    } else {
      panMode.current = true;
      boxMode.current = false;
      setGrabbing(true);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging.current) return;
    const stage = stageRef.current;
    const img = imgRef.current;
    const dx = e.clientX - last.current.x;
    const dy = e.clientY - last.current.y;
    last.current = { x: e.clientX, y: e.clientY };

    if (boxMode.current && stage && img) {
      const cur = clientToImage(e.clientX, e.clientY, stage, img, offset, scale);
      if (cur && startImage.current) {
        setDraftRegion({
          x1: startImage.current.ix,
          y1: startImage.current.iy,
          x2: cur.ix,
          y2: cur.iy,
        });
      }
      return;
    }

    if (mode === 'point' && !panMode.current) {
      const moved =
        Math.hypot(e.clientX - downPt.current.x, e.clientY - downPt.current.y) > 4;
      if (moved) {
        panMode.current = true;
        setGrabbing(true);
      } else {
        return;
      }
    }

    if (panMode.current || mode === 'pan') {
      setOffset((o) => ({ x: o.x + dx, y: o.y + dy }));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const wasBox = boxMode.current;
    const wasPan = panMode.current;
    const start = startImage.current;
    dragging.current = false;
    boxMode.current = false;
    panMode.current = false;
    setGrabbing(false);
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }

    if (wasBox && draftRegion) {
      const x1 = Math.floor(Math.min(draftRegion.x1, draftRegion.x2));
      const y1 = Math.floor(Math.min(draftRegion.y1, draftRegion.y2));
      const x2 = Math.ceil(Math.max(draftRegion.x1, draftRegion.x2));
      const y2 = Math.ceil(Math.max(draftRegion.y1, draftRegion.y2));
      setDraftRegion(null);
      if (x2 - x1 >= 2 && y2 - y1 >= 2) {
        onPickRegion?.({ x1, y1, x2, y2 });
      }
      return;
    }

    if (mode === 'point' && !wasPan && e.button === 0 && start) {
      const image = imgRef.current;
      onPickPoint?.({
        ix: Math.max(0, Math.min((image?.naturalWidth || 1) - 1, Math.round(start.ix))),
        iy: Math.max(0, Math.min((image?.naturalHeight || 1) - 1, Math.round(start.iy))),
      });
    }
  };

  const stage = stageRef.current;
  const img = imgRef.current;
  const showRegion = draftRegion || selectedRegion;
  const regionBox =
    showRegion && stage && img
      ? imageRectToStage(showRegion, stage, img, offset, scale)
      : null;
  void overlayTick;

  const pointMarker =
    selectedPoint && stage && img
      ? (() => {
          const box = imageRectToStage(
            {
              x1: selectedPoint.ix,
              y1: selectedPoint.iy,
              x2: selectedPoint.ix + 1,
              y2: selectedPoint.iy + 1,
            },
            stage,
            img,
            offset,
            scale,
          );
          return box;
        })()
      : null;

  const defaultHint =
    mode === 'point'
      ? '单击取点 · 拖动平移 · 滚轮缩放 · 双击复位'
      : mode === 'region'
        ? '拖动框选 · Alt/空格拖平移 · 滚轮缩放 · 双击复位'
        : '滚轮缩放 · 拖动平移 · 双击复位';

  const cursorClass = grabbing
    ? 'cursor-grabbing'
    : mode === 'region' && !spaceDown
      ? 'cursor-crosshair'
      : mode === 'point'
        ? 'cursor-crosshair'
        : 'cursor-grab';

  return (
    <div className={`relative w-full h-full min-h-0 flex flex-col ${className}`}>
      <div
        ref={stageRef}
        className={`relative flex-1 min-h-0 overflow-hidden rounded-lg bg-black/10 dark:bg-black/50 select-none touch-none ${cursorClass}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => {
          setScale(1);
          setOffset({ x: 0, y: 0 });
        }}
      >
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          draggable={false}
          className="absolute left-1/2 top-1/2 max-w-none pointer-events-none"
          style={{
            transform: `translate(calc(-50% + ${offset.x}px), calc(-50% + ${offset.y}px)) scale(${scale})`,
            transformOrigin: 'center center',
          }}
          onLoad={() => setOverlayTick((t) => t + 1)}
        />
        {regionBox && regionBox.width > 0 && regionBox.height > 0 && (
          <div
            className="absolute pointer-events-none border-2 border-sky-400 bg-sky-400/15"
            style={{
              left: regionBox.left,
              top: regionBox.top,
              width: regionBox.width,
              height: regionBox.height,
            }}
          />
        )}
        {pointMarker && (
          <div
            className="absolute pointer-events-none"
            style={{
              left: pointMarker.left - 6,
              top: pointMarker.top - 6,
              width: 12,
              height: 12,
            }}
          >
            <div className="absolute inset-0 rounded-full border-2 border-rose-400 bg-rose-400/40" />
            <div className="absolute left-1/2 top-0 bottom-0 w-px -translate-x-1/2 bg-rose-400" />
            <div className="absolute top-1/2 left-0 right-0 h-px -translate-y-1/2 bg-rose-400" />
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 pt-2 shrink-0">
        <p className="text-[11px] opacity-50">{hint ?? defaultHint}</p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => setScale((s) => Math.max(0.2, Number((s / 1.2).toFixed(3))))}
          >
            −
          </button>
          <span className="text-[11px] font-mono opacity-60 w-12 text-center">
            {Math.round(scale * 100)}%
          </span>
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => setScale((s) => Math.min(8, Number((s * 1.2).toFixed(3))))}
          >
            +
          </button>
          <button
            type="button"
            className="h-7 px-2 text-xs rounded-md border border-black/10 dark:border-white/10 hover:bg-black/5 dark:hover:bg-white/10"
            onClick={() => {
              setScale(1);
              setOffset({ x: 0, y: 0 });
            }}
          >
            复位
          </button>
        </div>
      </div>
    </div>
  );
}

export default ZoomPanStage;
