import React, { useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { NodeConnection, ThemeMode, WorkflowNode } from '../types';

type Props = {
  nodes: WorkflowNode[];
  connections?: NodeConnection[];
  activeNodeId?: string | null;
  entryId?: string | null;
  execStatus?: string;
  themeMode?: ThemeMode;
  className?: string;
  /** Fixed height in px; ignored when fill is true. */
  height?: number;
  /** Fill parent height (for full-page flowchart view). */
  fill?: boolean;
};

type ShapeKind = 'terminator' | 'process' | 'decision' | 'loop';

type LaidOut = {
  id: string;
  label: string;
  kind: ShapeKind;
  x: number; // center
  y: number; // center
  w: number;
  h: number;
  active: boolean;
  paused: boolean;
};

type LaidEdge = {
  id: string;
  from: string;
  to: string;
  label?: string;
  color: string;
  active: boolean;
};

const PROC_W = 112;
const PROC_H = 40;
const DEC_W = 88;
const DEC_H = 56;
const TERM_W = 96;
const TERM_H = 36;
const LOOP_W = 108;
const LOOP_H = 40;
const RANK_GAP = 64;
const COL_GAP = 28;
const PAD = 28;

const IF_TYPES = new Set([
  'if_condition',
  'if_color_match',
  'if_text_contains',
  'if_logic',
  'switch',
]);
const LOOP_TYPES = new Set(['loop_n', 'loop_while', 'loop_forever', 'loop_foreach']);
const END_TYPES = new Set(['end', 'stop', 'return', 'exit']);

function shapeKind(subType: string, isEntry: boolean, isSink: boolean): ShapeKind {
  if (isEntry || isSink || END_TYPES.has(subType)) return 'terminator';
  if (IF_TYPES.has(subType)) return 'decision';
  if (LOOP_TYPES.has(subType)) return 'loop';
  return 'process';
}

function sizeOf(kind: ShapeKind) {
  if (kind === 'decision') return { w: DEC_W, h: DEC_H };
  if (kind === 'terminator') return { w: TERM_W, h: TERM_H };
  if (kind === 'loop') return { w: LOOP_W, h: LOOP_H };
  return { w: PROC_W, h: PROC_H };
}

function branchMeta(socketId: string) {
  if (socketId === 'then') return { label: '是', color: '#34C759' };
  if (socketId === 'else') return { label: '否', color: '#FF5E57' };
  if (socketId === 'body') return { label: '循环', color: '#AF52DE' };
  if (socketId === 'default') return { label: '默认', color: '#FF9F0A' };
  if (String(socketId || '').startsWith('case:')) {
    return { label: '分支', color: '#30B0C7' };
  }
  return { label: '', color: '#64748b' };
}

function truncate(s: string, n: number) {
  const t = String(s || '');
  if (t.length <= n) return t;
  return `${t.slice(0, Math.max(1, n - 1))}…`;
}

/** Classic top-down engineering flowchart layout from flow edges. */
function layoutFlowchart(
  nodes: WorkflowNode[],
  connections: NodeConnection[],
  entryId: string | null | undefined,
  activeNodeId: string | null | undefined,
  execStatus: string,
): { items: LaidOut[]; edges: LaidEdge[]; width: number; height: number } {
  if (!nodes.length) {
    return { items: [], edges: [], width: 200, height: 120 };
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const flowConns = connections.filter((c) => (c.kind || 'flow') === 'flow');

  const outs = new Map<string, { to: string; socket: string; id: string }[]>();
  const ins = new Map<string, number>();
  for (const n of nodes) {
    outs.set(n.id, []);
    ins.set(n.id, 0);
  }
  for (const c of flowConns) {
    if (!nodeById.has(c.sourceNodeId) || !nodeById.has(c.targetNodeId)) continue;
    outs.get(c.sourceNodeId)!.push({
      to: c.targetNodeId,
      socket: c.sourceSocketId,
      id: c.id,
    });
    ins.set(c.targetNodeId, (ins.get(c.targetNodeId) || 0) + 1);
  }

  let root =
    (entryId && nodeById.has(entryId) && entryId) ||
    nodes.find((n) => (ins.get(n.id) || 0) === 0)?.id ||
    nodes[0].id;

  // Longest-path rank from root (top → bottom flowchart).
  const rank = new Map<string, number>();
  const visit = (id: string, r: number, stack: Set<string>) => {
    if (stack.has(id)) return;
    const prev = rank.get(id);
    if (prev != null && prev >= r) return;
    rank.set(id, r);
    stack.add(id);
    const children = outs.get(id) || [];
    // Prefer then/body before else for more natural order
    const ordered = [...children].sort((a, b) => {
      const order = (s: string) =>
        s === 'body' ? 0 : s === 'then' ? 1 : s === 'next' ? 2 : s === 'else' ? 3 : 4;
      return order(a.socket) - order(b.socket);
    });
    for (const ch of ordered) {
      visit(ch.to, r + 1, stack);
    }
    stack.delete(id);
  };
  visit(root, 0, new Set());

  // Orphans not reached from entry
  for (const n of nodes) {
    if (!rank.has(n.id)) {
      const base = Math.max(0, ...rank.values(), 0) + 1;
      visit(n.id, base, new Set());
    }
  }

  const byRank = new Map<number, string[]>();
  for (const [id, r] of rank) {
    if (!byRank.has(r)) byRank.set(r, []);
    byRank.get(r)!.push(id);
  }

  // Within a rank: keep discovery order; for children of decisions, then left / else right
  for (const [r, ids] of byRank) {
    ids.sort((a, b) => {
      // stable-ish: prefer nodes closer to then-branch of parent
      return a.localeCompare(b);
    });
    byRank.set(r, ids);
  }

  // Assign columns with a simple barycenter pass
  const col = new Map<string, number>();
  const ranks = [...byRank.keys()].sort((a, b) => a - b);
  for (const r of ranks) {
    const ids = byRank.get(r)!;
    ids.forEach((id, i) => col.set(id, i));
  }
  // Pull nodes toward average parent column
  for (let pass = 0; pass < 3; pass++) {
    for (const r of ranks) {
      if (r === 0) continue;
      const ids = byRank.get(r)!;
      const scored = ids.map((id) => {
        const parents: number[] = [];
        for (const c of flowConns) {
          if (c.targetNodeId === id && col.has(c.sourceNodeId)) {
            let bias = col.get(c.sourceNodeId)!;
            if (c.sourceSocketId === 'then') bias -= 0.35;
            if (c.sourceSocketId === 'else') bias += 0.35;
            if (c.sourceSocketId === 'body') bias -= 0.15;
            parents.push(bias);
          }
        }
        const avg = parents.length
          ? parents.reduce((s, v) => s + v, 0) / parents.length
          : col.get(id)!;
        return { id, avg };
      });
      scored.sort((a, b) => a.avg - b.avg || a.id.localeCompare(b.id));
      scored.forEach((s, i) => col.set(s.id, i));
      byRank.set(
        r,
        scored.map((s) => s.id),
      );
    }
  }

  const maxCols = Math.max(1, ...[...byRank.values()].map((ids) => ids.length));
  const cellW = PROC_W + COL_GAP;
  const cellH = DEC_H + RANK_GAP;
  const contentW = maxCols * cellW;
  const contentH = (ranks.length || 1) * cellH;

  const items: LaidOut[] = [];
  for (const r of ranks) {
    const ids = byRank.get(r)!;
    const rowW = ids.length * cellW;
    const rowLeft = (contentW - rowW) / 2;
    ids.forEach((id, i) => {
      const n = nodeById.get(id)!;
      const sub = n.subType || String(n.type || '');
      const outCount = (outs.get(id) || []).length;
      const isEntry = id === root;
      const isSink = outCount === 0;
      const kind = shapeKind(sub, isEntry, isSink);
      const { w, h } = sizeOf(kind);
      const cx = PAD + rowLeft + i * cellW + cellW / 2;
      const cy = PAD + r * cellH + cellH / 2;
      const active = id === activeNodeId || n.status === 'running';
      const paused =
        active && (execStatus === 'paused' || execStatus === 'breakpoint');
      items.push({
        id,
        label: truncate(n.name || sub || id, 10),
        kind,
        x: cx,
        y: cy,
        w,
        h,
        active,
        paused,
      });
    });
  }

  const pos = new Map(items.map((it) => [it.id, it]));
  const edges: LaidEdge[] = [];
  for (const c of flowConns) {
    if (!pos.has(c.sourceNodeId) || !pos.has(c.targetNodeId)) continue;
    const meta = branchMeta(c.sourceSocketId);
    const active =
      c.sourceNodeId === activeNodeId || c.targetNodeId === activeNodeId;
    edges.push({
      id: c.id,
      from: c.sourceNodeId,
      to: c.targetNodeId,
      label: meta.label,
      color: meta.label ? meta.color : '#64748b',
      active,
    });
  }

  return {
    items,
    edges,
    width: contentW + PAD * 2,
    height: contentH + PAD * 2,
  };
}

/** Anchor on shape border facing the other node (for clean flowchart arrows). */
function anchor(item: LaidOut, toward: LaidOut, role: 'out' | 'in') {
  const dx = toward.x - item.x;
  const dy = toward.y - item.y;
  if (item.kind === 'decision') {
    // Diamond vertices
    if (Math.abs(dy) >= Math.abs(dx)) {
      return role === 'out'
        ? { x: item.x, y: item.y + item.h / 2 }
        : { x: item.x, y: item.y - item.h / 2 };
    }
    return role === 'out'
      ? { x: item.x + (dx >= 0 ? item.w / 2 : -item.w / 2), y: item.y }
      : { x: item.x + (dx >= 0 ? -item.w / 2 : item.w / 2), y: item.y };
  }
  // Prefer bottom→top for downward flow
  if (dy >= 0) {
    return role === 'out'
      ? { x: item.x, y: item.y + item.h / 2 }
      : { x: item.x, y: item.y - item.h / 2 };
  }
  return role === 'out'
    ? { x: item.x, y: item.y - item.h / 2 }
    : { x: item.x, y: item.y + item.h / 2 };
}

/** Orthogonal elbow path (工程流程图折线). */
function orthoPath(x1: number, y1: number, x2: number, y2: number) {
  if (Math.abs(x1 - x2) < 1) {
    return `M ${x1} ${y1} L ${x2} ${y2}`;
  }
  const midY = (y1 + y2) / 2;
  if (y2 >= y1) {
    return `M ${x1} ${y1} L ${x1} ${midY} L ${x2} ${midY} L ${x2} ${y2}`;
  }
  const midX = (x1 + x2) / 2;
  return `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${x2} ${y2}`;
}

function Shape({
  item,
  themeMode,
}: {
  item: LaidOut;
  themeMode: ThemeMode;
}) {
  const fill = themeMode === 'light' ? '#ffffff' : '#1a2030';
  const stroke = item.active
    ? item.paused
      ? '#F59E0B'
      : '#34D399'
    : themeMode === 'light'
      ? '#334155'
      : '#94a3b8';
  const text = themeMode === 'light' ? '#0f172a' : '#e2e8f0';
  const sw = item.active ? 2.4 : 1.6;
  const { x, y, w, h, kind, label } = item;

  let body: React.ReactNode = null;
  if (kind === 'terminator') {
    body = (
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx={h / 2}
        ry={h / 2}
        fill={fill}
        stroke={stroke}
        strokeWidth={sw}
      />
    );
  } else if (kind === 'decision') {
    const pts = [
      `${x},${y - h / 2}`,
      `${x + w / 2},${y}`,
      `${x},${y + h / 2}`,
      `${x - w / 2},${y}`,
    ].join(' ');
    body = (
      <polygon
        points={pts}
        fill={fill}
        stroke={stroke}
        strokeWidth={sw}
      />
    );
  } else if (kind === 'loop') {
    // Hexagon (准备/循环)
    const hw = w / 2;
    const hh = h / 2;
    const cut = 14;
    const pts = [
      `${x - hw + cut},${y - hh}`,
      `${x + hw - cut},${y - hh}`,
      `${x + hw},${y}`,
      `${x + hw - cut},${y + hh}`,
      `${x - hw + cut},${y + hh}`,
      `${x - hw},${y}`,
    ].join(' ');
    body = (
      <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />
    );
  } else {
    body = (
      <rect
        x={x - w / 2}
        y={y - h / 2}
        width={w}
        height={h}
        rx={4}
        fill={fill}
        stroke={stroke}
        strokeWidth={sw}
      />
    );
  }

  return (
    <g>
      {body}
      {item.active ? (
        <circle
          cx={x + w / 2 - 4}
          cy={y - h / 2 + 4}
          r={3.5}
          fill={item.paused ? '#F59E0B' : '#34D399'}
        />
      ) : null}
      <text
        x={x}
        y={y}
        textAnchor="middle"
        dominantBaseline="central"
        fill={text}
        fontSize={11}
        fontWeight={600}
        style={{ userSelect: 'none' }}
      >
        {label}
      </text>
    </g>
  );
}

/** Engineering flowchart thumbnail: terminator / process / decision / loop + orthogonal arrows. */
export default function FlowThumbnail({
  nodes,
  connections = [],
  activeNodeId = null,
  entryId = null,
  execStatus = 'running',
  themeMode = 'dark',
  className = '',
  height = 200,
  fill = false,
}: Props) {
  const uid = useId().replace(/:/g, '');
  const wrapRef = useRef<HTMLDivElement>(null);
  const [viewSize, setViewSize] = useState({ w: 280, h: height });

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const apply = () =>
      setViewSize({
        w: Math.max(120, Math.floor(el.clientWidth)),
        h: Math.max(80, Math.floor(el.clientHeight || height)),
      });
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, [height, fill]);

  const layout = useMemo(
    () => layoutFlowchart(nodes, connections, entryId, activeNodeId, execStatus),
    [nodes, connections, entryId, activeNodeId, execStatus],
  );

  const viewW = viewSize.w;
  const viewH = viewSize.h;
  const scale = Math.min(
    viewW / Math.max(1, layout.width),
    viewH / Math.max(1, layout.height),
  );
  const tx = (viewW - layout.width * scale) / 2;
  const ty = (viewH - layout.height * scale) / 2;

  const surface = themeMode === 'light' ? '#f8fafc' : '#0c0e14';
  const border = themeMode === 'light' ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.12)';
  const pos = useMemo(() => new Map(layout.items.map((it) => [it.id, it])), [layout.items]);
  const arrowId = `fc-arrow-${uid}`;

  return (
    <div
      ref={wrapRef}
      className={`rounded-xl border overflow-hidden select-none ${fill ? 'h-full w-full' : ''} ${className}`}
      style={{
        height: fill ? undefined : height,
        backgroundColor: surface,
        borderColor: border,
      }}
      title="流程图"
    >
      {!layout.items.length ? (
        <div className="h-full w-full flex items-center justify-center text-[12.5px] text-slate-500">
          暂无流程
        </div>
      ) : (
        <svg width={viewW} height={viewH} className="block">
          <defs>
            <marker
              id={arrowId}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path
                d="M 0 0 L 10 5 L 0 10 z"
                fill={themeMode === 'light' ? '#475569' : '#94a3b8'}
              />
            </marker>
          </defs>
          <g transform={`translate(${tx}, ${ty}) scale(${scale})`}>
            {layout.edges.map((e) => {
              const a = pos.get(e.from);
              const b = pos.get(e.to);
              if (!a || !b) return null;
              const p1 = anchor(a, b, 'out');
              const p2 = anchor(b, a, 'in');
              const d = orthoPath(p1.x, p1.y, p2.x, p2.y);
              const midX = (p1.x + p2.x) / 2;
              const midY = (p1.y + p2.y) / 2;
              const stroke = e.active ? (e.color !== '#64748b' ? e.color : '#34D399') : e.color;
              return (
                <g key={e.id}>
                  <path
                    d={d}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={e.active ? 2.2 : 1.6}
                    markerEnd={`url(#${arrowId})`}
                  />
                  {e.label ? (
                    <g transform={`translate(${midX}, ${midY})`}>
                      <rect
                        x={-12}
                        y={-8}
                        width={24}
                        height={16}
                        rx={3}
                        fill={surface}
                        stroke={e.color}
                        strokeWidth={1}
                      />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        fontSize={10}
                        fontWeight={700}
                        fill={e.color}
                      >
                        {e.label}
                      </text>
                    </g>
                  ) : null}
                </g>
              );
            })}
            {layout.items.map((item) => (
              <Shape key={item.id} item={item} themeMode={themeMode} />
            ))}
          </g>
        </svg>
      )}
    </div>
  );
}
