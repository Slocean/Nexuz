import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  ZoomIn,
  ZoomOut,
  Maximize,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from "lucide-react";
import {
  WorkflowNode,
  NodeConnection,
  ThemeName,
  ThemeMode,
  NodeType,
} from "../types";
import { getThemeColors } from "../theme";
import MiniMap from "./MiniMap";
import { Button } from "@/components/ui/button";

interface CanvasProps {
  nodes: WorkflowNode[];
  connections: NodeConnection[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  onUpdateNodePosition: (nodeId: string, x: number, y: number) => void;
  onAddConnection: (
    sourceNodeId: string,
    sourceSocketId: string,
    targetNodeId: string,
    targetSocketId: string
  ) => void;
  onRemoveConnection: (connectionId: string) => void;
  onRemoveNode: (nodeId: string) => void;
  onRunSingleNode: (nodeId: string) => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  isExecuting: boolean;
  executingNodeId: string | null;
}

const NODE_WIDTH = 220;
const NODE_HEIGHT_EST = 120;

export default function Canvas({
  nodes,
  connections,
  selectedNodeId,
  onSelectNode,
  onUpdateNodePosition,
  onAddConnection,
  onRemoveConnection,
  onRemoveNode,
  onRunSingleNode,
  themeName,
  themeMode,
  isExecuting,
  executingNodeId,
}: CanvasProps) {
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 600 });

  // Local drag position — only commit to store on mouseup (avoids store thrash)
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [localDragPos, setLocalDragPos] = useState<{ x: number; y: number } | null>(null);

  const [draftConnection, setDraftConnection] = useState<{
    sourceNodeId: string;
    sourceSocketId: string;
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
  } | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const draggingIdRef = useRef<string | null>(null);
  const localPosRef = useRef<{ x: number; y: number } | null>(null);
  const draftRef = useRef(draftConnection);
  const rafRef = useRef<number | null>(null);
  const onUpdateRef = useRef(onUpdateNodePosition);
  const onAddConnRef = useRef(onAddConnection);

  useEffect(() => {
    panRef.current = { x: panX, y: panY };
  }, [panX, panY]);
  useEffect(() => {
    zoomRef.current = zoom;
  }, [zoom]);
  useEffect(() => {
    draftRef.current = draftConnection;
  }, [draftConnection]);
  useEffect(() => {
    onUpdateRef.current = onUpdateNodePosition;
  }, [onUpdateNodePosition]);
  useEffect(() => {
    onAddConnRef.current = onAddConnection;
  }, [onAddConnection]);

  const colors = getThemeColors(themeName, themeMode);

  // Track canvas size for minimap viewport + non-passive wheel zoom
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      if (cr) setCanvasSize({ w: cr.width, h: cr.height });
    });
    ro.observe(el);
    setCanvasSize({ w: el.clientWidth, h: el.clientHeight });

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
      const next = Math.min(2, Math.max(0.35, zoomRef.current * factor));
      const wx = (mx - panRef.current.x) / zoomRef.current;
      const wy = (my - panRef.current.y) / zoomRef.current;
      setZoom(next);
      setPanX(mx - wx * next);
      setPanY(my - wy * next);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      ro.disconnect();
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  const getNodeXY = useCallback(
    (node: WorkflowNode) => {
      if (draggingNodeId === node.id && localDragPos) return localDragPos;
      return { x: node.x, y: node.y };
    },
    [draggingNodeId, localDragPos]
  );

  const getSocketPosition = (node: WorkflowNode, socketId: string, isInput: boolean) => {
    const list = isInput ? node.inputs : node.outputs;
    const index = list.findIndex((s) => s.id === socketId);
    const xy = getNodeXY(node);
    if (index === -1) return { x: xy.x, y: xy.y };
    const yOffset = 44 + 18 + index * 32;
    const xOffset = isInput ? 0 : NODE_WIDTH;
    return { x: xy.x + xOffset, y: xy.y + yOffset };
  };

  const screenToCanvas = useCallback((clientX: number, clientY: number) => {
    if (!canvasRef.current) return { x: clientX, y: clientY };
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (clientX - rect.left - panRef.current.x) / zoomRef.current,
      y: (clientY - rect.top - panRef.current.y) / zoomRef.current,
    };
  }, []);

  const scheduleLocalPos = (x: number, y: number) => {
    localPosRef.current = { x, y };
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      if (localPosRef.current) setLocalDragPos({ ...localPosRef.current });
    });
  };

  const didPanOrDragRef = useRef(false);

  // Window-level move/up for smooth drag & pan (works outside canvas bounds)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (isPanningRef.current) {
        didPanOrDragRef.current = true;
        setPanX(e.clientX - panStartRef.current.x);
        setPanY(e.clientY - panStartRef.current.y);
        return;
      }
      if (draggingIdRef.current) {
        didPanOrDragRef.current = true;
        const pos = screenToCanvas(e.clientX, e.clientY);
        scheduleLocalPos(pos.x - dragOffsetRef.current.x, pos.y - dragOffsetRef.current.y);
        return;
      }
      if (draftRef.current) {
        const pos = screenToCanvas(e.clientX, e.clientY);
        setDraftConnection((prev) =>
          prev ? { ...prev, currentX: pos.x, currentY: pos.y } : null
        );
      }
    };

    const onUp = () => {
      if (draggingIdRef.current && localPosRef.current) {
        const id = draggingIdRef.current;
        const { x, y } = localPosRef.current;
        // Soft snap only on release
        const snappedX = Math.round(x / 10) * 10;
        const snappedY = Math.round(y / 10) * 10;
        onUpdateRef.current(id, snappedX, snappedY);
      }
      isPanningRef.current = false;
      draggingIdRef.current = null;
      localPosRef.current = null;
      setDraggingNodeId(null);
      setLocalDragPos(null);
      // Defer clearing draft so socket onMouseUp can still read it
      requestAnimationFrame(() => setDraftConnection(null));
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, [screenToCanvas]);

  const isPanSurface = (target: EventTarget | null) => {
    if (!target || !(target instanceof Element)) return false;
    if (target === canvasRef.current) return true;
    // Empty SVG background (connections use pointer-events on paths only)
    if (target.tagName === "svg" && canvasRef.current?.contains(target)) return true;
    if ((target as HTMLElement).dataset?.canvasPan === "true") return true;
    return false;
  };

  const startPan = (clientX: number, clientY: number) => {
    isPanningRef.current = true;
    didPanOrDragRef.current = false;
    panStartRef.current = {
      x: clientX - panRef.current.x,
      y: clientY - panRef.current.y,
    };
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    // Middle mouse: pan anywhere on canvas
    if (e.button === 1) {
      e.preventDefault();
      startPan(e.clientX, e.clientY);
      return;
    }
    // Left mouse on empty surface: pan
    if (e.button === 0 && isPanSurface(e.target)) {
      e.preventDefault();
      startPan(e.clientX, e.clientY);
    }
  };

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (didPanOrDragRef.current) {
      didPanOrDragRef.current = false;
      return;
    }
    if (!isPanSurface(e.target)) return;
    onSelectNode(null);
  };

  const handleZoomIn = () => setZoom((z) => Math.min(2, z + 0.1));
  const handleZoomOut = () => setZoom((z) => Math.max(0.35, z - 0.1));

  const handleFitView = () => {
    if (!nodes.length || !canvasRef.current) {
      setZoom(1);
      setPanX(0);
      setPanY(0);
      return;
    }
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      const xy = getNodeXY(n);
      minX = Math.min(minX, xy.x);
      minY = Math.min(minY, xy.y);
      maxX = Math.max(maxX, xy.x + NODE_WIDTH);
      maxY = Math.max(maxY, xy.y + NODE_HEIGHT_EST);
    }
    const pad = 80;
    const worldW = maxX - minX + pad * 2;
    const worldH = maxY - minY + pad * 2;
    const { w, h } = canvasSize;
    const nextZoom = Math.min(1.2, Math.max(0.35, Math.min(w / worldW, h / worldH)));
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setZoom(nextZoom);
    setPanX(w / 2 - cx * nextZoom);
    setPanY(h / 2 - cy * nextZoom);
  };

  const handleNodeDragStart = (e: React.MouseEvent, node: WorkflowNode) => {
    e.stopPropagation();
    e.preventDefault();
    onSelectNode(node.id);
    const pos = screenToCanvas(e.clientX, e.clientY);
    const xy = getNodeXY(node);
    draggingIdRef.current = node.id;
    dragOffsetRef.current = { x: pos.x - xy.x, y: pos.y - xy.y };
    localPosRef.current = { x: xy.x, y: xy.y };
    setDraggingNodeId(node.id);
    setLocalDragPos({ x: xy.x, y: xy.y });
  };

  const handleSocketDragStart = (
    e: React.MouseEvent,
    node: WorkflowNode,
    socketId: string
  ) => {
    e.stopPropagation();
    e.preventDefault();
    const socketPos = getSocketPosition(node, socketId, false);
    setDraftConnection({
      sourceNodeId: node.id,
      sourceSocketId: socketId,
      startX: socketPos.x,
      startY: socketPos.y,
      currentX: socketPos.x,
      currentY: socketPos.y,
    });
  };

  const handleSocketDragDrop = (
    e: React.MouseEvent,
    targetNode: WorkflowNode,
    targetSocketId: string
  ) => {
    e.stopPropagation();
    if (draftConnection && draftConnection.sourceNodeId !== targetNode.id) {
      onAddConnRef.current(
        draftConnection.sourceNodeId,
        draftConnection.sourceSocketId,
        targetNode.id,
        targetSocketId
      );
    }
    setDraftConnection(null);
  };

  const drawBezierPath = (x1: number, y1: number, x2: number, y2: number) => {
    const horizontalDistance = Math.abs(x2 - x1);
    const offset = Math.max(80, horizontalDistance * 0.45);
    return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
  };

  const getNodeColor = (type: NodeType | string) => {
    switch (type) {
      case "AI":
        return "#4F8CFF";
      case "Database":
        return "#34C759";
      case "HTTP":
        return "#AF52DE";
      case "Condition":
        return "#FF9500";
      case "Logic":
        return "#FFCC00";
      case "End":
        return "#FF5E57";
      default:
        return "#4F8CFF";
    }
  };

  // Nodes with live drag position for minimap
  const displayNodes = nodes.map((n) => {
    if (draggingNodeId === n.id && localDragPos) {
      return { ...n, x: localDragPos.x, y: localDragPos.y };
    }
    return n;
  });

  const isDragging = draggingNodeId != null;

  return (
    <div
      ref={canvasRef}
      onMouseDown={handleMouseDown}
      onClick={handleCanvasClick}
      onAuxClick={(e) => {
        // Prevent middle-click auto-scroll chrome behavior after pan
        if (e.button === 1) e.preventDefault();
      }}
      style={{
        backgroundColor: themeMode === "light" ? "#F5F7FB" : "#0A0D14",
      }}
      className={`flex-1 relative overflow-hidden select-none cursor-grab active:cursor-grabbing ${
        themeMode === "light" ? "bg-grid-light" : "bg-grid-dark"
      }`}
    >
      <div
        style={{ color: colors.secondaryText }}
        className="absolute bottom-5 left-5 text-[10px] font-mono font-bold uppercase tracking-wider bg-black/5 dark:bg-white/5 backdrop-blur-md px-2.5 py-1 rounded-lg border border-white/10 z-20 flex items-center space-x-1.5"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        <span>Scale: {Math.round(zoom * 100)}%</span>
      </div>

      <MiniMap
        nodes={displayNodes}
        panX={panX}
        panY={panY}
        zoom={zoom}
        canvasWidth={canvasSize.w}
        canvasHeight={canvasSize.h}
        themeMode={themeMode}
        getNodeColor={getNodeColor}
        onNavigate={(nx, ny) => {
          setPanX(nx);
          setPanY(ny);
        }}
      />

      <div className="absolute bottom-5 right-5 z-20 flex flex-col gap-2">
        <Button
          variant="outline"
          size="icon"
          onClick={handleZoomIn}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="shadow-lg"
          title="放大"
        >
          <ZoomIn className="w-4 h-4 opacity-80" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={handleZoomOut}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="shadow-lg"
          title="缩小"
        >
          <ZoomOut className="w-4 h-4 opacity-80" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onClick={handleFitView}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="shadow-lg"
          title="适应全局视图"
        >
          <Maximize className="w-4 h-4 opacity-80" />
        </Button>
      </div>

      <div
        style={{
          transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
          transformOrigin: "0 0",
          // No CSS transition while dragging — it fights pointer tracking
          transition: isDragging || isPanningRef.current ? "none" : undefined,
        }}
        className="absolute inset-0 pointer-events-none"
      >
        <svg className="absolute inset-0 w-[10000px] h-[10000px] overflow-visible pointer-events-none">
          <defs>
            <linearGradient id="connectionGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={colors.primary} stopOpacity="0.8" />
              <stop offset="100%" stopColor="#30D158" stopOpacity="0.8" />
            </linearGradient>
            <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
              <feDropShadow dx="0" dy="2" stdDeviation="4" floodOpacity="0.15" />
            </filter>
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {connections.map((conn) => {
            const sourceNode = nodes.find((n) => n.id === conn.sourceNodeId);
            const targetNode = nodes.find((n) => n.id === conn.targetNodeId);
            if (!sourceNode || !targetNode) return null;

            const p1 = getSocketPosition(sourceNode, conn.sourceSocketId, false);
            const p2 = getSocketPosition(targetNode, conn.targetSocketId, true);
            const isPathExecuting =
              isExecuting ||
              sourceNode.status === "running" ||
              targetNode.status === "running";

            return (
              <g key={conn.id} className="group pointer-events-auto cursor-pointer">
                <path
                  d={drawBezierPath(p1.x, p1.y, p2.x, p2.y)}
                  fill="none"
                  stroke="transparent"
                  strokeWidth="12"
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (
                      window.confirm(
                        "Do you want to disconnect this workflow socket connection?"
                      )
                    ) {
                      onRemoveConnection(conn.id);
                    }
                  }}
                />
                {isPathExecuting && (
                  <path
                    d={drawBezierPath(p1.x, p1.y, p2.x, p2.y)}
                    fill="none"
                    stroke={colors.primary}
                    strokeWidth="4"
                    strokeOpacity="0.4"
                    filter="url(#glow)"
                  />
                )}
                <path
                  d={drawBezierPath(p1.x, p1.y, p2.x, p2.y)}
                  fill="none"
                  stroke={
                    isPathExecuting
                      ? "url(#connectionGrad)"
                      : themeMode === "light"
                        ? "rgba(79, 140, 255, 0.45)"
                        : "rgba(255, 255, 255, 0.15)"
                  }
                  strokeWidth="2.5"
                  className={`group-hover:stroke-red-400 ${
                    isPathExecuting ? "connection-flow" : ""
                  }`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm("Disconnect this workflow pathway?")) {
                      onRemoveConnection(conn.id);
                    }
                  }}
                />
                <circle
                  cx={(p1.x + p2.x) / 2}
                  cy={(p1.y + p2.y) / 2}
                  r="10"
                  fill={themeMode === "light" ? "#FFF" : "#1A2235"}
                  stroke="#FF5E57"
                  strokeWidth="1.5"
                  className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none"
                />
                <text
                  x={(p1.x + p2.x) / 2}
                  y={(p1.y + p2.y) / 2 + 3}
                  textAnchor="middle"
                  fill="#FF5E57"
                  fontSize="10px"
                  fontWeight="bold"
                  className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none"
                >
                  ×
                </text>
              </g>
            );
          })}

          {draftConnection && (
            <path
              d={drawBezierPath(
                draftConnection.startX,
                draftConnection.startY,
                draftConnection.currentX,
                draftConnection.currentY
              )}
              fill="none"
              stroke={colors.primary}
              strokeWidth="2"
              strokeDasharray="4,4"
              className="connection-flow-fast opacity-80"
            />
          )}
        </svg>

        <div className="absolute inset-0 pointer-events-none">
          {nodes.map((node) => {
            const isSelected = selectedNodeId === node.id;
            const isNodeRunning =
              executingNodeId === node.id || node.status === "running";
            const nodeAccentColor = getNodeColor(node.type);
            const xy = getNodeXY(node);
            const thisDragging = draggingNodeId === node.id;

            return (
              <div
                key={node.id}
                onMouseDown={(e) => handleNodeDragStart(e, node)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectNode(node.id);
                }}
                style={{
                  left: xy.x,
                  top: xy.y,
                  width: NODE_WIDTH,
                  backgroundColor:
                    themeMode === "light"
                      ? "rgba(255, 255, 255, 0.72)"
                      : "rgba(24, 28, 43, 0.75)",
                  borderColor: isSelected
                    ? colors.primary
                    : themeMode === "light"
                      ? "rgba(0, 0, 0, 0.08)"
                      : "rgba(255, 255, 255, 0.06)",
                  color: colors.text,
                  // Disable transform transitions while dragging this node
                  transition: thisDragging ? "none" : undefined,
                  willChange: thisDragging ? "left, top" : undefined,
                }}
                className={`absolute rounded-[22px] border-1.5 backdrop-blur-2xl p-4 pointer-events-auto shadow-xl flex flex-col space-y-3 cursor-grab active:cursor-grabbing ${
                  isSelected
                    ? "ring-4 ring-offset-2 ring-offset-transparent ring-blue-500/20"
                    : ""
                } ${
                  themeMode === "light" ? "glass-shadow-light" : "glass-shadow-dark"
                } ${thisDragging ? "" : "hover:shadow-2xl"}`}
              >
                <div className="flex items-center justify-between border-b border-black/5 dark:border-white/5 pb-2.5 shrink-0">
                  <div className="flex items-center space-x-2 truncate">
                    <span
                      style={{
                        backgroundColor: nodeAccentColor + "1E",
                        color: nodeAccentColor,
                      }}
                      className="w-2.5 h-2.5 rounded-full"
                    />
                    <span className="font-display font-semibold text-xs truncate max-w-[120px]">
                      {node.name}
                    </span>
                  </div>

                  <div className="flex items-center space-x-1 pointer-events-auto">
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRunSingleNode(node.id);
                      }}
                      style={{ color: colors.secondaryText }}
                      className="p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 hover:text-emerald-500 transition-all cursor-pointer"
                      title="Run node solo"
                    >
                      <Loader2
                        className={`w-3 h-3 ${
                          isNodeRunning ? "animate-spin text-emerald-500" : ""
                        }`}
                      />
                    </button>
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveNode(node.id);
                      }}
                      style={{ color: colors.danger }}
                      className="p-1 rounded-lg hover:bg-red-500/15 transition-all cursor-pointer"
                      title="Delete node"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                <div className="flex flex-col space-y-3 relative">
                  {node.inputs.map((inp) => (
                    <div
                      key={inp.id}
                      className="flex items-center justify-start space-x-2 relative pointer-events-auto h-6"
                    >
                      <div
                        onMouseUp={(e) => handleSocketDragDrop(e, node, inp.id)}
                        style={{
                          backgroundColor:
                            themeMode === "light" ? "#FFFFFF" : "#111524",
                          borderColor: nodeAccentColor,
                        }}
                        className="w-3.5 h-3.5 rounded-full border-2 absolute -left-[23px] top-[5px] flex items-center justify-center hover:scale-125 hover:bg-blue-500 transition-transform cursor-crosshair z-30"
                        title="Drag connection to here"
                      >
                        <div className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-700" />
                      </div>
                      <span className="text-[11px] font-medium tracking-wide opacity-80 pl-1">
                        {inp.name}
                      </span>
                    </div>
                  ))}

                  {node.outputs.map((out) => (
                    <div
                      key={out.id}
                      className="flex items-center justify-end space-x-2 relative pointer-events-auto h-6"
                    >
                      <span className="text-[11px] font-medium tracking-wide opacity-80 pr-1">
                        {out.name}
                      </span>
                      <div
                        onMouseDown={(e) => handleSocketDragStart(e, node, out.id)}
                        style={{
                          backgroundColor: nodeAccentColor,
                          borderColor:
                            themeMode === "light" ? "#FFFFFF" : "#111524",
                        }}
                        className="w-3.5 h-3.5 rounded-full border-2 absolute -right-[23px] top-[5px] flex items-center justify-center hover:scale-125 transition-transform cursor-crosshair z-30"
                        title="Drag connection from here"
                      >
                        <div className="w-1 h-1 rounded-full bg-white" />
                      </div>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-between text-[10px] pt-1.5 border-t border-black/5 dark:border-white/5 font-mono text-slate-400">
                  <div className="flex items-center space-x-1">
                    {node.status === "success" && (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    )}
                    {node.status === "error" && (
                      <AlertCircle className="w-3 h-3 text-rose-500" />
                    )}
                    {node.status === "running" && (
                      <Loader2 className="w-3 h-3 text-blue-500 animate-spin" />
                    )}
                    <span>{node.status.toUpperCase()}</span>
                  </div>
                  <span className="opacity-60 capitalize">
                    {node.subType.replace("-", " ")}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
