/**
 * FlowModel (Nexuz) ↔ CanvasFlow visual nodes/connections
 */
import type { WorkflowNode, NodeConnection, NodeType, NodeSocket } from './types';
import { formatNodeRef, isBindableInput, parseNodeRef, rootFieldName } from './bindValue';

const VAR_REF = /\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\s*\}\}/g;

export const DATA_OUT_PREFIX = 'data:';
export const PARAM_IN_PREFIX = 'param:';
export const CASE_OUT_PREFIX = 'case:';
export const DEFAULT_OUT = 'default';

export function isCaseOutSocket(id: string): boolean {
  return String(id || '').startsWith(CASE_OUT_PREFIX);
}

export function caseOutIndex(id: string): number {
  const n = Number(String(id || '').slice(CASE_OUT_PREFIX.length));
  return Number.isFinite(n) ? n : -1;
}

export function isDefaultOutSocket(id: string): boolean {
  return String(id || '') === DEFAULT_OUT;
}

/** Prefer these param names when auto-binding from a data drop onto flow Input */
const BIND_PRIORITY = [
  'variable',
  'actual_text',
  'actual_color',
  'expect_text',
  'target_color',
  'x',
  'y',
  'times',
  'max_times',
  'timeout_ms',
  'text',
  'value',
];

/** Primary scalar outputs shown as canvas data ports (panel still lists all). */
const PRIMARY_DATA_OUTS = new Set([
  'found',
  'x',
  'y',
  'matched',
  'matched_text',
  'text',
  'color',
  'path',
  'ok',
  'index',
  'count',
  'confidence',
  'score',
  'elapsed_ms',
  'from_x',
  'from_y',
  'to_x',
  'to_y',
  'button',
  'width',
  'height',
  'left',
  'top',
  'actual_text',
  'registered',
  'job_id',
  'value',
]);

function isCanvasDataOut(out: { name?: string; type?: string; canvas?: boolean }): boolean {
  if (!out?.name) return false;
  if (out.canvas === false) return false;
  const t = String(out.type || 'any').toLowerCase();
  if (t === 'any' || t === 'object' || t === 'list' || t === 'dict') return false;
  if (t !== 'string' && t !== 'number' && t !== 'boolean') return false;
  // Prefer whitelist so OCR doesn't flood the node with every scalar.
  return PRIMARY_DATA_OUTS.has(String(out.name));
}

export function isDataOutSocket(id: string): boolean {
  return String(id || '').startsWith(DATA_OUT_PREFIX);
}

export function isParamInSocket(id: string): boolean {
  return String(id || '').startsWith(PARAM_IN_PREFIX);
}

export function isFlowSocket(id: string): boolean {
  return !isDataOutSocket(id) && !isParamInSocket(id);
}

export function dataOutField(id: string): string {
  return String(id || '').slice(DATA_OUT_PREFIX.length);
}

export function paramInName(id: string): string {
  return String(id || '').slice(PARAM_IN_PREFIX.length);
}

function mapDataType(t?: string): NodeSocket['dataType'] {
  if (t === 'number' || t === 'boolean' || t === 'string') return t;
  return 'any';
}

const FLOW_OUT_KEYS = ['next', 'then', 'else', 'body', 'catch', 'finally'] as const;

function flowOutputsFor(blockType: string, params?: Record<string, any>): NodeSocket[] {
  if (['if_condition', 'if_color_match', 'if_text_contains', 'if_logic'].includes(blockType)) {
    return [
      { id: 'then', name: '是', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'else', name: '否', type: 'output', dataType: 'any', kind: 'flow' },
    ];
  }
  if (['loop_n', 'loop_while', 'loop_forever', 'loop_foreach'].includes(blockType)) {
    return [
      { id: 'body', name: '循环体', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'next', name: '结束', type: 'output', dataType: 'any', kind: 'flow' },
    ];
  }
  if (blockType === 'try_catch') {
    return [
      { id: 'body', name: '尝试', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'catch', name: '捕获', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'finally', name: '收尾', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'next', name: '继续', type: 'output', dataType: 'any', kind: 'flow' },
    ];
  }
  if (blockType === 'switch') {
    const cases = Array.isArray(params?.cases) ? params.cases : [];
    const outs: NodeSocket[] = cases.map((c: any, i: number) => {
      const custom = String(c?.name ?? '').trim();
      const matchVal = String(c?.value ?? '').trim();
      const op = String(c?.op || '==').trim() || '==';
      const opLabel =
        op === 'contains' ? '包含' : op === '!=' ? '≠' : op === '==' ? '=' : op;
      const name =
        custom ||
        (matchVal ? `${opLabel} ${matchVal}` : `分支${i + 1}`);
      return {
        id: `${CASE_OUT_PREFIX}${i}`,
        name,
        type: 'output' as const,
        dataType: 'any' as const,
        kind: 'flow' as const,
      };
    });
    outs.push({
      id: DEFAULT_OUT,
      name: '默认',
      type: 'output',
      dataType: 'any',
      kind: 'flow',
    });
    return outs;
  }
  return [{ id: 'next', name: '下一步', type: 'output', dataType: 'any', kind: 'flow' }];
}

/** Bindable params currently holding a {{node.field}} ref */
function boundParamNames(params: Record<string, any> | undefined): Set<string> {
  const set = new Set<string>();
  if (!params) return set;
  for (const [k, v] of Object.entries(params)) {
    if (typeof v === 'string' && parseNodeRef(v)) set.add(k);
  }
  return set;
}

/**
 * Build visual sockets: flow ports + typed data outs (schema.outputs)
 * + capped bindable param ins for drag-to-bind.
 */
export function socketsForBlockType(
  blockType: string,
  schema?: any,
  params?: Record<string, any>,
): { inputs: NodeSocket[]; outputs: NodeSocket[] } {
  const inputs: NodeSocket[] = [
    { id: 'in', name: '入口', type: 'input', dataType: 'any', kind: 'flow' },
  ];

  const schemaInputs: any[] = Array.isArray(schema?.inputs) ? schema.inputs : [];
  const bound = boundParamNames(params);
  const candidates = schemaInputs.filter((inp) => isBindableInput(inp));

  const score = (name: string) => {
    const pri = BIND_PRIORITY.indexOf(name);
    if (bound.has(name)) return -100;
    return pri >= 0 ? pri : 50 + name.length;
  };
  const sorted = [...candidates].sort((a, b) => score(a.name) - score(b.name));
  const maxParamIns = 3;
  const chosen: any[] = sorted.slice(0, maxParamIns);
  const chosenNames = new Set(chosen.map((i) => i.name));
  // Always show already-bound params so existing data edges keep a target socket.
  for (const name of bound) {
    if (chosenNames.has(name)) continue;
    const inp = candidates.find((c) => c.name === name);
    if (inp) {
      chosen.push(inp);
      chosenNames.add(name);
    }
  }
  for (const inp of chosen) {
    inputs.push({
      id: `${PARAM_IN_PREFIX}${inp.name}`,
      name: inp.label || inp.name,
      type: 'input',
      dataType: mapDataType(inp.type),
      kind: 'data',
    });
  }

  const outputs: NodeSocket[] = [...flowOutputsFor(blockType, params)];
  const schemaOuts: any[] = Array.isArray(schema?.outputs) ? schema.outputs : [];
  for (const out of schemaOuts) {
    if (!isCanvasDataOut(out)) continue;
    outputs.push({
      id: `${DATA_OUT_PREFIX}${out.name}`,
      name: out.name,
      type: 'output',
      dataType: mapDataType(out.type),
      kind: 'data',
    });
  }

  return { inputs, outputs };
}

export function categoryToNodeType(category?: string): NodeType {
  if (category === '动作类') return 'Logic';
  if (category === '识别类') return 'HTTP';
  if (category === '控制类') return 'Condition';
  if (category === '系统类') return 'Database';
  if (category === '自定义') return 'AI';
  return 'Logic';
}

export type ParamRef = {
  sourceId: string;
  field: string;
  /** Top-level param that holds an exact {{id.field}} value */
  paramName?: string;
};

/** Collect {{node.field}} references from nested params */
export function collectParamRefs(params: any): ParamRef[] {
  const found: ParamRef[] = [];

  // Exact top-level bindings first (for editable data edges)
  if (params && typeof params === 'object' && !Array.isArray(params)) {
    for (const [key, v] of Object.entries(params)) {
      if (typeof v !== 'string') continue;
      const parsed = parseNodeRef(v);
      if (parsed) {
        found.push({ sourceId: parsed.nodeId, field: parsed.field, paramName: key });
      }
    }
  }

  const walk = (v: any, topKey?: string) => {
    if (typeof v === 'string') {
      // Skip exact whole-value refs already recorded with paramName
      if (topKey && parseNodeRef(v)) return;
      let m: RegExpExecArray | null;
      const re = new RegExp(VAR_REF.source, 'g');
      while ((m = re.exec(v))) {
        found.push({ sourceId: m[1], field: m[2], paramName: topKey });
      }
    } else if (Array.isArray(v)) {
      v.forEach((item) => walk(item, topKey));
    } else if (v && typeof v === 'object') {
      Object.entries(v).forEach(([k, val]) => walk(val, topKey ?? k));
    }
  };

  if (params && typeof params === 'object') {
    for (const [key, v] of Object.entries(params)) {
      if (typeof v === 'string' && parseNodeRef(v)) continue;
      walk(v, key);
    }
  }
  return found;
}

/** List bindable params on a target schema for picker / auto-bind */
export function listBindableParams(schema: any): { name: string; label: string; type: string }[] {
  const inputs: any[] = Array.isArray(schema?.inputs) ? schema.inputs : [];
  return inputs
    .filter((inp) => isBindableInput(inp))
    .map((inp) => ({
      name: inp.name,
      label: inp.label || inp.name,
      type: inp.type || 'string',
    }));
}

/**
 * Pick best target param when dropping a data out onto flow Input.
 * Prefers name match with source field, then type, then BIND_PRIORITY.
 */
export function pickBestBindParam(
  schema: any,
  sourceField: string,
  sourceDataType?: string,
): string | null {
  const params = listBindableParams(schema);
  if (!params.length) return null;

  const exact = params.find((p) => p.name === sourceField);
  if (exact) return exact.name;

  const aliases: Record<string, string[]> = {
    text: ['actual_text', 'expect_text', 'variable'],
    color: ['actual_color', 'target_color'],
    matched: ['variable'],
    value: ['variable', 'actual_text'],
    found: ['variable'],
    ok: ['variable'],
  };
  for (const alt of aliases[sourceField] || []) {
    const hit = params.find((p) => p.name === alt);
    if (hit) return hit.name;
  }

  if (sourceDataType && sourceDataType !== 'any') {
    const typed = params.filter((p) => p.type === sourceDataType);
    if (typed.length === 1) return typed[0].name;
    if (typed.length > 1) {
      typed.sort((a, b) => {
        const ia = BIND_PRIORITY.indexOf(a.name);
        const ib = BIND_PRIORITY.indexOf(b.name);
        return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
      });
      return typed[0].name;
    }
  }

  params.sort((a, b) => {
    const ia = BIND_PRIORITY.indexOf(a.name);
    const ib = BIND_PRIORITY.indexOf(b.name);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return params[0]?.name ?? null;
}

/** Flow out-edge targets from a model node (next/then/else/body/catch/finally/switch). */
export function flowOutTargets(node: any): string[] {
  if (!node || typeof node !== 'object') return [];
  const out: string[] = [];
  for (const k of FLOW_OUT_KEYS) {
    const v = node[k];
    if (v) out.push(String(v));
  }
  if (node.type === 'switch' && node.params) {
    if (node.params.default) out.push(String(node.params.default));
    const cases = Array.isArray(node.params.cases) ? node.params.cases : [];
    for (const c of cases) {
      if (c?.node_id) out.push(String(c.node_id));
    }
  }
  return out;
}

/** Downstream node ids reachable via flow edges from startId (excludes startId). */
export function collectDownstreamNodeIds(flow: any, startId: string): string[] {
  const nodes = flow?.nodes || {};
  const start = String(startId || '');
  if (!start || !nodes[start]) return [];
  const visited = new Set<string>();
  const stack = [...flowOutTargets(nodes[start])];
  while (stack.length) {
    const id = String(stack.pop() || '');
    if (!id || id === start || visited.has(id) || !nodes[id]) continue;
    visited.add(id);
    for (const t of flowOutTargets(nodes[id])) stack.push(t);
  }
  return [...visited];
}

/** Clear all flow out pointers on a model node (mutates a shallow copy fields). */
export function clearedFlowOuts(node: any): any {
  if (!node) return node;
  const next = { ...node };
  for (const k of FLOW_OUT_KEYS) {
    if (k in next) next[k] = null;
  }
  if (next.type === 'switch' && next.params) {
    const params = { ...next.params };
    if (Array.isArray(params.cases)) {
      params.cases = params.cases.map((c: any) =>
        c && typeof c === 'object' ? { ...c, node_id: '' } : c,
      );
    }
    params.default = '';
    next.params = params;
    next.next = null;
  }
  return next;
}

export function flowToCanvas(
  flow: any,
  schemaMap: Record<string, any>,
  execNodeStates: Record<string, string>,
  execNodeId: string | null,
  nodeOutputs: Record<string, any> = {},
): { nodes: WorkflowNode[]; connections: NodeConnection[] } {
  const nodes: WorkflowNode[] = [];
  const connections: NodeConnection[] = [];
  const entries = Object.entries(flow?.nodes || {}) as [string, any][];
  const nodeIdSet = new Set(entries.map(([id]) => id));

  entries.forEach(([id, node], index) => {
    const schema = schemaMap[node.type] || {};
    const { inputs, outputs } = socketsForBlockType(node.type, schema, node.params);
    const pos = node.position || { x: 100 + (index % 4) * 260, y: 140 + Math.floor(index / 4) * 180 };
    let status: WorkflowNode['status'] = 'idle';
    if (execNodeId === id || execNodeStates[id] === 'running') status = 'running';
    else if (execNodeStates[id] === 'done') status = 'success';
    else if (execNodeStates[id] === 'error') status = 'error';

    nodes.push({
      id,
      type: categoryToNodeType(schema.category),
      name: node.name || schema.label || node.type,
      subType: node.type,
      x: pos.x,
      y: pos.y,
      width: 220,
      height: 140,
      inputs,
      outputs,
      // Share params by reference — Canvas/Inspector must not mutate in place.
      config: node.params || {},
      status,
      // Only attach live output for nodes that produced one (already summarized upstream).
      outputData: nodeOutputs[id] || null,
      collapsed: !!node.collapsed,
      disabled: !!node.disabled,
    });

    const links: [string, string | null | undefined][] = [
      ['next', node.next],
      ['then', node.then],
      ['else', node.else],
      ['body', node.body],
      ['catch', node.catch],
      ['finally', node.finally],
    ];
    // switch: per-case + default edges (single source of truth in params)
    if (node.type === 'switch') {
      const cases = Array.isArray(node.params?.cases) ? node.params.cases : [];
      cases.forEach((c: any, i: number) => {
        const target = c?.node_id;
        if (target && nodeIdSet.has(String(target))) {
          connections.push({
            id: `${id}-${CASE_OUT_PREFIX}${i}-${target}`,
            sourceNodeId: id,
            sourceSocketId: `${CASE_OUT_PREFIX}${i}`,
            targetNodeId: String(target),
            targetSocketId: 'in',
            kind: 'flow',
          });
        }
      });
      const defTarget = node.params?.default || node.default || node.next;
      if (defTarget && nodeIdSet.has(String(defTarget))) {
        connections.push({
          id: `${id}-${DEFAULT_OUT}-${defTarget}`,
          sourceNodeId: id,
          sourceSocketId: DEFAULT_OUT,
          targetNodeId: String(defTarget),
          targetSocketId: 'in',
          kind: 'flow',
        });
      }
    } else {
      for (const [handle, target] of links) {
        if (target) {
          connections.push({
            id: `${id}-${handle}-${target}`,
            sourceNodeId: id,
            sourceSocketId: handle,
            targetNodeId: target,
            targetSocketId: 'in',
            kind: 'flow',
          });
        }
      }
    }

    // Data links from {{source.field}} in params
    const refs = collectParamRefs(node.params);
    const seen = new Set<string>();
    for (const ref of refs) {
      if (!nodeIdSet.has(ref.sourceId) || ref.sourceId === id) continue;
      const paramKey = ref.paramName || '_';
      const key = `${ref.sourceId}.${ref.field}->${id}.${paramKey}`;
      if (seen.has(key)) continue;
      seen.add(key);
      connections.push({
        id: `data-${key}`,
        sourceNodeId: ref.sourceId,
        sourceSocketId: `${DATA_OUT_PREFIX}${rootFieldName(ref.field)}`,
        targetNodeId: id,
        targetSocketId: ref.paramName ? `${PARAM_IN_PREFIX}${ref.paramName}` : 'in',
        kind: 'data',
        label: ref.paramName ? `${ref.field}→${ref.paramName}` : ref.field,
      });
    }
  });

  return { nodes, connections };
}

export function mapLogLevel(level: string): 'info' | 'success' | 'warning' | 'error' {
  if (level === 'ok' || level === 'success') return 'success';
  if (level === 'error') return 'error';
  if (level === 'warn' || level === 'warning') return 'warning';
  return 'info';
}

export function logsToText(
  logs: {
    ts?: number;
    level?: string;
    category?: string;
    message?: string;
    detail?: any;
  }[],
) {
  return logs
    .map((l) => {
      const t = l.ts ? new Date(l.ts).toLocaleString() : '';
      const cat = l.category ? ` [${l.category}]` : '';
      const detail =
        l.detail !== undefined
          ? `\n  detail: ${typeof l.detail === 'string' ? l.detail : JSON.stringify(l.detail)}`
          : '';
      return `[${t}] [${l.level || 'info'}]${cat} ${l.message || ''}${detail}`;
    })
    .join('\n');
}

/** Inject defaultCaptureMode into click nodes that omit capture_mode (inherit global). */
export function applyDefaultCaptureMode(flow: any, defaultCaptureMode: string = 'coord') {
  if (!flow?.nodes || typeof flow.nodes !== 'object') return flow;
  const mode = defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
  let changed = false;
  const nodes: Record<string, any> = {};
  for (const [id, node] of Object.entries(flow.nodes)) {
    const n: any = node;
    if (n?.type === 'click' && !(n.params || {}).capture_mode) {
      changed = true;
      nodes[id] = { ...n, params: { ...(n.params || {}), capture_mode: mode } };
    } else {
      nodes[id] = n;
    }
  }
  return changed ? { ...flow, nodes } : flow;
}

/** Inject the global coordinate default into coordinate click nodes that omit it. */
export function applyDefaultCoordinateMode(flow: any, defaultCoordinateMode: string = 'screen_abs') {
  if (!flow?.nodes || typeof flow.nodes !== 'object') return flow;
  const mode =
    defaultCoordinateMode === 'window_client' || defaultCoordinateMode === 'virtual_norm'
      ? defaultCoordinateMode
      : 'screen_abs';
  let changed = false;
  const nodes: Record<string, any> = {};
  for (const [id, node] of Object.entries(flow.nodes)) {
    const n: any = node;
    const params = n?.params || {};
    if (
      n?.type === 'click' &&
      (params.capture_mode || 'coord') === 'coord' &&
      !params.coordinate_mode &&
      !params.coord?.coordinate_mode
    ) {
      changed = true;
      nodes[id] = { ...n, params: { ...params, coordinate_mode: mode } };
    } else {
      nodes[id] = n;
    }
  }
  return changed ? { ...flow, nodes } : flow;
}

const OUTPUT_COORD_NODE_TYPES = new Set(['ocr_recognize', 'find_image']);

/** Inject global output-coordinate default into OCR / find_image nodes that omit it. */
export function applyDefaultOutputCoordinateMode(
  flow: any,
  defaultOutputCoordinateMode: string = 'screen_abs',
) {
  if (!flow?.nodes || typeof flow.nodes !== 'object') return flow;
  const mode = defaultOutputCoordinateMode === 'region_rel' ? 'region_rel' : 'screen_abs';
  let changed = false;
  const nodes: Record<string, any> = {};
  for (const [id, node] of Object.entries(flow.nodes)) {
    const n: any = node;
    const params = n?.params || {};
    if (OUTPUT_COORD_NODE_TYPES.has(n?.type) && !params.output_coordinate_mode) {
      changed = true;
      nodes[id] = { ...n, params: { ...params, output_coordinate_mode: mode } };
    } else {
      nodes[id] = n;
    }
  }
  return changed ? { ...flow, nodes } : flow;
}

export const LOOP_BLOCK_TYPES = new Set([
  'loop_n',
  'loop_while',
  'loop_forever',
  'loop_foreach',
]);

/** Flow successors from a node (excludes data edges). */
function flowTargetsFrom(
  sourceId: string,
  connections: NodeConnection[],
): string[] {
  const out: string[] = [];
  for (const c of connections) {
    if (c.kind === 'data') continue;
    if (c.sourceNodeId === sourceId) out.push(c.targetNodeId);
  }
  return out;
}

/**
 * Collect node ids in a loop's body subgraph (reachable from ``body`` socket,
 * stopping when control returns to the loop node).
 */
export function collectLoopBodyMemberIds(
  loopId: string,
  connections: NodeConnection[],
): string[] {
  const bodyEdge = connections.find(
    (c) =>
      c.kind !== 'data' &&
      c.sourceNodeId === loopId &&
      c.sourceSocketId === 'body',
  );
  if (!bodyEdge?.targetNodeId) return [];

  const members = new Set<string>();
  const queue = [bodyEdge.targetNodeId];
  while (queue.length) {
    const id = queue.shift()!;
    if (!id || id === loopId || members.has(id)) continue;
    members.add(id);
    for (const next of flowTargetsFrom(id, connections)) {
      if (next !== loopId && !members.has(next)) queue.push(next);
    }
  }
  return [...members];
}

export type LoopBodyFrame = {
  loopId: string;
  loopName: string;
  forever: boolean;
  memberIds: string[];
  collapsed: boolean;
  x: number;
  y: number;
  width: number;
  height: number;
};

/** Bounding frames for loop bodies (canvas overlay). */
export function computeLoopBodyFrames(
  nodes: WorkflowNode[],
  connections: NodeConnection[],
  pad = 18,
  collapsedStripH = 28,
): LoopBodyFrame[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const frames: LoopBodyFrame[] = [];

  for (const node of nodes) {
    if (!LOOP_BLOCK_TYPES.has(node.subType)) continue;
    const memberIds = collectLoopBodyMemberIds(node.id, connections);
    const forever = node.subType === 'loop_forever';
    const collapsed = !!node.collapsed;

    if (collapsed || memberIds.length === 0) {
      const w = Math.max(node.width || 176, 160);
      frames.push({
        loopId: node.id,
        loopName: node.name || node.subType,
        forever,
        memberIds,
        collapsed: true,
        x: node.x - 8,
        y: node.y - collapsedStripH - 6,
        width: w + 16,
        height: collapsedStripH,
      });
      continue;
    }

    let minX = node.x;
    let minY = node.y;
    let maxX = node.x + (node.width || 176);
    let maxY = node.y + (node.height || 96);
    for (const mid of memberIds) {
      const m = byId.get(mid);
      if (!m) continue;
      const mw = m.width || 176;
      const mh = m.height || 96;
      minX = Math.min(minX, m.x);
      minY = Math.min(minY, m.y);
      maxX = Math.max(maxX, m.x + mw);
      maxY = Math.max(maxY, m.y + mh);
    }
    frames.push({
      loopId: node.id,
      loopName: node.name || node.subType,
      forever,
      memberIds,
      collapsed: false,
      x: minX - pad,
      y: minY - pad - 18,
      width: maxX - minX + pad * 2,
      height: maxY - minY + pad * 2 + 18,
    });
  }
  return frames;
}

export { formatNodeRef };
