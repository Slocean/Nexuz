import React, { useCallback, useRef, useState } from "react";
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
}

/** Screenshot + markers; click to re-place the selected point. */
export default function PointConfirmPanel({
  conversationId,
  shot,
  points,
  themeName,
  themeMode,
  onPointsChange,
}: PointConfirmPanelProps) {
  const colors = getThemeColors(themeName, themeMode);
  const [selected, setSelected] = useState<string | null>(points[0]?.ref_id ?? null);
  const [busy, setBusy] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  const handleImgClick = useCallback(
    async (e: React.MouseEvent<HTMLImageElement>) => {
      if (!selected || !shot?.data_url || busy) return;
      const img = imgRef.current;
      if (!img) return;
      const rect = img.getBoundingClientRect();
      const scaleX = (shot.width || img.naturalWidth) / rect.width;
      const scaleY = (shot.height || img.naturalHeight) / rect.height;
      const localX = (e.clientX - rect.left) * scaleX;
      const localY = (e.clientY - rect.top) * scaleY;
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

  const w = shot?.width || 1;
  const h = shot?.height || 1;
  const left = shot?.left || 0;
  const top = shot?.top || 0;

  return (
    <div
      className="mx-4 mb-3 rounded-xl border p-3 space-y-2"
      style={{ borderColor: colors.border, backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.02)" : "rgba(255,255,255,0.03)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium" style={{ color: colors.text }}>
          点位预览
        </p>
        <p className="text-[11px]" style={{ color: colors.secondaryText }}>
          选中后点击截图可修正
        </p>
      </div>

      {points.length > 0 ? (
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
                {p.source === "user_override" ? " · 已修正" : p.source ? ` · ${p.source}` : ""}
              </Button>
            );
          })}
        </div>
      ) : null}

      {shot?.data_url ? (
        <div className="relative w-full overflow-hidden rounded-lg border" style={{ borderColor: colors.border }}>
          <img
            ref={imgRef}
            src={shot.data_url}
            alt="screen"
            className="w-full h-auto max-h-48 object-contain cursor-crosshair select-none"
            draggable={false}
            onClick={(e) => void handleImgClick(e)}
          />
          {points.map((p) => {
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
          })}
        </div>
      ) : null}

      {busy ? (
        <p className="text-[11px]" style={{ color: colors.secondaryText }}>
          正在更新点位…
        </p>
      ) : null}
    </div>
  );
}
