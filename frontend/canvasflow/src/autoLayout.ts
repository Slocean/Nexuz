/**
 * Layered left-to-right auto-layout for flow nodes (reduces tangled edges).
 */
import type { NodeConnection, WorkflowNode } from './types';

const H_GAP = 260;
const V_GAP = 140;
const ORIGIN_X = 80;
const ORIGIN_Y = 100;

function outletRank(socketId: string) {
  const s = String(socketId || '');
  if (s === 'then') return 0;
  if (s === 'body') return 1;
  if (s === 'catch') return 2;
  if (s.startsWith('case:')) return 3;
  if (s === 'finally') return 4;
  if (s === 'next') return 5;
  if (s === 'default') return 6;
  if (s === 'else') return 7;
  return 8;
}

export function computeAutoLayout(
  nodes: WorkflowNode[],
  connections: NodeConnection[],
): { id: string; x: number; y: number }[] {
  if (!nodes.length) return [];

  const idSet = new Set(nodes.map((n) => n.id));
  const children = new Map<string, string[]>();
  const indegree = new Map<string, number>();
  for (const n of nodes) {
    children.set(n.id, []);
    indegree.set(n.id, 0);
  }

  const flowEdges = connections.filter((c) => c.kind !== 'data');
  for (const e of flowEdges) {
    if (!idSet.has(e.sourceNodeId) || !idSet.has(e.targetNodeId)) continue;
    if (e.sourceNodeId === e.targetNodeId) continue;
    const list = children.get(e.sourceNodeId)!;
    if (!list.includes(e.targetNodeId)) {
      list.push(e.targetNodeId);
      indegree.set(e.targetNodeId, (indegree.get(e.targetNodeId) || 0) + 1);
    }
  }

  for (const [src, kids] of children) {
    kids.sort((a, b) => {
      const ea = flowEdges.find((e) => e.sourceNodeId === src && e.targetNodeId === a);
      const eb = flowEdges.find((e) => e.sourceNodeId === src && e.targetNodeId === b);
      return outletRank(ea?.sourceSocketId || '') - outletRank(eb?.sourceSocketId || '');
    });
  }

  const roots = nodes.filter((n) => (indegree.get(n.id) || 0) === 0).map((n) => n.id);
  if (!roots.length) roots.push(nodes[0].id);

  // Longest-path layering (DAG-friendly); ignore edges that would deepen past n
  const layer = new Map<string, number>();
  for (const r of roots) layer.set(r, 0);

  let changed = true;
  let guard = 0;
  while (changed && guard++ < nodes.length + 2) {
    changed = false;
    for (const e of flowEdges) {
      if (!layer.has(e.sourceNodeId)) continue;
      const nextL = (layer.get(e.sourceNodeId) as number) + 1;
      if (nextL >= nodes.length) continue;
      const cur = layer.get(e.targetNodeId);
      if (cur === undefined || nextL > cur) {
        layer.set(e.targetNodeId, nextL);
        changed = true;
      }
    }
  }

  for (const n of nodes) {
    if (!layer.has(n.id)) layer.set(n.id, 0);
  }

  // Discovery order for vertical stacking
  const visitOrder = new Map<string, number>();
  let seq = 0;
  const dfs = (id: string) => {
    if (visitOrder.has(id)) return;
    visitOrder.set(id, seq++);
    for (const c of children.get(id) || []) dfs(c);
  };
  for (const r of roots) dfs(r);
  for (const n of nodes) dfs(n.id);

  const byLayer = new Map<number, string[]>();
  for (const n of nodes) {
    const L = layer.get(n.id) || 0;
    if (!byLayer.has(L)) byLayer.set(L, []);
    byLayer.get(L)!.push(n.id);
  }
  for (const ids of byLayer.values()) {
    ids.sort((a, b) => (visitOrder.get(a) || 0) - (visitOrder.get(b) || 0));
  }

  const maxLayer = Math.max(0, ...byLayer.keys());
  const updates: { id: string; x: number; y: number }[] = [];
  for (let L = 0; L <= maxLayer; L++) {
    const ids = byLayer.get(L) || [];
    ids.forEach((id, i) => {
      updates.push({
        id,
        x: ORIGIN_X + L * H_GAP,
        y: ORIGIN_Y + i * V_GAP,
      });
    });
  }
  return updates;
}
