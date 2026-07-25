import React, { useCallback, useRef, useState } from "react";
import { X, ZoomIn } from "lucide-react";
import { ThemeMode, ThemeName } from "../types";
import { getThemeColors } from "../theme";
import { Button } from "@/components/ui/button";
import { bridge } from "@/bridge";

export interface AiPointPreview {
  ref_id: string;
  x?: number;
  y?: number;
  label?: string;
  source?: string;
  shot_id?: string;
  matched_text?: string;
  bbox?: { left?: number; top?: number; width?: number; height?: number };
}

export interface AiShotPreview {
  shot_id?: string;
  width?: number;
  height?: number;
  left?: number;
  top?: number;
  data_url?: string;
}

interface PointConfirmPanelProps {
  conversationId: string;
  shot: AiShotPreview | null;
  points: AiPointPreview[];
  themeName: ThemeName;
  themeMode: ThemeMode;
  onPointsChange: (points: AiPointPreview[]) => void;
  onDismiss?: () => void;
}

/**
 * Optional correction UI for session-level vision/OCR points.
 * Most OCR-bound flows never need this; dismiss anytime.
 */
export default function PointConfirmPanel({
  conversationId,
  shot,
  points,
  themeName,
  themeMode,
  onPointsChange,
  onDismiss,
}: PointConfirmPanelProps) {
  const colors = getThemeColors(themeName, themeMode);
  const [selected, setSelected] = useState<string | null>(points[0]?.ref_id ?? null);
  const [busy, setBusy] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const zoomImgRef = useRef<HTMLImageElement>(null);

  const placeAt = useCallback(
    async (clientX: number, clientY: number, img: HTMLImageElement | null) => {
      if (!selected || !shot?.data_url || busy || !img) return;
      const rect = img.getBoundingClientRect();
      const scaleX = (shot.width || img.naturalWidth) / rect.width;
      const scaleY = (shot.height || img.naturalHeight) / rect.height;
      const localX = (clientX - rect.left) * scaleX;
      const localY = (clientY - rect.top) * scaleY;
      const absX = Math.round(localX + (shot.left || 0));
      const absY = Math.round(localY + (shot.top || 0));
      setBusy(true);
      try {
        const res = await bridge.aiOverridePoint(conversationId, selected, absX, absY);
        if (res?.ok && Array.isArray(res.points)) {
          onPointsChange(res.points);
        }
      } finally {
        setBusy(false);
      }
    },
    [busy, conversationId, onPointsChange, selected, shot]
  );

  if (!shot?.data_url && points.length === 0) return null;
  if (points.length === 0) return null;

  const w = shot?.width || 1;
  const h = shot?.height || 1;
  const left = shot?.left || 0;
  const top = shot?.top || 0;

  const markers = (imgW: number, imgH: number) =>
    points.map((p) => {
      if (p.x == null || p.y == null) return null;
      const px = ((p.x - left) / w) * 100;
      const py = ((p.y - top) / h) * 100;
      const isSel = selected === p.ref_id;
      return (
        <div
          key={p.ref_id}
          className="absolute pointer-events-none"
          style={{
            left: `${px}%`,
            top: `${py}%`,
            transform: "translate(-50%, -50%)",
          }}
        >
          <div
            className="w-3 h-3 rounded-full border-2"
            style={{
              borderColor: isSel ? "#ef4444" : colors.primary,
              backgroundColor: isSel ? "rgba(239,68,68,0.5)" : `${colors.primary}88`,
              boxShadow: "0 0 0 1px rgba(0,0,0,0.35)",
            }}
          />
        </div>
      );
    });

  return (
    <>
      <div
        className="mx-4 mb-3 rounded-xl border p-3 space-y-2"
        style={{
          borderColor: colors.border,
          backgroundColor:
            themeMode === "light" ? "rgba(0,0,0,0.02)" : "rgba(255,255,255,0.03)",
        }}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-medium" style={{ color: colors.text }}>
              可选：修正自动取点
            </p>
            <p className="text-[11px] mt-0.5 leading-relaxed" style={{ color: colors.secondaryText }}>
              仅当编排期截图定点不准时使用。多数「文字点击」流程用 OCR
              绑定，运行时再识别，可直接关闭本面板。
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {shot?.data_url ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0"
                title="放大查看"
                onClick={() => setZoomed(true)}
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </Button>
            ) : null}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0"
              title="关闭（不需要修正）"
              onClick={() => onDismiss?.()}
            >
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {points.map((p) => {
            const active = selected === p.ref_id;
            return (
              <Button
                key={p.ref_id}
                type="button"
                size="sm"
                variant={active ? "default" : "outline"}
                className="h-7 text-[11px] px-2"
                style={active ? { backgroundColor: colors.primary } : undefined}
                onClick={() => setSelected(p.ref_id)}
              >
                {p.label || p.ref_id}
                {p.source === "user_override"
                  ? " · 已修正"
                  : p.source
                    ? ` · ${p.source}`
                    : ""}
              </Button>
            );
          })}
        </div>

        {shot?.data_url ? (
          <div
            className="relative w-full overflow-hidden rounded-lg border"
            style={{ borderColor: colors.border }}
          >
            <img
              ref={imgRef}
              src={shot.data_url}
              alt="screen"
              className="w-full h-auto max-h-40 object-contain cursor-crosshair select-none"
              draggable={false}
              onClick={(e) => void placeAt(e.clientX, e.clientY, imgRef.current)}
            />
            {markers(w, h)}
          </div>
        ) : null}

        {busy ? (
          <p className="text-[11px]" style={{ color: colors.secondaryText }}>
            正在更新点位…
          </p>
        ) : (
          <p className="text-[11px]" style={{ color: colors.secondaryText }}>
            先点上方标签选中目标，再点截图落点；或点右上角关闭。
          </p>
        )}
      </div>

      {zoomed && shot?.data_url ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center p-4"
          style={{ backgroundColor: "rgba(0,0,0,0.72)" }}
          onClick={() => setZoomed(false)}
        >
          <div
            className="relative max-w-[min(96vw,1200px)] max-h-[90vh] w-full rounded-xl border overflow-auto"
            style={{
              borderColor: colors.border,
              backgroundColor: themeMode === "light" ? "#111" : "#0a0a0a",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 z-10 flex items-center justify-between gap-2 px-3 py-2 border-b"
              style={{ borderColor: colors.border, backgroundColor: "rgba(0,0,0,0.85)" }}>
              <p className="text-xs text-white/80">
                放大修正 · 选中标签后点击图上位置
              </p>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 text-xs text-white"
                onClick={() => setZoomed(false)}
              >
                关闭
              </Button>
            </div>
            <div className="relative">
              <img
                ref={zoomImgRef}
                src={shot.data_url}
                alt="screen-zoom"
                className="w-full h-auto cursor-crosshair select-none"
                draggable={false}
                onClick={(e) => void placeAt(e.clientX, e.clientY, zoomImgRef.current)}
              />
              {markers(w, h)}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
