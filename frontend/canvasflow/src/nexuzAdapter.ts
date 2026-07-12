/**
 * FlowModel (Nexuz) ↔ CanvasFlow visual nodes/connections
 */
import type { WorkflowNode, NodeConnection, NodeType, NodeSocket } from './types';
import { formatNodeRef, isBindableInput, parseNodeRef } from './bindValue';

const VAR_REF = /\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*\}\}/g;

export const DATA_OUT_PREFIX = 'data:';
export const PARAM_IN_PREFIX = 'param:';

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

function flowOutputsFor(blockType: string): NodeSocket[] {
  if (['if_condition', 'if_color_match', 'if_text_contains', 'if_logic'].includes(blockType)) {
    return [
      { id: 'then', name: '是', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'else', name: '否', type: 'output', dataType: 'any', kind: 'flow' },
    ];
  }
  if (['loop_n', 'loop_while', 'loop_forever'].includes(blockType)) {
    return [
      { id: 'body', name: '循环体', type: 'output', dataType: 'any', kind: 'flow' },
      { id: 'next', name: '结束', type: 'output', dataType: 'any', kind: 'flow' },
    ];
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
  const maxParamIns = 6;
  const chosen: any[] = sorted.slice(0, maxParamIns);
  const chosenNames = new Set(chosen.map((i) => i.name));
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

  const outputs: NodeSocket[] = [...flowOutputsFor(blockType)];
  const schemaOuts: any[] = Array.isArray(schema?.outputs) ? schema.outputs : [];
  for (const out of schemaOuts) {
    if (!out?.name) continue;
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
      config: { ...(node.params || {}) },
      status,
      outputData: nodeOutputs[id] ?? null,
    });

    const links: [string, string | null | undefined][] = [
      ['next', node.next],
      ['then', node.then],
      ['else', node.else],
      ['body', node.body],
    ];
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
        sourceSocketId: `${DATA_OUT_PREFIX}${ref.field}`,
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

export function logsToText(logs: { ts?: number; level?: string; message?: string; detail?: any }[]) {
  return logs
    .map((l) => {
      const t = l.ts ? new Date(l.ts).toLocaleString() : '';
      const detail =
        l.detail !== undefined ? `\n  detail: ${typeof l.detail === 'string' ? l.detail : JSON.stringify(l.detail)}` : '';
      return `[${t}] [${l.level || 'info'}] ${l.message || ''}${detail}`;
    })
    .join('\n');
}

/** Inject defaultCaptureMode into click nodes that omit capture_mode (inherit global). */
export function applyDefaultCaptureMode(flow: any, defaultCaptureMode: string = 'coord') {
  if (!flow?.nodes || typeof flow.nodes !== 'object') return flow;
  const mode = defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
  const nodes: Record<string, any> = {};
  for (const [id, node] of Object.entries(flow.nodes)) {
    const n: any = node;
    if (n?.type === 'click') {
      const params = { ...(n.params || {}) };
      if (!params.capture_mode) params.capture_mode = mode;
      nodes[id] = { ...n, params };
    } else {
      nodes[id] = n;
    }
  }
  return { ...flow, nodes };
}

export { formatNodeRef };
