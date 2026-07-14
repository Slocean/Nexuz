import React, { useMemo, useRef } from "react";
import { WorkflowNode, ThemeMode } from "../types";

interface MiniMapProps {
  nodes: WorkflowNode[];
  panX: number;
  panY: number;
  zoom: number;
  canvasWidth: number;
  canvasHeight: number;
  themeMode: ThemeMode;
  getNodeColor: (type: string) => string;
  onNavigate: (panX: number, panY: number) => void;
}

const MAP_W = 168;
const MAP_H = 112;
const NODE_W = 220;
const NODE_H = 120;
const PAD = 80;

export default function MiniMap({
  nodes,
  panX,
  panY,
  zoom,
  canvasWidth,
  canvasHeight,
  themeMode,
  getNodeColor,
  onNavigate,
}: MiniMapProps) {
  const dragging = useRef(false);

  const bounds = useMemo(() => {
    if (nodes.length === 0) {
      return { minX: 0, minY: 0, maxX: 800, maxY: 600 };
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + NODE_W);
      maxY = Math.max(maxY, n.y + NODE_H);
    }
    return {
      minX: minX - PAD,
      minY: minY - PAD,
      maxX: maxX + PAD,
      maxY: maxY + PAD,
    };
  }, [nodes]);

  const worldW = Math.max(1, bounds.maxX - bounds.minX);
  const worldH = Math.max(1, bounds.maxY - bounds.minY);
  const scale = Math.min(MAP_W / worldW, MAP_H / worldH);

  const toMap = (x: number, y: number) => ({
    x: (x - bounds.minX) * scale,
    y: (y - bounds.minY) * scale,
  });

  // Visible viewport in canvas/world space
  const viewWorld = {
    x: -panX / zoom,
    y: -panY / zoom,
    w: canvasWidth / zoom,
    h: canvasHeight / zoom,
  };
  const viewMap = toMap(viewWorld.x, viewWorld.y);
  const viewMapW = viewWorld.w * scale;
  const viewMapH = viewWorld.h * scale;

  const navigateFromClient = (clientX: number, clientY: number, el: HTMLElement) => {
    const rect = el.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const worldX = mx / scale + bounds.minX;
    const worldY = my / scale + bounds.minY;
    // Center viewport on clicked world point
    const nextPanX = canvasWidth / 2 - worldX * zoom;
    const nextPanY = canvasHeight / 2 - worldY * zoom;
    onNavigate(nextPanX, nextPanY);
  };

  const surface = themeMode === "light" ? "rgba(255,255,255,0.85)" : "rgba(18,22,34,0.9)";
  const border = themeMode === "light" ? "rgba(0,0,0,0.1)" : "rgba(255,255,255,0.12)";
  const mask = themeMode === "light" ? "rgba(245,247,251,0.55)" : "rgba(10,13,20,0.55)";

  return (
    <div
      className="rounded-xl border overflow-hidden shadow-lg backdrop-blur-md cursor-crosshair select-none relative"
      style={{
        width: MAP_W,
        height: MAP_H,
        backgroundColor: surface,
        borderColor: border,
      }}
      title="全局视图 — 点击或拖动以导航"
      onMouseDown={(e) => {
        e.stopPropagation();
        e.preventDefault();
        dragging.current = true;
        navigateFromClient(e.clientX, e.clientY, e.currentTarget);
        const target = e.currentTarget;
        const onMove = (ev: MouseEvent) => {
          if (!dragging.current) return;
          navigateFromClient(ev.clientX, ev.clientY, target);
        };
        const onUp = () => {
          dragging.current = false;
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      }}
    >
      <svg width={MAP_W} height={MAP_H} className="block">
        <rect width={MAP_W} height={MAP_H} fill={mask} />
        {nodes.map((n) => {
          const p = toMap(n.x, n.y);
          return (
            <rect
              key={n.id}
              x={p.x}
              y={p.y}
              width={NODE_W * scale}
              height={NODE_H * scale}
              rx={2}
              fill={getNodeColor(n.type)}
              opacity={0.85}
            />
          );
        })}
        <rect
          x={viewMap.x}
          y={viewMap.y}
          width={Math.max(8, viewMapW)}
          height={Math.max(8, viewMapH)}
          fill="rgba(79, 140, 255, 0.18)"
          stroke="#4F8CFF"
          strokeWidth={1.5}
          rx={2}
        />
      </svg>
    </div>
  );
}
