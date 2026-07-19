import React, { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo, memo } from "react";
import {
  ZoomIn,
  ZoomOut,
  Maximize,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Pause,
  Play,
  Waypoints,
  ChevronDown,
  ChevronRight,
  MousePointer2,
  SquareDashedMousePointer,
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
import NodeContextMenu, { type NodeContextMenuState } from "./NodeContextMenu";
import { Button } from "@/components/ui/button";
import { useAppDialog } from "./AppDialogs";
import { computeAutoLayout } from "../autoLayout";
import { computeLoopBodyFrames } from "../nexuzAdapter";
import { useFlowStore } from "@/store/flowModelStore";

interface CanvasProps {
  nodes: WorkflowNode[];
  connections: NodeConnection[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  onUpdateNodePosition: (nodeId: string, x: number, y: number) => void;
  onUpdateNodePositions?: (updates: { id: string; x: number; y: number }[]) => void;
  onAddConnection: (
    sourceNodeId: string,
    sourceSocketId: string,
    targetNodeId: string,
    targetSocketId: string
  ) => void;
  onRemoveConnection: (connectionId: string) => void;
  onRemoveNode: (nodeId: string) => void;
  onRemoveNodes?: (nodeIds: string[]) => void;
  onDuplicateNodes?: (nodeIds: string[]) => void;
  onDropBlock?: (blockType: string, x: number, y: number) => void;
  onRunSingleNode?: (nodeId: string) => void;
  onToggleBreakpoint?: (nodeId: string) => void;
  onUpdateNodeName?: (nodeId: string, name: string) => void;
  onToggleNodeCollapsed?: (nodeId: string) => void;
  onSetEntry?: (nodeId: string) => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  isExecuting: boolean;
  /** idle | running | paused | stopping | breakpoint */
  execStatus?: string;
  executingNodeId?: string | null;
  debugMode?: boolean;
  breakpoints?: string[];
}

const NODE_WIDTH = 176;
/** Layout metrics must match the node card CSS (p-2 / header / h-[18px] / space-y-1). */
const NODE_PAD_TOP = 8;
const NODE_HEADER_H = 28;
const SOCKET_ROW_H = 18;
const SOCKET_ROW_GAP = 4;
const SOCKET_DOT_OFFSET = 9; // vertical center within the row
const NODE_HEIGHT_EST = 96;
const DATA_SOCKET_COLOR = '#AF52DE';
/** Match Tailwind `rounded-xl` (12px) + slight outward offset for the orbit stroke. */
const NODE_ORBIT_RADIUS = 12;
const NODE_ORBIT_PAD = 2;

/** Light spot that travels exactly along the node border. */
function NodeRunningOrbit() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: NODE_WIDTH, h: NODE_HEIGHT_EST });

  useLayoutEffect(() => {
    const parent = svgRef.current?.parentElement;
    if (!parent) return;
    const update = () => {
      // Use layout size (not getBoundingClientRect) so canvas zoom doesn't skew the path.
      const width = parent.offsetWidth;
      const height = parent.offsetHeight;
      if (width > 0 && height > 0) {
        setSize({ w: width, h: height });
      }
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  const w = size.w + NODE_ORBIT_PAD * 2;
  const h = size.h + NODE_ORBIT_PAD * 2;
  const r = NODE_ORBIT_RADIUS + NODE_ORBIT_PAD;

  return (
    <svg
      ref={svgRef}
      className="node-running-orbit"
      aria-hidden
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
    >
      <rect
        className="node-running-orbit-track"
        x={1}
        y={1}
        width={w - 2}
        height={h - 2}
        rx={r}
        ry={r}
        pathLength={100}
      />
      <rect
        className="node-running-orbit-tail"
        x={1}
        y={1}
        width={w - 2}
        height={h - 2}
        rx={r}
        ry={r}
        pathLength={100}
      />
      <rect
        className="node-running-orbit-beam"
        x={1}
        y={1}
        width={w - 2}
        height={h - 2}
        rx={r}
        ry={r}
        pathLength={100}
      />
    </svg>
  );
}

/** Static amber ring while the current node is paused mid-run. */
function NodePausedRing() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ w: NODE_WIDTH, h: NODE_HEIGHT_EST });

  useLayoutEffect(() => {
    const parent = svgRef.current?.parentElement;
    if (!parent) return;
    const update = () => {
      const width = parent.offsetWidth;
      const height = parent.offsetHeight;
      if (width > 0 && height > 0) {
        setSize({ w: width, h: height });
      }
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  const w = size.w + NODE_ORBIT_PAD * 2;
  const h = size.h + NODE_ORBIT_PAD * 2;
  const r = NODE_ORBIT_RADIUS + NODE_ORBIT_PAD;

  return (
    <svg
      ref={svgRef}
      className="node-paused-ring"
      aria-hidden
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
    >
      <rect
        className="node-paused-ring-stroke"
        x={1}
        y={1}
        width={w - 2}
        height={h - 2}
        rx={r}
        ry={r}
      />
    </svg>
  );
}

function Canvas({
  nodes,
  connections,
  selectedNodeId,
  onSelectNode,
  onUpdateNodePosition,
  onUpdateNodePositions,
  onAddConnection,
  onRemoveConnection,
  onRemoveNode,
  onRemoveNodes,
  onDuplicateNodes,
  onDropBlock,
  onRunSingleNode,
  onToggleBreakpoint,
  onUpdateNodeName,
  onToggleNodeCollapsed,
  onSetEntry,
  themeName,
  themeMode,
  isExecuting: _isExecuting,
  execStatus = "idle",
  executingNodeId,
  debugMode = false,
  breakpoints = [],
}: CanvasProps) {
  const { confirm, alert } = useAppDialog();
  const flowEntry = useFlowStore((s) => s.flow?.entry ?? null);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [canvasSize, setCanvasSize] = useState({ w: 800, h: 600 });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [showDataLinks, setShowDataLinks] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<NodeContextMenuState | null>(null);

  const loopFrames = useMemo(
    () => computeLoopBodyFrames(nodes, connections),
    [nodes, connections],
  );
  const [editingNameId, setEditingNameId] = useState<string | null>(null);
  const [editingNameValue, setEditingNameValue] = useState("");
  /** pan = 拖动画布；select = 空处拖动框选 */
  const [canvasTool, setCanvasTool] = useState<"pan" | "select">("pan");
  const [marquee, setMarquee] = useState<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  } | null>(null);

  // Local drag position — only commit to store on mouseup (avoids store thrash)
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [localDragPos, setLocalDragPos] = useState<{ x: number; y: number } | null>(null);
  const [localGroupDelta, setLocalGroupDelta] = useState<{ x: number; y: number } | null>(null);

  const [draftConnection, setDraftConnection] = useState<{
    sourceNodeId: string;
    sourceSocketId: string;
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
  } | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);
  const worldLayerRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const isPanningRef = useRef(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const draggingIdRef = useRef<string | null>(null);
  const dragGroupIdsRef = useRef<string[]>([]);
  const groupStartPosRef = useRef<Record<string, { x: number; y: number }>>({});
  const localPosRef = useRef<{ x: number; y: number } | null>(null);
  const groupDeltaRef = useRef<{ x: number; y: number } | null>(null);
  const marqueeRef = useRef<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const isMarqueeRef = useRef(false);
  const clipboardRef = useRef<string[]>([]);
  const selectedIdsRef = useRef<string[]>([]);
  const editingNameIdRef = useRef<string | null>(null);
  const editingNameValueRef = useRef("");
  const onUpdateNodeNameRef = useRef(onUpdateNodeName);
  const canvasToolRef = useRef<"pan" | "select">("pan");
  const draftRef = useRef(draftConnection);
  const rafRef = useRef<number | null>(null);
  const marqueeRafRef = useRef<number | null>(null);
  const draftRafRef = useRef<number | null>(null);

  const applyWorldTransform = useCallback(() => {
    const el = worldLayerRef.current;
    if (!el) return;
    el.style.transform = `translate(${panRef.current.x}px, ${panRef.current.y}px) scale(${zoomRef.current})`;
  }, []);

  const setPan = useCallback(
    (x: number, y: number) => {
      panRef.current = { x, y };
      setPanX(x);
      setPanY(y);
      applyWorldTransform();
    },
    [applyWorldTransform],
  );
  const onUpdateRef = useRef(onUpdateNodePosition);
  const onUpdateManyRef = useRef(onUpdateNodePositions);
  const onAddConnRef = useRef(onAddConnection);
  const onRemoveNodesRef = useRef(onRemoveNodes);
  const onDuplicateNodesRef = useRef(onDuplicateNodes);
  const onSelectNodeRef = useRef(onSelectNode);
  const nodesRef = useRef(nodes);

  useEffect(() => {
    panRef.current = { x: panX, y: panY };
    applyWorldTransform();
  }, [panX, panY, applyWorldTransform]);
  useEffect(() => {
    zoomRef.current = zoom;
    applyWorldTransform();
  }, [zoom, applyWorldTransform]);
  useEffect(() => {
    draftRef.current = draftConnection;
  }, [draftConnection]);
  useEffect(() => {
    onUpdateRef.current = onUpdateNodePosition;
  }, [onUpdateNodePosition]);
  useEffect(() => {
    onUpdateManyRef.current = onUpdateNodePositions;
  }, [onUpdateNodePositions]);
  useEffect(() => {
    onAddConnRef.current = onAddConnection;
  }, [onAddConnection]);
  useEffect(() => {
    onRemoveNodesRef.current = onRemoveNodes;
  }, [onRemoveNodes]);
  useEffect(() => {
    onDuplicateNodesRef.current = onDuplicateNodes;
  }, [onDuplicateNodes]);
  useEffect(() => {
    onSelectNodeRef.current = onSelectNode;
  }, [onSelectNode]);
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    selectedIdsRef.current = selectedIds;
  }, [selectedIds]);
  useEffect(() => {
    editingNameIdRef.current = editingNameId;
  }, [editingNameId]);
  useEffect(() => {
    editingNameValueRef.current = editingNameValue;
  }, [editingNameValue]);
  useEffect(() => {
    onUpdateNodeNameRef.current = onUpdateNodeName;
  }, [onUpdateNodeName]);
  useEffect(() => {
    canvasToolRef.current = canvasTool;
  }, [canvasTool]);

  /** Commit in-progress title edit (blur / click elsewhere / Enter). */
  const commitNameEdit = useCallback(() => {
    const id = editingNameIdRef.current;
    if (!id) return;
    onUpdateNodeNameRef.current?.(id, editingNameValueRef.current);
    editingNameIdRef.current = null;
    setEditingNameId(null);
  }, []);

  // Keep multi-select in sync when external selection changes
  useEffect(() => {
    if (selectedNodeId == null) {
      setSelectedIds((prev) => (prev.length ? [] : prev));
      return;
    }
    setSelectedIds((prev) => (prev.includes(selectedNodeId) ? prev : [selectedNodeId]));
  }, [selectedNodeId]);

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
      if (localGroupDelta && dragGroupIdsRef.current.includes(node.id)) {
        const start = groupStartPosRef.current[node.id];
        if (start) {
          return { x: start.x + localGroupDelta.x, y: start.y + localGroupDelta.y };
        }
      }
      return { x: node.x, y: node.y };
    },
    [draggingNodeId, localDragPos, localGroupDelta]
  );

  const scheduleGroupDelta = (dx: number, dy: number) => {
    groupDeltaRef.current = { x: dx, y: dy };
    if (rafRef.current != null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      if (groupDeltaRef.current) setLocalGroupDelta({ ...groupDeltaRef.current });
    });
  };

  const getSocketPosition = (node: WorkflowNode, socketId: string, isInput: boolean) => {
    const xy = getNodeXY(node);
    // Collapsed: dock all wires to the header mid-line
    if (node.collapsed) {
      const y = xy.y + NODE_PAD_TOP + Math.floor(NODE_HEADER_H / 2);
      return { x: isInput ? xy.x : xy.x + NODE_WIDTH, y };
    }
    if (isInput) {
      let index = node.inputs.findIndex((s) => s.id === socketId);
      if (index === -1 && socketId.startsWith("param:")) {
        // Bound param may exceed visible cap — dock near last data-in
        index = Math.max(0, node.inputs.length - 1);
      } else if (index === -1) {
        return { x: xy.x, y: xy.y + NODE_HEADER_H };
      }
      const y =
        xy.y +
        NODE_PAD_TOP +
        NODE_HEADER_H +
        index * (SOCKET_ROW_H + SOCKET_ROW_GAP) +
        SOCKET_DOT_OFFSET;
      return { x: xy.x, y };
    }
    let index = node.outputs.findIndex((s) => s.id === socketId);
    if (index === -1 && socketId.startsWith("data:")) {
      index = Math.max(0, node.outputs.length - 1);
    } else if (index === -1) {
      return { x: xy.x + NODE_WIDTH, y: xy.y + NODE_HEADER_H };
    }
    const row = node.inputs.length + index;
    const y =
      xy.y +
      NODE_PAD_TOP +
      NODE_HEADER_H +
      row * (SOCKET_ROW_H + SOCKET_ROW_GAP) +
      SOCKET_DOT_OFFSET;
    return { x: xy.x + NODE_WIDTH, y };
  };

  const flowHandleMeta = (socketId: string, sourceNode?: WorkflowNode) => {
    if (socketId === "then") return { label: "是", color: "#34C759" };
    if (socketId === "else") return { label: "否", color: "#FF5E57" };
    if (socketId === "body") return { label: "循环体", color: "#AF52DE" };
    if (socketId === "next") return { label: "下一步", color: "#4F8CFF" };
    if (socketId === "default") return { label: "默认", color: "#FF9F0A" };
    if (String(socketId || "").startsWith("case:")) {
      const out = sourceNode?.outputs?.find((s) => s.id === socketId);
      if (out?.name) return { label: out.name, color: "#30B0C7" };
      const idx = Number(String(socketId).slice(5));
      return {
        label: Number.isFinite(idx) ? `分支${idx + 1}` : "分支",
        color: "#30B0C7",
      };
    }
    return { label: socketId, color: colors.primary };
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
      if (isMarqueeRef.current && marqueeRef.current) {
        didPanOrDragRef.current = true;
        const pos = screenToCanvas(e.clientX, e.clientY);
        const next = { ...marqueeRef.current, x1: pos.x, y1: pos.y };
        marqueeRef.current = next;
        if (marqueeRafRef.current != null) return;
        marqueeRafRef.current = requestAnimationFrame(() => {
          marqueeRafRef.current = null;
          if (marqueeRef.current) setMarquee({ ...marqueeRef.current });
        });
        return;
      }
      if (isPanningRef.current) {
        didPanOrDragRef.current = true;
        panRef.current = {
          x: e.clientX - panStartRef.current.x,
          y: e.clientY - panStartRef.current.y,
        };
        applyWorldTransform();
        return;
      }
      if (draggingIdRef.current) {
        didPanOrDragRef.current = true;
        const pos = screenToCanvas(e.clientX, e.clientY);
        if (dragGroupIdsRef.current.length > 1) {
          const lead = groupStartPosRef.current[draggingIdRef.current];
          if (lead) {
            const nx = pos.x - dragOffsetRef.current.x;
            const ny = pos.y - dragOffsetRef.current.y;
            scheduleGroupDelta(nx - lead.x, ny - lead.y);
          }
        } else {
          scheduleLocalPos(pos.x - dragOffsetRef.current.x, pos.y - dragOffsetRef.current.y);
        }
        return;
      }
      if (draftRef.current) {
        const pos = screenToCanvas(e.clientX, e.clientY);
        draftRef.current = { ...draftRef.current, currentX: pos.x, currentY: pos.y };
        if (draftRafRef.current != null) return;
        draftRafRef.current = requestAnimationFrame(() => {
          draftRafRef.current = null;
          if (draftRef.current) setDraftConnection({ ...draftRef.current });
        });
      }
    };

    const onUp = () => {
      if (isPanningRef.current) {
        setPanX(panRef.current.x);
        setPanY(panRef.current.y);
      }
      if (isMarqueeRef.current && marqueeRef.current) {
        const m = marqueeRef.current;
        const minX = Math.min(m.x0, m.x1);
        const maxX = Math.max(m.x0, m.x1);
        const minY = Math.min(m.y0, m.y1);
        const maxY = Math.max(m.y0, m.y1);
        const hit = nodesRef.current
          .filter((n) => {
            const r = n.x + NODE_WIDTH;
            const b = n.y + NODE_HEIGHT_EST;
            return n.x < maxX && r > minX && n.y < maxY && b > minY;
          })
          .map((n) => n.id);
        setSelectedIds(hit);
        onSelectNodeRef.current(hit[hit.length - 1] || null);
        isMarqueeRef.current = false;
        marqueeRef.current = null;
        setMarquee(null);
      } else if (draggingIdRef.current) {
        if (dragGroupIdsRef.current.length > 1 && groupDeltaRef.current) {
          const { x: dx, y: dy } = groupDeltaRef.current;
          const updates = dragGroupIdsRef.current
            .map((id) => {
              const start = groupStartPosRef.current[id];
              if (!start) return null;
              return {
                id,
                x: Math.round((start.x + dx) / 10) * 10,
                y: Math.round((start.y + dy) / 10) * 10,
              };
            })
            .filter(Boolean) as { id: string; x: number; y: number }[];
          if (updates.length) {
            if (onUpdateManyRef.current) onUpdateManyRef.current(updates);
            else updates.forEach((u) => onUpdateRef.current(u.id, u.x, u.y));
          }
        } else if (localPosRef.current) {
          const id = draggingIdRef.current;
          const { x, y } = localPosRef.current;
          onUpdateRef.current(id, Math.round(x / 10) * 10, Math.round(y / 10) * 10);
        }
      }
      isPanningRef.current = false;
      draggingIdRef.current = null;
      dragGroupIdsRef.current = [];
      groupStartPosRef.current = {};
      localPosRef.current = null;
      groupDeltaRef.current = null;
      setDraggingNodeId(null);
      setLocalDragPos(null);
      setLocalGroupDelta(null);
      // Defer clearing draft so socket onMouseUp can still read it
      requestAnimationFrame(() => setDraftConnection(null));
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (marqueeRafRef.current != null) {
        cancelAnimationFrame(marqueeRafRef.current);
        marqueeRafRef.current = null;
      }
      if (draftRafRef.current != null) {
        cancelAnimationFrame(draftRafRef.current);
        draftRafRef.current = null;
      }
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      if (marqueeRafRef.current != null) cancelAnimationFrame(marqueeRafRef.current);
      if (draftRafRef.current != null) cancelAnimationFrame(draftRafRef.current);
    };
  }, [screenToCanvas, applyWorldTransform]);

  // Keyboard: Delete, Ctrl+C/V/Z/Y, Ctrl+A (capture so it works while Inspector buttons focused)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) {
        return;
      }
      if ((e.target as HTMLElement)?.closest?.('[role="dialog"]')) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) {
        e.preventDefault();
        useFlowStore.getState().undo();
        return;
      }
      if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) {
        e.preventDefault();
        useFlowStore.getState().redo();
        return;
      }
      if (mod && e.key.toLowerCase() === "a") {
        e.preventDefault();
        const ids = nodesRef.current.map((n) => n.id);
        setSelectedIds(ids);
        onSelectNodeRef.current(ids[ids.length - 1] || null);
        return;
      }
      if (mod && e.key.toLowerCase() === "c") {
        if (!selectedIdsRef.current.length) return;
        e.preventDefault();
        clipboardRef.current = [...selectedIdsRef.current];
        return;
      }
      if (mod && e.key.toLowerCase() === "v") {
        if (!clipboardRef.current.length || !onDuplicateNodesRef.current) return;
        e.preventDefault();
        const newIds = onDuplicateNodesRef.current(clipboardRef.current) || [];
        if (newIds.length) {
          setSelectedIds(newIds);
          onSelectNodeRef.current(newIds[newIds.length - 1]);
          clipboardRef.current = newIds;
        }
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        const ids = selectedIdsRef.current;
        if (!ids.length) return;
        e.preventDefault();
        if (onRemoveNodesRef.current) onRemoveNodesRef.current(ids);
        else ids.forEach((id) => onRemoveNode(id));
        setSelectedIds([]);
        onSelectNodeRef.current(null);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onRemoveNode]);

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
      commitNameEdit();
      startPan(e.clientX, e.clientY);
      return;
    }
    // Select tool, or Shift + left on empty: marquee select
    const wantMarquee =
      e.button === 0 &&
      isPanSurface(e.target) &&
      (e.shiftKey || canvasToolRef.current === "select");
    if (wantMarquee) {
      e.preventDefault();
      commitNameEdit();
      const pos = screenToCanvas(e.clientX, e.clientY);
      isMarqueeRef.current = true;
      didPanOrDragRef.current = false;
      const box = { x0: pos.x, y0: pos.y, x1: pos.x, y1: pos.y };
      marqueeRef.current = box;
      setMarquee(box);
      return;
    }
    // Left mouse on empty surface: pan
    if (e.button === 0 && isPanSurface(e.target)) {
      e.preventDefault();
      commitNameEdit();
      startPan(e.clientX, e.clientY);
    }
  };

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (didPanOrDragRef.current) {
      didPanOrDragRef.current = false;
      return;
    }
    if (!isPanSurface(e.target)) return;
    setSelectedIds([]);
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

  const handleAutoLayout = () => {
    if (!nodes.length) return;
    const updates = computeAutoLayout(nodes, connections);
    if (!updates.length) return;
    if (onUpdateNodePositions) {
      onUpdateNodePositions(updates);
    } else {
      for (const u of updates) onUpdateNodePosition(u.id, u.x, u.y);
    }
    // Fit after React applies positions on next frame
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        // Use laid-out coords directly (props may not have flushed yet)
        if (!canvasRef.current || !updates.length) return;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (const u of updates) {
          minX = Math.min(minX, u.x);
          minY = Math.min(minY, u.y);
          maxX = Math.max(maxX, u.x + NODE_WIDTH);
          maxY = Math.max(maxY, u.y + NODE_HEIGHT_EST);
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
      });
    });
  };

  const handleNodeDragStart = (e: React.MouseEvent, node: WorkflowNode) => {
    e.stopPropagation();
    e.preventDefault();
    // Clicking another node: save any in-progress title edit first
    if (editingNameIdRef.current && editingNameIdRef.current !== node.id) {
      commitNameEdit();
    }
    let nextSelected = selectedIdsRef.current;
    if (e.ctrlKey || e.metaKey) {
      nextSelected = nextSelected.includes(node.id)
        ? nextSelected.filter((id) => id !== node.id)
        : [...nextSelected, node.id];
      setSelectedIds(nextSelected);
      onSelectNode(nextSelected.includes(node.id) ? node.id : nextSelected[nextSelected.length - 1] || null);
    } else if (!nextSelected.includes(node.id)) {
      nextSelected = [node.id];
      setSelectedIds(nextSelected);
      onSelectNode(node.id);
    } else {
      onSelectNode(node.id);
    }

    const pos = screenToCanvas(e.clientX, e.clientY);
    const xy = getNodeXY(node);
    draggingIdRef.current = node.id;
    dragOffsetRef.current = { x: pos.x - xy.x, y: pos.y - xy.y };
    localPosRef.current = { x: xy.x, y: xy.y };

    const group =
      nextSelected.includes(node.id) && nextSelected.length > 1 ? nextSelected : [node.id];
    dragGroupIdsRef.current = group;
    groupStartPosRef.current = {};
    for (const id of group) {
      const n = nodesRef.current.find((x) => x.id === id);
      if (n) groupStartPosRef.current[id] = { x: n.x, y: n.y };
    }
    // Lead node uses local pos if solo
    if (group.length === 1) {
      setDraggingNodeId(node.id);
      setLocalDragPos({ x: xy.x, y: xy.y });
      setLocalGroupDelta(null);
    } else {
      setDraggingNodeId(node.id);
      setLocalDragPos(null);
      setLocalGroupDelta({ x: 0, y: 0 });
      groupDeltaRef.current = { x: 0, y: 0 };
    }
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
  const displayNodes = useMemo(() => {
    if (!draggingNodeId && !localGroupDelta) return nodes;
    return nodes.map((n) => {
      const xy = getNodeXY(n);
      if (xy.x !== n.x || xy.y !== n.y) return { ...n, x: xy.x, y: xy.y };
      return n;
    });
  }, [nodes, draggingNodeId, localGroupDelta, getNodeXY]);

  const nodeById = useMemo(() => {
    const m = new Map<string, WorkflowNode>();
    for (const n of displayNodes) m.set(n.id, n);
    return m;
  }, [displayNodes]);

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const isDragging = draggingNodeId != null;

  return (
    <div
      ref={canvasRef}
      onMouseDown={handleMouseDown}
      onClick={handleCanvasClick}
      onDragOver={(e) => {
        if (!onDropBlock) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }}
      onDrop={(e) => {
        if (!onDropBlock) return;
        e.preventDefault();
        // Only accept explicit Nexuz block drags — never text/plain (can be polluted)
        const blockType = e.dataTransfer.getData("application/nexuz-block");
        if (!blockType || !/^[a-z][a-z0-9_]*$/i.test(blockType)) return;
        const pos = screenToCanvas(e.clientX, e.clientY);
        onDropBlock(blockType, pos.x - NODE_WIDTH / 2, pos.y - 28);
      }}
      onAuxClick={(e) => {
        // Prevent middle-click auto-scroll chrome behavior after pan
        if (e.button === 1) e.preventDefault();
      }}
      style={{
        backgroundColor: themeMode === "light" ? "#F5F7FB" : "#0A0D14",
      }}
      className={`flex-1 relative overflow-hidden select-none ${
        canvasTool === "select"
          ? "cursor-crosshair"
          : "cursor-grab active:cursor-grabbing"
      } ${themeMode === "light" ? "bg-grid-light" : "bg-grid-dark"}`}
    >
      <div className="absolute bottom-5 left-5 z-20 flex flex-col gap-2 items-start">
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
            setPan(nx, ny);
          }}
        />
        <div
          style={{ color: colors.secondaryText }}
          className="text-xs font-mono font-bold uppercase tracking-wider bg-black/5 dark:bg-white/5 backdrop-blur-md px-2.5 py-1 rounded-lg border border-black/10 dark:border-white/10 flex items-center space-x-1.5"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
          <span>Scale: {Math.round(zoom * 100)}%</span>
          {selectedIds.length > 1 && (
            <span className="opacity-70">· {selectedIds.length} selected</span>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleAutoLayout}
          disabled={!nodes.length}
          style={{
            backgroundColor: colors.surface,
            borderColor: colors.border,
            color: colors.text,
          }}
          className="h-8 text-xs shadow-lg gap-1.5"
          title="按流程连接自动排布节点，减少连线交叉"
        >
          <Waypoints className="w-3.5 h-3.5 opacity-80" />
          整理布局
        </Button>
      </div>

      <div className="absolute top-4 left-4 z-20 flex items-center gap-2 flex-wrap max-w-[min(100%,520px)]">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowDataLinks((v) => !v)}
          style={{
            backgroundColor: colors.surface,
            borderColor: showDataLinks ? colors.primary : colors.border,
            color: showDataLinks ? colors.primary : colors.text,
          }}
          className="h-8 text-xs shadow-lg"
          title="数据请优先在右侧面板绑定；连线仅辅助显示 {{node.field}} 引用"
        >
          数据连线 {showDataLinks ? "开" : "关"}
        </Button>
        <div
          className="flex items-center rounded-md border shadow-lg overflow-hidden h-8"
          style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        >
          <button
            type="button"
            onClick={() => setCanvasTool("pan")}
            title="平移画布（空处拖动）"
            className="h-full px-2 flex items-center gap-1 text-xs"
            style={{
              color: canvasTool === "pan" ? colors.primary : colors.text,
              backgroundColor: canvasTool === "pan" ? colors.primary + "18" : "transparent",
            }}
          >
            <MousePointer2 className="w-3.5 h-3.5" />
            平移
          </button>
          <button
            type="button"
            onClick={() => setCanvasTool("select")}
            title="框选节点（空处拖动拉框；也可 Shift+拖动）"
            className="h-full px-2 flex items-center gap-1 text-xs border-l"
            style={{
              borderColor: colors.border,
              color: canvasTool === "select" ? colors.primary : colors.text,
              backgroundColor: canvasTool === "select" ? colors.primary + "18" : "transparent",
            }}
          >
            <SquareDashedMousePointer className="w-3.5 h-3.5" />
            框选
          </button>
        </div>
        {selectedIds.length > 0 ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const ids = [...selectedIdsRef.current];
              if (!ids.length) return;
              if (onRemoveNodes) onRemoveNodes(ids);
              else ids.forEach((id) => onRemoveNode(id));
              setSelectedIds([]);
              onSelectNode(null);
            }}
            style={{
              backgroundColor: colors.surface,
              borderColor: colors.border,
              color: colors.danger,
            }}
            className="h-8 text-xs shadow-lg gap-1"
            title="删除选中节点（Delete）"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除{selectedIds.length > 1 ? ` ${selectedIds.length}` : ""}
          </Button>
        ) : null}
        <span
          style={{ color: colors.secondaryText }}
          className="text-xs opacity-60 hidden md:inline"
        >
          {canvasTool === "select" ? "拖空处框选" : "Shift框选"} · Ctrl多选 · Del删除
        </span>
      </div>

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
        ref={worldLayerRef}
        style={{
          transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
          transformOrigin: "0 0",
          willChange: "transform",
        }}
        className="absolute inset-0 pointer-events-none"
      >
        {/* Loop body range frames (under nodes / wires) */}
        {loopFrames.map((frame) => {
          const accent = frame.forever ? "#FF5E57" : "#AF52DE";
          const label = frame.collapsed
            ? `循环 · ${frame.memberIds.length} 节点`
            : frame.loopName;
          return (
            <div
              key={`loop-frame-${frame.loopId}`}
              className="absolute rounded-2xl border pointer-events-none"
              style={{
                left: frame.x,
                top: frame.y,
                width: frame.width,
                height: frame.height,
                borderColor: accent + (frame.forever ? "99" : "66"),
                borderWidth: frame.forever ? 2 : 1,
                backgroundColor: accent + (themeMode === "light" ? "12" : "18"),
                boxShadow: frame.forever
                  ? "inset 0 0 0 1px rgba(255,94,87,0.15)"
                  : undefined,
              }}
            >
              <div
                className="absolute left-2 top-1 text-[10px] font-medium truncate max-w-[calc(100%-16px)]"
                style={{ color: accent }}
              >
                {label}
              </div>
            </div>
          );
        })}
        <svg
          className="absolute left-0 top-0 overflow-visible pointer-events-none"
          width={1}
          height={1}
          style={{ overflow: "visible" }}
        >
          <defs>
            <linearGradient id="connectionGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={colors.primary} stopOpacity="0.8" />
              <stop offset="100%" stopColor="#30D158" stopOpacity="0.8" />
            </linearGradient>
            <marker
              id="arrowFlow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={colors.primary} />
            </marker>
            <marker
              id="arrowThen"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#34C759" />
            </marker>
            <marker
              id="arrowElse"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#FF5E57" />
            </marker>
            <marker
              id="arrowBody"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#AF52DE" />
            </marker>
            <marker
              id="arrowData"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#AF52DE" />
            </marker>
            <marker
              id="arrowExec"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="8"
              markerHeight="8"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#30D158" />
            </marker>
          </defs>

          {connections.map((conn) => {
            const isData = conn.kind === "data";
            if (isData && !showDataLinks) return null;

            const sourceNode = nodeById.get(conn.sourceNodeId);
            const targetNode = nodeById.get(conn.targetNodeId);
            if (!sourceNode || !targetNode) return null;

            const sp = getSocketPosition(sourceNode, conn.sourceSocketId, false);
            const tp = getSocketPosition(targetNode, conn.targetSocketId, true);

            const isPathExecuting =
              !isData &&
              !isDragging &&
              execStatus === "running" &&
              (executingNodeId === sourceNode.id ||
                sourceNode.status === "running" ||
                targetNode.status === "running");

            const handleMeta = !isData ? flowHandleMeta(conn.sourceSocketId, sourceNode) : null;
            const stroke = isData
              ? conn.bindIssue === "broken"
                ? themeMode === "light"
                  ? "rgba(255, 59, 48, 0.75)"
                  : "rgba(255, 69, 58, 0.7)"
                : conn.bindIssue === "type_warn"
                  ? themeMode === "light"
                    ? "rgba(255, 149, 0, 0.7)"
                    : "rgba(255, 159, 10, 0.65)"
                  : themeMode === "light"
                    ? "rgba(175, 82, 222, 0.55)"
                    : "rgba(175, 82, 222, 0.45)"
              : isPathExecuting
                ? "url(#connectionGrad)"
                : handleMeta?.color ||
                  (themeMode === "light"
                    ? "rgba(79, 140, 255, 0.45)"
                    : "rgba(255, 255, 255, 0.15)");

            const midX = (sp.x + tp.x) / 2;
            const midY = (sp.y + tp.y) / 2;
            // Labels sit at path midpoint
            const labelX = midX;
            const labelY = midY;
            const pathD = drawBezierPath(sp.x, sp.y, tp.x, tp.y);

            const markerId = isData
              ? "arrowData"
              : isPathExecuting
                ? "arrowExec"
                : conn.sourceSocketId === "then"
                  ? "arrowThen"
                  : conn.sourceSocketId === "else"
                    ? "arrowElse"
                    : conn.sourceSocketId === "body"
                      ? "arrowBody"
                      : "arrowFlow";

            const labelW = Math.max(36, (handleMeta?.label?.length || 2) * 12 + 12);

            return (
              <g key={conn.id} className="group pointer-events-auto cursor-pointer">
                <path
                  d={pathD}
                  fill="none"
                  stroke="transparent"
                  strokeWidth="12"
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    void (async () => {
                      if (isData) {
                        await alert({
                          title: "数据连线",
                          description:
                            "数据连线由参数中的 {{node.field}} 自动生成。请在右侧 Inspector 中修改或清除引用；画布上点击连线不会删除绑定。",
                        });
                        return;
                      }
                      const ok = await confirm({
                        title: "断开连接",
                        description: "确定断开这条工作流连线？",
                        confirmText: "断开",
                        destructive: true,
                      });
                      if (ok) onRemoveConnection(conn.id);
                    })();
                  }}
                />
                <path
                  d={pathD}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={isData ? 1.5 : 2.5}
                  strokeDasharray={isData ? "6,5" : undefined}
                  markerEnd={`url(#${markerId})`}
                  className={`group-hover:stroke-red-400 ${
                    isPathExecuting ? "connection-flow" : ""
                  }`}
                  onClick={(e) => {
                    e.stopPropagation();
                    void (async () => {
                      if (isData) {
                        await alert({
                          title: "数据连线",
                          description:
                            "数据连线由参数中的 {{node.field}} 自动生成。请在右侧 Inspector 中修改或清除引用；画布上点击连线不会删除绑定。",
                        });
                        return;
                      }
                      const ok = await confirm({
                        title: "断开连接",
                        description: "确定断开这条工作流连线？",
                        confirmText: "断开",
                        destructive: true,
                      });
                      if (ok) onRemoveConnection(conn.id);
                    })();
                  }}
                />
                {isData && conn.label && (
                  <text
                    x={midX}
                    y={midY - 8}
                    textAnchor="middle"
                    fill={themeMode === "light" ? "#AF52DE" : "#C77DFF"}
                    fontSize="12px"
                    className="pointer-events-none opacity-80"
                  >
                    {conn.label}
                  </text>
                )}
                {!isData && handleMeta && (
                  <g className="pointer-events-none">
                    <rect
                      x={labelX - labelW / 2}
                      y={labelY - 10}
                      width={labelW}
                      height={16}
                      rx={4}
                      fill={themeMode === "light" ? "#FFFFFF" : "#1A2235"}
                      stroke={handleMeta.color}
                      strokeWidth="1"
                      opacity="0.95"
                    />
                    <text
                      x={labelX}
                      y={labelY + 2}
                      textAnchor="middle"
                      fill={handleMeta.color}
                      fontSize="12px"
                      fontWeight="bold"
                    >
                      {handleMeta.label}
                    </text>
                  </g>
                )}
                {!isData && (
                  <>
                    <circle
                      cx={midX}
                      cy={midY - 22}
                      r="10"
                      fill={themeMode === "light" ? "#FFF" : "#1A2235"}
                      stroke="#FF5E57"
                      strokeWidth="1.5"
                      className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none"
                    />
                    <text
                      x={midX}
                      y={midY - 19}
                      textAnchor="middle"
                      fill="#FF5E57"
                      fontSize="12px"
                      fontWeight="bold"
                      className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none"
                    >
                      ×
                    </text>
                  </>
                )}
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
            const isSelected = selectedIdSet.has(node.id) || selectedNodeId === node.id;
            const isForever = node.subType === "loop_forever";
            const isNodeRunning =
              executingNodeId === node.id || node.status === "running";
            const isAtBreakpoint =
              execStatus === "breakpoint" && executingNodeId === node.id;
            const isNodePaused =
              isAtBreakpoint || (isNodeRunning && execStatus === "paused");
            const isNodeLive = isNodeRunning && execStatus === "running";
            const hasBreakpoint =
              debugMode && (breakpoints || []).includes(node.id);
            const nodeAccentColor = isForever ? "#FF5E57" : getNodeColor(node.type);
            const xy = getNodeXY(node);
            const thisDragging =
              draggingNodeId === node.id ||
              (localGroupDelta != null && selectedIdSet.has(node.id) && dragGroupIdsRef.current.includes(node.id));

            return (
              <div
                key={node.id}
                onMouseDown={(e) => handleNodeDragStart(e, node)}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!(e.ctrlKey || e.metaKey)) {
                    if (!selectedIdSet.has(node.id) || selectedIds.length <= 1) {
                      setSelectedIds([node.id]);
                    }
                    onSelectNode(node.id);
                  }
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (!selectedIdSet.has(node.id)) {
                    setSelectedIds([node.id]);
                    onSelectNode(node.id);
                  }
                  setCtxMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
                }}
                style={{
                  left: xy.x,
                  top: xy.y,
                  width: NODE_WIDTH,
                  backgroundColor:
                    themeMode === "light"
                      ? "rgba(255, 255, 255, 0.92)"
                      : "rgba(24, 28, 43, 0.92)",
                  borderColor: isForever
                    ? "#FF5E57"
                    : (node.bindErrorCount || 0) > 0
                      ? "#FF5E57"
                    : isSelected
                      ? colors.primary
                      : themeMode === "light"
                        ? "rgba(0, 0, 0, 0.08)"
                        : "rgba(255, 255, 255, 0.06)",
                  borderWidth: isForever || (node.bindErrorCount || 0) > 0 ? 2 : undefined,
                  boxShadow: isForever
                    ? "0 0 0 3px rgba(255, 94, 87, 0.25)"
                    : isSelected
                      ? `0 0 0 2px ${colors.primary}33`
                      : "0 8px 24px rgba(0,0,0,0.12)",
                  color: colors.text,
                  ["--node-halo" as string]: isNodeLive
                    ? colors.primary || "#34d399"
                    : isNodePaused
                      ? "#f59e0b"
                      : undefined,
                  transition: thisDragging ? "none" : undefined,
                  willChange: thisDragging ? "left, top" : undefined,
                }}
                className={`absolute rounded-xl border px-2.5 py-2 pointer-events-auto flex flex-col gap-1.5 cursor-grab active:cursor-grabbing overflow-visible ${
                  thisDragging ? "" : "hover:shadow-lg"
                } ${isNodeLive ? "node-running-halo" : ""} ${
                  isNodePaused ? "node-paused-halo" : ""
                }`}
              >
                {isNodeLive ? <NodeRunningOrbit /> : null}
                {isNodePaused ? <NodePausedRing /> : null}
                {debugMode ? (
                  <button
                    type="button"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleBreakpoint?.(node.id);
                    }}
                    className="absolute -left-3 top-3 z-10 w-3.5 h-3.5 rounded-full border-2 pointer-events-auto cursor-pointer transition-colors"
                    style={{
                      borderColor: hasBreakpoint || isAtBreakpoint ? "#ef4444" : "rgba(148,163,184,0.7)",
                      backgroundColor:
                        hasBreakpoint || isAtBreakpoint
                          ? "#ef4444"
                          : themeMode === "light"
                            ? "rgba(255,255,255,0.9)"
                            : "rgba(30,35,50,0.95)",
                      boxShadow: isAtBreakpoint
                        ? "0 0 0 3px rgba(239,68,68,0.35)"
                        : undefined,
                    }}
                    title={hasBreakpoint ? "取消断点" : "设置断点"}
                  />
                ) : null}
                {isForever && (
                  <div className="absolute -top-2 left-2 px-1 py-0.5 rounded bg-rose-500 text-white text-xs font-bold tracking-wide uppercase">
                    FOREVER
                  </div>
                )}
                {(node.bindErrorCount || 0) > 0 && !isForever && (
                  <div
                    className="absolute -top-2 right-2 px-1.5 py-0.5 rounded bg-rose-500 text-white text-[10px] font-semibold"
                    title={`${node.bindErrorCount} 个绑定错误`}
                  >
                    {node.bindErrorCount} 绑定
                  </div>
                )}
                <div
                  className={`flex items-center justify-between shrink-0 ${
                    node.collapsed ? "" : "border-b border-black/10 dark:border-white/10 pb-1.5"
                  }`}
                >
                  <div className="flex items-center gap-1 truncate min-w-0 flex-1">
                    <button
                      type="button"
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleNodeCollapsed?.(node.id);
                      }}
                      className="p-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5 shrink-0"
                      style={{ color: colors.secondaryText }}
                      title={node.collapsed ? "展开节点" : "折叠节点"}
                    >
                      {node.collapsed ? (
                        <ChevronRight className="w-3 h-3" />
                      ) : (
                        <ChevronDown className="w-3 h-3" />
                      )}
                    </button>
                    <span
                      style={{
                        backgroundColor: nodeAccentColor + "1E",
                        color: nodeAccentColor,
                      }}
                      className="w-2 h-2 rounded-full shrink-0"
                    />
                    {editingNameId === node.id ? (
                      <input
                        autoFocus
                        value={editingNameValue}
                        onChange={(e) => setEditingNameValue(e.target.value)}
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => e.stopPropagation()}
                        onBlur={() => commitNameEdit()}
                        onKeyDown={(e) => {
                          e.stopPropagation();
                          if (e.key === "Enter") {
                            e.preventDefault();
                            commitNameEdit();
                          } else if (e.key === "Escape") {
                            e.preventDefault();
                            editingNameIdRef.current = null;
                            setEditingNameId(null);
                          }
                        }}
                        className="h-5 min-w-0 flex-1 rounded border border-black/15 dark:border-white/20 bg-transparent px-1 text-xs font-semibold outline-none"
                      />
                    ) : (
                      <span
                        className="font-semibold text-xs truncate cursor-text"
                        title="双击修改名称；点空白处或回车确认"
                        onDoubleClick={(e) => {
                          e.stopPropagation();
                          setEditingNameId(node.id);
                          setEditingNameValue(node.name || "");
                        }}
                      >
                        {node.name}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center shrink-0 pointer-events-auto">
                    {onRunSingleNode ? (
                      <button
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={(e) => {
                          e.stopPropagation();
                          onRunSingleNode(node.id);
                        }}
                        disabled={_isExecuting}
                        style={{ color: colors.secondaryText }}
                        className="p-0.5 rounded hover:bg-black/5 dark:hover:bg-white/5 hover:text-emerald-500 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                        title={isNodePaused || isAtBreakpoint ? "节点暂停中" : "仅运行此节点"}
                      >
                        {isNodeLive ? (
                          <Loader2 className="w-3 h-3 animate-spin text-emerald-500" />
                        ) : isNodePaused || isAtBreakpoint ? (
                          <Pause className="w-3 h-3 text-amber-500 fill-amber-500/30" />
                        ) : (
                          <Play className="w-3 h-3 fill-current" />
                        )}
                      </button>
                    ) : null}
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (onRemoveNodes) onRemoveNodes([node.id]);
                        else onRemoveNode(node.id);
                        setSelectedIds((prev) => prev.filter((id) => id !== node.id));
                      }}
                      style={{ color: colors.danger }}
                      className="p-0.5 rounded hover:bg-red-500/15 cursor-pointer"
                      title="删除节点"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {node.collapsed ? (
                  <>
                    {node.inputs.length > 0 ? (
                      <div
                        onMouseUp={(e) => handleSocketDragDrop(e, node, node.inputs[0].id)}
                        style={{
                          backgroundColor: themeMode === "light" ? "#FFFFFF" : "#111524",
                          borderColor: nodeAccentColor,
                        }}
                        className="w-3 h-3 border-2 absolute -left-[18px] top-[14px] rounded-full hover:scale-125 transition-transform cursor-crosshair z-30"
                        title="折叠中：连线接到首个入口（展开可选具体口）"
                      />
                    ) : null}
                    {node.outputs.length > 0 ? (
                      <div
                        onMouseDown={(e) => {
                          const out =
                            node.outputs.find((o) => o.id === "next") || node.outputs[0];
                          handleSocketDragStart(e, node, out.id);
                        }}
                        style={{
                          backgroundColor: nodeAccentColor,
                          borderColor: themeMode === "light" ? "#FFFFFF" : "#111524",
                        }}
                        className="w-3 h-3 border-2 absolute -right-[18px] top-[14px] rounded-full hover:scale-125 transition-transform cursor-crosshair z-30 flex items-center justify-center"
                        title="折叠中：从 next/首个出口拖出（展开可选具体口）"
                      >
                        <div className="w-1 h-1 rounded-full bg-white" />
                      </div>
                    ) : null}
                  </>
                ) : (
                  <>
                <div className="flex flex-col gap-1 relative">
                  {node.inputs.map((inp) => {
                    const isDataIn = inp.kind === "data";
                    return (
                    <div
                      key={inp.id}
                      className="flex items-center justify-start relative pointer-events-auto h-[18px]"
                    >
                      <div
                        onMouseUp={(e) => handleSocketDragDrop(e, node, inp.id)}
                        style={{
                          backgroundColor:
                            themeMode === "light" ? "#FFFFFF" : "#111524",
                          borderColor: isDataIn ? DATA_SOCKET_COLOR : nodeAccentColor,
                        }}
                        className={`w-3 h-3 border-2 absolute -left-[18px] top-[3px] flex items-center justify-center hover:scale-125 transition-transform cursor-crosshair z-30 ${
                          isDataIn ? "rounded-sm hover:bg-purple-500/30" : "rounded-full hover:bg-blue-500"
                        }`}
                        title={isDataIn ? `绑定到参数：${inp.name}` : "执行入口（可接收多个上游）"}
                      >
                        <div className={`w-1 h-1 ${isDataIn ? "rounded-sm" : "rounded-full"} bg-slate-300 dark:bg-slate-700`} />
                      </div>
                      <span
                        className={`text-xs font-medium tracking-wide pl-0.5 truncate ${
                          isDataIn ? "text-purple-500/90" : "opacity-80"
                        }`}
                      >
                        {inp.name}
                      </span>
                    </div>
                    );
                  })}

                  {node.outputs.map((out) => {
                    const isDataOut = out.kind === "data";
                    const isThen = out.id === 'then';
                    const isElse = out.id === 'else';
                    const isBody = out.id === 'body';
                    const isDefault = out.id === 'default';
                    const isCase = String(out.id || '').startsWith('case:');
                    const socketColor = isDataOut
                      ? DATA_SOCKET_COLOR
                      : isThen
                        ? '#34C759'
                        : isElse
                          ? '#FF5E57'
                          : isBody
                            ? '#AF52DE'
                            : isDefault
                              ? '#FF9F0A'
                              : isCase
                                ? '#30B0C7'
                                : nodeAccentColor;
                    return (
                      <div
                        key={out.id}
                        className="flex items-center justify-end relative pointer-events-auto h-[18px]"
                      >
                        <span
                          className={`text-xs font-semibold tracking-wide pr-0.5 truncate ${
                            isDataOut
                              ? 'text-purple-500'
                              : isThen
                                ? 'text-emerald-500'
                                : isElse
                                  ? 'text-rose-500'
                                  : isBody
                                    ? 'text-purple-400'
                                    : isDefault
                                      ? 'text-amber-500'
                                      : isCase
                                        ? 'text-cyan-600'
                                        : 'opacity-80 font-medium'
                          }`}
                        >
                          {out.name}
                        </span>
                        <div
                          onMouseDown={(e) => handleSocketDragStart(e, node, out.id)}
                          style={{
                            backgroundColor: socketColor,
                            borderColor:
                              themeMode === 'light' ? '#FFFFFF' : '#111524',
                          }}
                          className={`w-3 h-3 border-2 absolute -right-[18px] top-[3px] flex items-center justify-center hover:scale-125 transition-transform cursor-crosshair z-30 ${
                            isDataOut ? 'rounded-sm' : 'rounded-full'
                          }`}
                          title={
                            isDataOut
                              ? `拖出数据：{{${node.id}.${out.name}}}`
                              : isThen
                                ? '是 / Then — 条件成立时走此分支'
                                : isElse
                                  ? '否 / Else — 条件不成立时走此分支'
                                  : '从此拖出执行连线'
                          }
                        >
                          <div className={`w-1 h-1 ${isDataOut ? 'rounded-sm' : 'rounded-full'} bg-white`} />
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="flex flex-col gap-0.5 text-xs pt-1 border-t border-black/10 dark:border-white/10 font-mono text-slate-400 min-w-0">
                  <div className="flex items-center gap-0.5 min-w-0">
                    {node.status === "success" && (
                      <CheckCircle2 className="w-2.5 h-2.5 text-emerald-500 shrink-0" />
                    )}
                    {node.status === "error" && (
                      <AlertCircle className="w-2.5 h-2.5 text-rose-500 shrink-0" />
                    )}
                    {node.status === "running" && execStatus === "running" && (
                      <Loader2 className="w-2.5 h-2.5 text-blue-500 animate-spin shrink-0" />
                    )}
                    {(isNodePaused ||
                      (node.status === "running" && execStatus === "paused")) && (
                      <Pause className="w-2.5 h-2.5 text-amber-500 fill-amber-500/30 shrink-0" />
                    )}
                    <span className="truncate" title={node.id}>
                      {node.id}
                    </span>
                  </div>
                  <span
                    className="opacity-60 truncate pl-0 leading-tight"
                    title={node.subType}
                  >
                    {node.subType}
                  </span>
                </div>
                  </>
                )}
              </div>
            );
          })}
        </div>

        {marquee && (
          <div
            style={{
              left: Math.min(marquee.x0, marquee.x1),
              top: Math.min(marquee.y0, marquee.y1),
              width: Math.abs(marquee.x1 - marquee.x0),
              height: Math.abs(marquee.y1 - marquee.y0),
              borderColor: colors.primary,
              backgroundColor: colors.primary + "22",
            }}
            className="absolute border border-dashed pointer-events-none z-40"
          />
        )}
      </div>

      {ctxMenu ? (() => {
        const ctxNode = nodeById.get(ctxMenu.nodeId);
        if (!ctxNode) return null;
        const menuIds =
          selectedIdSet.has(ctxMenu.nodeId) && selectedIds.length > 0
            ? selectedIds
            : [ctxMenu.nodeId];
        return (
          <NodeContextMenu
            open={ctxMenu}
            onClose={() => setCtxMenu(null)}
            themeName={themeName}
            themeMode={themeMode}
            selectedIds={menuIds}
            collapsed={!!ctxNode.collapsed}
            isEntry={flowEntry === ctxMenu.nodeId}
            hasBreakpoint={(breakpoints || []).includes(ctxMenu.nodeId)}
            isExecuting={_isExecuting}
            onRunSingle={() => onRunSingleNode?.(ctxMenu.nodeId)}
            onRename={() => {
              setEditingNameId(ctxMenu.nodeId);
              setEditingNameValue(ctxNode.name || "");
            }}
            onToggleCollapse={() => {
              if (!onToggleNodeCollapsed) return;
              for (const id of menuIds) onToggleNodeCollapsed(id);
            }}
            onDuplicate={() => {
              if (!onDuplicateNodes) return;
              const newIds = onDuplicateNodes(menuIds) || [];
              if (newIds.length) {
                setSelectedIds(newIds);
                onSelectNode(newIds[newIds.length - 1]);
                clipboardRef.current = newIds;
              }
            }}
            onSetEntry={() => onSetEntry?.(ctxMenu.nodeId)}
            onToggleBreakpoint={() => {
              if (!onToggleBreakpoint) return;
              for (const id of menuIds) onToggleBreakpoint(id);
            }}
            onDelete={() => {
              if (onRemoveNodes) onRemoveNodes(menuIds);
              else menuIds.forEach((id) => onRemoveNode(id));
              setSelectedIds([]);
              onSelectNode(null);
            }}
          />
        );
      })() : null}
    </div>
  );
}

export default memo(Canvas);
