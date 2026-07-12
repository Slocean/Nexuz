/**
 * FlowModel (Nexuz) ↔ CanvasFlow visual nodes/connections
 */
import type { WorkflowNode, NodeConnection, NodeType, NodeSocket } from './types';

const VAR_REF = /\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*\}\}/g;

export function socketsForBlockType(blockType: string): { inputs: NodeSocket[]; outputs: NodeSocket[] } {
  const inputs: NodeSocket[] = [
    { id: 'in', name: 'Input', type: 'input', dataType: 'any' },
  ];
  if (['if_condition', 'if_color_match', 'if_text_contains'].includes(blockType)) {
    return {
      inputs,
      outputs: [
        { id: 'then', name: '是', type: 'output', dataType: 'any' },
        { id: 'else', name: '否', type: 'output', dataType: 'any' },
      ],
    };
  }
  if (['loop_n', 'loop_while', 'loop_forever'].includes(blockType)) {
    return {
      inputs,
      outputs: [
        { id: 'body', name: '循环体', type: 'output', dataType: 'any' },
        { id: 'next', name: '结束', type: 'output', dataType: 'any' },
      ],
    };
  }
  return {
    inputs,
    outputs: [{ id: 'next', name: 'Next', type: 'output', dataType: 'any' }],
  };
}

export function categoryToNodeType(category?: string): NodeType {
  if (category === '动作类') return 'Logic';
  if (category === '识别类') return 'HTTP';
  if (category === '控制类') return 'Condition';
  return 'Logic';
}

/** Collect {{node.field}} references from nested params */
export function collectParamRefs(params: any): { sourceId: string; field: string }[] {
  const found: { sourceId: string; field: string }[] = [];
  const walk = (v: any) => {
    if (typeof v === 'string') {
      let m: RegExpExecArray | null;
      const re = new RegExp(VAR_REF.source, 'g');
      while ((m = re.exec(v))) {
        found.push({ sourceId: m[1], field: m[2] });
      }
    } else if (Array.isArray(v)) {
      v.forEach(walk);
    } else if (v && typeof v === 'object') {
      Object.values(v).forEach(walk);
    }
  };
  walk(params);
  return found;
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
    const { inputs, outputs } = socketsForBlockType(node.type);
    const pos = node.position || { x: 100 + (index % 4) * 260, y: 140 + Math.floor(index / 4) * 180 };
    let status: WorkflowNode['status'] = 'idle';
    if (execNodeId === id || execNodeStates[id] === 'running') status = 'running';
    else if (execNodeStates[id] === 'done') status = 'success';
    else if (execNodeStates[id] === 'error') status = 'error';

    nodes.push({
      id,
      type: categoryToNodeType(schema.category),
      name: schema.label || node.type,
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
      const key = `${ref.sourceId}->${id}.${ref.field}`;
      if (seen.has(key)) continue;
      seen.add(key);
      connections.push({
        id: `data-${key}`,
        sourceNodeId: ref.sourceId,
        sourceSocketId: 'next',
        targetNodeId: id,
        targetSocketId: 'in',
        kind: 'data',
        label: ref.field,
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
