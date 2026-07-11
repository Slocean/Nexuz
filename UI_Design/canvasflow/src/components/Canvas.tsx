import React, { useState, useRef, useEffect } from "react";
import { 
  ZoomIn, 
  ZoomOut, 
  Maximize, 
  Plus, 
  X, 
  Settings2, 
  Trash2, 
  CheckCircle2, 
  AlertCircle, 
  Loader2 
} from "lucide-react";
import { 
  WorkflowNode, 
  NodeConnection, 
  ThemeName, 
  ThemeMode,
  NodeType
} from "../types";
import { getThemeColors } from "../theme";

interface CanvasProps {
  nodes: WorkflowNode[];
  connections: NodeConnection[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  onUpdateNodePosition: (nodeId: string, x: number, y: number) => void;
  onAddConnection: (sourceNodeId: string, sourceSocketId: string, targetNodeId: string, targetSocketId: string) => void;
  onRemoveConnection: (connectionId: string) => void;
  onRemoveNode: (nodeId: string) => void;
  onRunSingleNode: (nodeId: string) => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  isExecuting: boolean;
  executingNodeId: string | null;
}

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
  // Canvas viewport translation / scale states
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Node drag states
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });

  // Connection drafting states
  const [draftConnection, setDraftConnection] = useState<{
    sourceNodeId: string;
    sourceSocketId: string;
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
  } | null>(null);

  const canvasRef = useRef<HTMLDivElement>(null);

  const colors = getThemeColors(themeName, themeMode);

  // Width of each node card
  const NODE_WIDTH = 220;

  // Get coordinates for a specific socket
  const getSocketPosition = (node: WorkflowNode, socketId: string, isInput: boolean) => {
    const list = isInput ? node.inputs : node.outputs;
    const index = list.findIndex(s => s.id === socketId);
    if (index === -1) return { x: node.x, y: node.y };

    // Card Header is 44px, padding is 16px, items spaced by 32px
    const yOffset = 44 + 18 + index * 32;
    const xOffset = isInput ? 0 : NODE_WIDTH;

    return {
      x: node.x + xOffset,
      y: node.y + yOffset
    };
  };

  // Convert client cursor coordinates into local canvas space
  const screenToCanvas = (clientX: number, clientY: number) => {
    if (!canvasRef.current) return { x: clientX, y: clientY };
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (clientX - rect.left - panX) / zoom,
      y: (clientY - rect.top - panY) / zoom
    };
  };

  // 1. Pan Event Handlers
  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.button === 0 && e.target === canvasRef.current) {
      setIsPanning(true);
      setPanStart({ x: e.clientX - panX, y: e.clientY - panY });
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    // Handling Panning
    if (isPanning) {
      setPanX(e.clientX - panStart.x);
      setPanY(e.clientY - panStart.y);
      return;
    }

    // Handling Node Dragging
    if (draggingNodeId) {
      const pos = screenToCanvas(e.clientX, e.clientY);
      // Snap to grid of 10px
      const snappedX = Math.round((pos.x - dragOffset.x) / 10) * 10;
      const snappedY = Math.round((pos.y - dragOffset.y) / 10) * 10;
      onUpdateNodePosition(draggingNodeId, snappedX, snappedY);
      return;
    }

    // Handling connection dragging
    if (draftConnection) {
      const pos = screenToCanvas(e.clientX, e.clientY);
      setDraftConnection(prev => prev ? {
        ...prev,
        currentX: pos.x,
        currentY: pos.y
      } : null);
    }
  };

  const handleMouseUp = () => {
    setIsPanning(false);
    setDraggingNodeId(null);
    setDraftConnection(null);
  };

  // Zoom helpers
  const handleZoomIn = () => setZoom(z => Math.min(1.5, z + 0.1));
  const handleZoomOut = () => setZoom(z => Math.max(0.5, z - 0.1));
  const handleZoomReset = () => {
    setZoom(1);
    setPanX(0);
    setPanY(0);
  };

  // Node click and drag start
  const handleNodeDragStart = (e: React.MouseEvent, node: WorkflowNode) => {
    e.stopPropagation();
    onSelectNode(node.id);
    const pos = screenToCanvas(e.clientX, e.clientY);
    setDraggingNodeId(node.id);
    setDragOffset({
      x: pos.x - node.x,
      y: pos.y - node.y
    });
  };

  // Start connection drafting
  const handleSocketDragStart = (e: React.MouseEvent, node: WorkflowNode, socketId: string) => {
    e.stopPropagation();
    e.preventDefault();
    const socketPos = getSocketPosition(node, socketId, false);
    setDraftConnection({
      sourceNodeId: node.id,
      sourceSocketId: socketId,
      startX: socketPos.x,
      startY: socketPos.y,
      currentX: socketPos.x,
      currentY: socketPos.y
    });
  };

  // Drop connection on dynamic target socket
  const handleSocketDragDrop = (e: React.MouseEvent, targetNode: WorkflowNode, targetSocketId: string) => {
    e.stopPropagation();
    if (draftConnection && draftConnection.sourceNodeId !== targetNode.id) {
      onAddConnection(
        draftConnection.sourceNodeId,
        draftConnection.sourceSocketId,
        targetNode.id,
        targetSocketId
      );
    }
    setDraftConnection(null);
  };

  // Bezier path generator
  const drawBezierPath = (x1: number, y1: number, x2: number, y2: number) => {
    const horizontalDistance = Math.abs(x2 - x1);
    const offset = Math.max(80, horizontalDistance * 0.45);
    return `M ${x1} ${y1} C ${x1 + offset} ${y1}, ${x2 - offset} ${y2}, ${x2} ${y2}`;
  };

  // Connection category coloring mapper
  const getNodeColor = (type: NodeType) => {
    switch (type) {
      case "AI": return "#4F8CFF";
      case "Database": return "#34C759";
      case "HTTP": return "#AF52DE";
      case "Condition": return "#FF9500";
      case "Logic": return "#FFCC00";
      case "End": return "#FF5E57";
      default: return "#4F8CFF";
    }
  };

  return (
    <div 
      ref={canvasRef}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ 
        backgroundColor: themeMode === "light" ? "#F5F7FB" : "#0A0D14",
      }}
      className={`flex-1 relative overflow-hidden select-none cursor-grab active:cursor-grabbing ${
        themeMode === "light" ? "bg-grid-light" : "bg-grid-dark"
      }`}
    >
      {/* 1. Zoom indicator on bottom left */}
      <div 
        style={{ color: colors.secondaryText }}
        className="absolute bottom-5 left-5 text-[10px] font-mono font-bold uppercase tracking-wider bg-black/5 dark:bg-white/5 backdrop-blur-md px-2.5 py-1 rounded-lg border border-white/10 z-20 flex items-center space-x-1.5"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
        <span>Scale: {Math.round(zoom * 100)}%</span>
      </div>

      {/* 2. Floating Action Canvas Controls */}
      <div className="absolute bottom-5 right-5 z-20 flex flex-col space-y-2">
        <button
          onClick={handleZoomIn}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="p-2.5 rounded-xl border shadow-lg hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
          title="Zoom In"
        >
          <ZoomIn className="w-4 h-4 opacity-80" />
        </button>
        <button
          onClick={handleZoomOut}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="p-2.5 rounded-xl border shadow-lg hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
          title="Zoom Out"
        >
          <ZoomOut className="w-4 h-4 opacity-80" />
        </button>
        <button
          onClick={handleZoomReset}
          style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
          className="p-2.5 rounded-xl border shadow-lg hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
          title="Reset Zoom & Pan"
        >
          <Maximize className="w-4 h-4 opacity-80" />
        </button>
      </div>

      {/* 3. Scaled and Translated Canvas Container */}
      <div
        style={{
          transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
          transformOrigin: "0 0",
        }}
        className="absolute inset-0 pointer-events-none transition-transform duration-75"
      >
        {/* SVG connection lines overlay */}
        <svg className="absolute inset-0 w-[10000px] h-[10000px] overflow-visible pointer-events-auto">
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

          {/* Draw active nodes connections */}
          {connections.map((conn) => {
            const sourceNode = nodes.find(n => n.id === conn.sourceNodeId);
            const targetNode = nodes.find(n => n.id === conn.targetNodeId);
            if (!sourceNode || !targetNode) return null;

            const p1 = getSocketPosition(sourceNode, conn.sourceSocketId, false);
            const p2 = getSocketPosition(targetNode, conn.targetSocketId, true);

            const isPathExecuting = isExecuting || sourceNode.status === "running" || targetNode.status === "running";

            return (
              <g key={conn.id} className="group pointer-events-auto cursor-pointer">
                {/* Thick background path for easy clicking/hover actions */}
                <path
                  d={drawBezierPath(p1.x, p1.y, p2.x, p2.y)}
                  fill="none"
                  stroke="transparent"
                  strokeWidth="12"
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm("Do you want to disconnect this workflow socket connection?")) {
                      onRemoveConnection(conn.id);
                    }
                  }}
                />
                
                {/* Visual Glow Layer when active */}
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

                {/* Primary rendered path */}
                <path
                  d={drawBezierPath(p1.x, p1.y, p2.x, p2.y)}
                  fill="none"
                  stroke={isPathExecuting ? "url(#connectionGrad)" : (themeMode === "light" ? "rgba(79, 140, 255, 0.45)" : "rgba(255, 255, 255, 0.15)")}
                  strokeWidth="2.5"
                  className={`transition-all duration-300 group-hover:stroke-red-400 group-hover:stroke-3 ${
                    isPathExecuting ? "connection-flow" : ""
                  }`}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm("Disconnect this workflow pathway?")) {
                      onRemoveConnection(conn.id);
                    }
                  }}
                />

                {/* Disconnect indicator dot */}
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

          {/* Draw active Draft Connection while dragging */}
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

        {/* Node Cards stack container */}
        <div className="absolute inset-0 pointer-events-none">
          {nodes.map((node) => {
            const isSelected = selectedNodeId === node.id;
            const isNodeRunning = executingNodeId === node.id || node.status === "running";
            const nodeAccentColor = getNodeColor(node.type);

            return (
              <div
                key={node.id}
                onMouseDown={(e) => handleNodeDragStart(e, node)}
                onClick={(e) => { e.stopPropagation(); onSelectNode(node.id); }}
                style={{
                  left: node.x,
                  top: node.y,
                  width: NODE_WIDTH,
                  backgroundColor: themeMode === "light" ? "rgba(255, 255, 255, 0.72)" : "rgba(24, 28, 43, 0.75)",
                  borderColor: isSelected 
                    ? colors.primary 
                    : (themeMode === "light" ? "rgba(0, 0, 0, 0.08)" : "rgba(255, 255, 255, 0.06)"),
                  color: colors.text,
                }}
                className={`absolute rounded-[22px] border-1.5 backdrop-blur-2xl p-4 pointer-events-auto transition-all shadow-xl hover:shadow-2xl hover:scale-[1.01] active:scale-[0.995] flex flex-col space-y-3 cursor-grab active:cursor-grabbing ${
                  isSelected 
                    ? "ring-4 ring-offset-2 ring-offset-transparent ring-blue-500/20" 
                    : ""
                } ${
                  themeMode === "light" ? "glass-shadow-light" : "glass-shadow-dark"
                }`}
              >
                {/* Header Row */}
                <div className="flex items-center justify-between border-b border-black/5 dark:border-white/5 pb-2.5 shrink-0">
                  <div className="flex items-center space-x-2 truncate">
                    <span 
                      style={{ backgroundColor: nodeAccentColor + "1E", color: nodeAccentColor }}
                      className="w-2.5 h-2.5 rounded-full"
                    />
                    <span className="font-display font-semibold text-xs truncate max-w-[120px]">
                      {node.name}
                    </span>
                  </div>

                  {/* Node individual actions */}
                  <div className="flex items-center space-x-1 pointer-events-auto">
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); onRunSingleNode(node.id); }}
                      style={{ color: colors.secondaryText }}
                      className="p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 hover:text-emerald-500 transition-all cursor-pointer"
                      title="Run node solo"
                    >
                      <Loader2 className={`w-3 h-3 ${isNodeRunning ? "animate-spin text-emerald-500" : ""}`} />
                    </button>
                    <button
                      onMouseDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); onRemoveNode(node.id); }}
                      style={{ color: colors.danger }}
                      className="p-1 rounded-lg hover:bg-red-500/15 transition-all cursor-pointer"
                      title="Delete node"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {/* Sockets Rows */}
                <div className="flex flex-col space-y-3 relative">
                  {/* Render Input sockets on left */}
                  {node.inputs.map((inp, idx) => (
                    <div 
                      key={inp.id} 
                      className="flex items-center justify-start space-x-2 relative pointer-events-auto h-6"
                    >
                      {/* Connection socket handle */}
                      <div
                        onMouseUp={(e) => handleSocketDragDrop(e, node, inp.id)}
                        style={{ 
                          backgroundColor: themeMode === "light" ? "#FFFFFF" : "#111524",
                          borderColor: nodeAccentColor
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

                  {/* Render Output sockets on right */}
                  {node.outputs.map((out, idx) => (
                    <div 
                      key={out.id} 
                      className="flex items-center justify-end space-x-2 relative pointer-events-auto h-6"
                    >
                      <span className="text-[11px] font-medium tracking-wide opacity-80 pr-1">
                        {out.name}
                      </span>
                      {/* Connection socket handle */}
                      <div
                        onMouseDown={(e) => handleSocketDragStart(e, node, out.id)}
                        style={{ 
                          backgroundColor: nodeAccentColor,
                          borderColor: themeMode === "light" ? "#FFFFFF" : "#111524"
                        }}
                        className="w-3.5 h-3.5 rounded-full border-2 absolute -right-[23px] top-[5px] flex items-center justify-center hover:scale-125 transition-transform cursor-crosshair z-30"
                        title="Drag connection from here"
                      >
                        <div className="w-1 h-1 rounded-full bg-white" />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Status Indicator / Summary Panel */}
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
                  <span className="opacity-60 capitalize">{node.subType.replace("-", " ")}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
