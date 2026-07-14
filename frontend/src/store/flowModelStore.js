import { create } from 'zustand';

const MAX_LOGS = 200;
const HEAVY_KEYS = new Set(['boxes', 'box', 'image', 'bitmap', 'pixels', 'raw', 'screenshot']);

function uid(prefix = 'node') {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function cloneValue(value) {
  if (value === null || typeof value !== 'object') return value;
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value);
    } catch {
      /* fall through */
    }
  }
  try {
    return JSON.parse(JSON.stringify(value));
  } catch {
    if (Array.isArray(value)) return value.map((v) => cloneValue(v));
    return { ...value };
  }
}

/** Slim runtime values kept in UI store / logs to avoid retaining OCR polygons etc. */
function summarizeRuntimeValue(value, depth = 0, key = null) {
  if (depth >= 4) return '…';
  if (key && HEAVY_KEYS.has(String(key).toLowerCase())) {
    if (Array.isArray(value)) return { _omitted: 'boxes', count: value.length };
    return value == null ? value : { _omitted: key };
  }
  if (value == null || typeof value === 'boolean' || typeof value === 'number') return value;
  if (typeof value === 'string') {
    return value.length > 240 ? `${value.slice(0, 240)}…(+${value.length - 240})` : value;
  }
  if (Array.isArray(value)) {
    const head = value.slice(0, 24).map((v) => summarizeRuntimeValue(v, depth + 1));
    if (value.length > 24) head.push(`…(+${value.length - 24})`);
    return head;
  }
  if (typeof value === 'object') {
    const out = {};
    const entries = Object.entries(value);
    for (let i = 0; i < entries.length; i++) {
      if (i >= 40) {
        out['…'] = `+${entries.length - 40} keys`;
        break;
      }
      const [k, v] = entries[i];
      out[k] = summarizeRuntimeValue(v, depth + 1, k);
    }
    return out;
  }
  return String(value).slice(0, 240);
}

function summarizeDetail(detail) {
  if (detail == null) return detail;
  if (typeof detail === 'string') return summarizeRuntimeValue(detail);
  if (typeof detail === 'object') return summarizeRuntimeValue(detail);
  return detail;
}

function defaultParams(schema) {
  const params = {};
  for (const input of schema?.inputs || []) {
    if (input.default !== undefined) {
      params[input.name] =
        Array.isArray(input.default) || (input.default && typeof input.default === 'object')
          ? cloneValue(input.default)
          : input.default;
      continue;
    }
    if (input.type === 'number') params[input.name] = 0;
    else if (input.type === 'keys' || input.type === 'cases' || input.type === 'condition_list')
      params[input.name] = [];
    else if (input.type === 'logic_tree')
      params[input.name] =
        input.default && typeof input.default === 'object'
          ? cloneValue(input.default)
          : {
              kind: 'group',
              id: 'root',
              op: 'and',
              not: false,
              children: [{ kind: 'expr', id: 'c0', expression: '', not: false, label: '' }],
            };
    else if (input.type === 'keymap') params[input.name] = {};
    else params[input.name] = '';
  }
  return params;
}

function createEmptyFlow() {
  return {
    flow_id: uid('flow'),
    name: '未命名流程',
    version: 1,
    variables: {},
    nodes: {},
    entry: null,
  };
}

function loadHideWindowOnRecord() {
  try {
    const v = localStorage.getItem('nexuz.hideWindowOnRecord');
    // Default OFF: keep window visible so users can click「停止录制」
    if (v === null) return false;
    return v === '1' || v === 'true';
  } catch {
    return false;
  }
}

function loadDefaultCaptureMode() {
  try {
    const v = localStorage.getItem('nexuz.defaultCaptureMode');
    if (v === 'frida_ui' || v === 'coord') return v;
    return 'coord';
  } catch {
    return 'coord';
  }
}

function loadTheme() {
  try {
    return {
      themeName: localStorage.getItem('nexuz.themeName') || 'Ocean',
      themeMode: localStorage.getItem('nexuz.themeMode') || 'dark',
    };
  } catch {
    return { themeName: 'Ocean', themeMode: 'dark' };
  }
}

const initialTheme = loadTheme();

export const useFlowStore = create((set, get) => ({
  flow: createEmptyFlow(),
  schemas: [],
  schemaMap: {},
  selectedNodeId: null,
  viewMode: 'canvas', // canvas | code | settings
  bridgeReady: false,
  filePath: null,

  // theme (CanvasFlow)
  themeName: initialTheme.themeName,
  themeMode: initialTheme.themeMode,

  // app settings
  hideWindowOnRecord: loadHideWindowOnRecord(),
  defaultCaptureMode: loadDefaultCaptureMode(),

  // run history for sidebar
  runHistory: [],

  // execution
  execStatus: 'idle', // idle | running | paused | stopping
  execNodeId: null,
  execNodeStates: {}, // id -> running|done|error
  logs: [],

  setHideWindowOnRecord: (hideWindowOnRecord) => {
    try {
      localStorage.setItem('nexuz.hideWindowOnRecord', hideWindowOnRecord ? '1' : '0');
    } catch {
      /* ignore */
    }
    set({ hideWindowOnRecord: !!hideWindowOnRecord });
  },

  setDefaultCaptureMode: (defaultCaptureMode) => {
    const mode = defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
    try {
      localStorage.setItem('nexuz.defaultCaptureMode', mode);
    } catch {
      /* ignore */
    }
    set({ defaultCaptureMode: mode });
  },

  /** Force all click nodes to use the given capture_mode */
  syncAllClickCaptureModes: (mode) =>
    set((state) => {
      const m = mode === 'frida_ui' ? 'frida_ui' : 'coord';
      const nodes = { ...state.flow.nodes };
      let changed = false;
      for (const [id, node] of Object.entries(nodes)) {
        if (node?.type !== 'click') continue;
        const prev = node.params?.capture_mode;
        if (prev === m) continue;
        changed = true;
        nodes[id] = {
          ...node,
          params: { ...(node.params || {}), capture_mode: m },
        };
      }
      if (!changed) return state;
      return { flow: { ...state.flow, nodes } };
    }),

  setThemeName: (themeName) => {
    set({ themeName });
    const persist = () => {
      try {
        localStorage.setItem('nexuz.themeName', themeName);
      } catch {
        /* ignore */
      }
    };
    if (typeof requestIdleCallback === 'function') requestIdleCallback(persist);
    else setTimeout(persist, 0);
  },

  setThemeMode: (themeMode) => {
    set({ themeMode });
    const persist = () => {
      try {
        localStorage.setItem('nexuz.themeMode', themeMode);
      } catch {
        /* ignore */
      }
    };
    if (typeof requestIdleCallback === 'function') requestIdleCallback(persist);
    else setTimeout(persist, 0);
  },

  clearRunHistory: () => set({ runHistory: [] }),
  pushRunHistory: (item) =>
    set((state) => ({
      runHistory: [item, ...state.runHistory].slice(0, 50),
    })),

  setBridgeReady: (v) => set({ bridgeReady: v }),
  setSchemas: (schemas) => {
    const schemaMap = {};
    for (const s of schemas) schemaMap[s.type] = s;
    set({ schemas, schemaMap });
  },

  setViewMode: (viewMode) => set({ viewMode }),
  selectNode: (selectedNodeId) => set({ selectedNodeId }),

  setFlow: (flow, filePath = undefined) =>
    set((state) => ({
      flow: {
        ...createEmptyFlow(),
        ...flow,
        nodes: flow.nodes || {},
      },
      selectedNodeId: null,
      filePath: filePath === undefined ? state.filePath : filePath,
      execNodeStates: {},
      execNodeId: null,
    })),

  updateFlowMeta: (patch) =>
    set((state) => ({
      flow: { ...state.flow, ...patch },
    })),

  setVariable: (name, value) =>
    set((state) => {
      const key = String(name || '').trim();
      if (!key) return state;
      const variables = { ...(state.flow.variables || {}), [key]: value };
      return { flow: { ...state.flow, variables } };
    }),

  deleteVariable: (name) =>
    set((state) => {
      const variables = { ...(state.flow.variables || {}) };
      delete variables[name];
      delete variables[String(name).replace(/^\$/, '')];
      delete variables[`$${String(name).replace(/^\$/, '')}`];
      return { flow: { ...state.flow, variables } };
    }),

  renameVariable: (oldName, newName) =>
    set((state) => {
      const from = String(oldName || '').trim();
      const to = String(newName || '').trim();
      if (!from || !to || from === to) return state;
      const variables = { ...(state.flow.variables || {}) };
      if (!(from in variables)) return state;
      variables[to] = variables[from];
      delete variables[from];
      return { flow: { ...state.flow, variables } };
    }),

  addNodeFromSchema: (type, position = { x: 120, y: 120 }) => {
    const schema = get().schemaMap[type];
    if (!schema) return null;
    const id = uid('node');
    const params = defaultParams(schema);
    if (type === 'click') {
      const mode = get().defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
      params.capture_mode = mode;
    }
    const node = {
      type,
      params,
      next: null,
      position,
    };
    if (['if_condition', 'if_color_match', 'if_text_contains'].includes(type)) {
      node.then = null;
      node.else = null;
      delete node.next;
    }
    if (['loop_n', 'loop_while', 'loop_forever'].includes(type)) {
      node.body = null;
      node.next = null;
    }
    set((state) => {
      const nodes = { ...state.flow.nodes, [id]: node };
      const entry = state.flow.entry || id;
      return {
        flow: { ...state.flow, nodes, entry },
        selectedNodeId: id,
      };
    });
    return id;
  },

  appendRecordedNodes: (recorded) => {
    if (!recorded?.length) return;
    set((state) => {
      const nodes = { ...state.flow.nodes };
      let lastId = null;
      // find a tail from entry for chaining, or just set entry
      const existingIds = Object.keys(nodes);
      if (!state.flow.entry && recorded[0]) {
        // will set entry to first
      } else if (state.flow.entry) {
        // find node with no next
        for (const [id, n] of Object.entries(nodes)) {
          if (!n.next && !n.then && !n.body) lastId = id;
        }
        if (!lastId) lastId = existingIds[existingIds.length - 1] || null;
      }

      let x = 80;
      let y = 80 + existingIds.length * 70;
      let firstId = null;
      let prevId = null;
      for (const item of recorded) {
        const id = item.id || uid('node');
        if (!firstId) firstId = id;
        nodes[id] = {
          type: item.type,
          params: item.params || {},
          next: null,
          position: { x, y },
        };
        x += 40;
        y += 90;
        if (prevId) nodes[prevId].next = id;
        prevId = id;
      }
      if (lastId && nodes[lastId] && firstId) {
        nodes[lastId] = { ...nodes[lastId], next: firstId };
      }
      return {
        flow: {
          ...state.flow,
          nodes,
          entry: state.flow.entry || firstId,
        },
      };
    });
  },

  updateNodeParams: (nodeId, params) =>
    set((state) => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const nextParams = { ...node.params, ...params };
      const patch = { ...node, params: nextParams };
      // Keep switch default ↔ next in sync for legacy interpreter fallback
      if (node.type === 'switch' && Object.prototype.hasOwnProperty.call(params, 'default')) {
        patch.next = params.default || null;
      }
      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: patch,
          },
        },
      };
    }),

  updateNodeName: (nodeId, name) =>
    set((state) => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const raw = String(name ?? '');
      const nextNode = { ...node };
      if (raw.trim()) nextNode.name = raw;
      else delete nextNode.name;
      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: nextNode,
          },
        },
      };
    }),

  updateNodePosition: (nodeId, position) =>
    set((state) => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: { ...node, position },
          },
        },
      };
    }),

  updateNodePositions: (updates) =>
    set((state) => {
      if (!updates?.length) return state;
      const nodes = { ...state.flow.nodes };
      for (const u of updates) {
        const node = nodes[u.id];
        if (!node) continue;
        nodes[u.id] = { ...node, position: { x: u.x, y: u.y } };
      }
      return { flow: { ...state.flow, nodes } };
    }),

  setNodeLink: (sourceId, handle, targetId) =>
    set((state) => {
      const node = state.flow.nodes[sourceId];
      if (!node) return state;
      if (sourceId === targetId) return state; // 禁止自环
      const field = handle || 'next';

      // switch case:/default → write params (canvas ↔ inspector dual binding)
      if (node.type === 'switch' && String(field).startsWith('case:')) {
        const idx = Number(String(field).slice(5));
        if (!Number.isFinite(idx) || idx < 0) return state;
        const cases = Array.isArray(node.params?.cases)
          ? node.params.cases.map((c) => ({ ...c }))
          : [];
        while (cases.length <= idx) cases.push({ name: '', value: '', node_id: '' });
        cases[idx] = {
          ...cases[idx],
          name: cases[idx].name || '',
          value: cases[idx].value || '',
          node_id: targetId,
        };
        return {
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                params: { ...(node.params || {}), cases },
              },
            },
          },
        };
      }
      if (node.type === 'switch' && field === 'default') {
        return {
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                next: targetId,
                params: { ...(node.params || {}), default: targetId },
              },
            },
          },
        };
      }

      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [sourceId]: { ...node, [field]: targetId },
          },
        },
      };
    }),

  removeNodeLink: (sourceId, handle) =>
    set((state) => {
      const node = state.flow.nodes[sourceId];
      if (!node) return state;
      const field = handle || 'next';

      if (node.type === 'switch' && String(field).startsWith('case:')) {
        const idx = Number(String(field).slice(5));
        if (!Number.isFinite(idx) || idx < 0) return state;
        const cases = Array.isArray(node.params?.cases)
          ? node.params.cases.map((c) => ({ ...c }))
          : [];
        if (cases[idx]) cases[idx] = { ...cases[idx], node_id: '' };
        return {
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                params: { ...(node.params || {}), cases },
              },
            },
          },
        };
      }
      if (node.type === 'switch' && field === 'default') {
        return {
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                next: null,
                params: { ...(node.params || {}), default: '' },
              },
            },
          },
        };
      }

      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [sourceId]: { ...node, [field]: null },
          },
        },
      };
    }),

  deleteNodes: (ids) =>
    set((state) => {
      const idSet = new Set(ids);
      const nodes = { ...state.flow.nodes };
      for (const id of idSet) delete nodes[id];
      for (const n of Object.values(nodes)) {
        for (const key of ['next', 'then', 'else', 'body']) {
          if (n[key] && idSet.has(n[key])) n[key] = null;
        }
        // Clear switch case / default refs pointing at deleted nodes
        if (n.type === 'switch' && n.params) {
          const params = { ...n.params };
          if (Array.isArray(params.cases)) {
            params.cases = params.cases.map((c) =>
              c?.node_id && idSet.has(c.node_id) ? { ...c, node_id: '' } : c,
            );
          }
          if (params.default && idSet.has(params.default)) params.default = '';
          n.params = params;
        }
      }
      let entry = state.flow.entry;
      if (entry && idSet.has(entry)) {
        entry = Object.keys(nodes)[0] || null;
      }
      return {
        flow: { ...state.flow, nodes, entry },
        selectedNodeId: idSet.has(state.selectedNodeId) ? null : state.selectedNodeId,
      };
    }),

  duplicateNodes: (ids, offset = { x: 40, y: 40 }) => {
    if (!ids?.length) return [];
    const state = get();
    const srcNodes = state.flow.nodes;
    const idMap = {};
    for (const id of ids) {
      if (!srcNodes[id]) continue;
      idMap[id] = `node_${Math.random().toString(36).slice(2, 10)}`;
    }
    const mappedIds = Object.keys(idMap);
    if (!mappedIds.length) return [];

    const remap = (v) => (v && idMap[v] ? idMap[v] : v && mappedIds.includes(v) ? null : v);

    set((s) => {
      const nodes = { ...s.flow.nodes };
      for (const oldId of mappedIds) {
        const src = srcNodes[oldId];
        const newId = idMap[oldId];
        const pos = src.position || { x: 100, y: 100 };
        const copy = {
          ...cloneValue(src),
          position: { x: pos.x + offset.x, y: pos.y + offset.y },
        };
        for (const key of ['next', 'then', 'else', 'body']) {
          if (copy[key]) copy[key] = idMap[copy[key]] || null;
        }
        if (copy.type === 'switch' && copy.params) {
          const params = { ...copy.params };
          if (Array.isArray(params.cases)) {
            params.cases = params.cases.map((c) => ({
              ...c,
              node_id: c?.node_id && idMap[c.node_id] ? idMap[c.node_id] : c?.node_id || '',
            }));
          }
          if (params.default && idMap[params.default]) {
            params.default = idMap[params.default];
          }
          copy.params = params;
        }
        nodes[newId] = copy;
      }
      return {
        flow: { ...s.flow, nodes },
        selectedNodeId: idMap[ids[ids.length - 1]] || s.selectedNodeId,
      };
    });
    return mappedIds.map((id) => idMap[id]);
  },

  setEntry: (entry) =>
    set((state) => ({
      flow: { ...state.flow, entry },
    })),

  // execution UI
  nodeOutputs: {}, // nodeId -> last summarized result (UI only)
  clearLogs: () => set({ logs: [] }),
  appendLog: (entry) =>
    set((state) => ({
      logs: [
        ...state.logs.slice(-(MAX_LOGS - 1)),
        {
          ...entry,
          detail: entry.detail !== undefined ? summarizeDetail(entry.detail) : undefined,
          ts: Date.now(),
        },
      ],
    })),
  onRuntimeEvent: (event, payload) => {
    const appendLog = get().appendLog;
    if (event === 'node_start') {
      set((state) => ({
        // Don't clobber pause/stopping if a late event races the control channel.
        execStatus:
          state.execStatus === 'paused' || state.execStatus === 'stopping'
            ? state.execStatus
            : 'running',
        execNodeId: payload.node_id,
        execNodeStates: { ...state.execNodeStates, [payload.node_id]: 'running' },
      }));
      appendLog({
        level: 'info',
        nodeId: payload.node_id,
        message: `▶ [${payload.node_id}] ${payload.type}`,
        detail: summarizeDetail(payload.params),
      });
    } else if (event === 'node_end') {
      const result = summarizeDetail(payload.result || {}) || {};
      const nid = payload.node_id;
      set((state) => {
        // Interrupted mid-node: leave idle — flow_stopped/finished clears UI; don't paint error.
        if (payload.stopped) {
          const next = { ...state.execNodeStates };
          delete next[nid];
          return { execNodeStates: next };
        }
        return {
          execNodeStates: {
            ...state.execNodeStates,
            [nid]: payload.ok ? 'done' : 'error',
          },
          nodeOutputs: payload.ok
            ? { ...state.nodeOutputs, [nid]: result }
            : state.nodeOutputs,
        };
      });
      let msg = payload.ok
        ? `✓ [${nid}] ${payload.elapsed_ms}ms`
        : payload.stopped
          ? `■ [${nid}] 已停止`
          : `✗ [${nid}]: ${payload.error}`;
      if (payload.ok && payload.type === 'ocr_recognize') {
        const t = result.text;
        msg =
          t !== undefined && t !== ''
            ? `✓ [${nid}] OCR 识别到: ${String(t).slice(0, 120)}`
            : `✓ [${nid}] OCR 完成但未识别到文字（请确认已框选区域且区域内有清晰文字）`;
      }
      if (payload.ok && payload.type === 'if_text_contains') {
        msg = `✓ [${nid}] 文字匹配 ${result.matched ? '成立' : '不成立'} · 实际: ${String(result.actual_text || '').slice(0, 80)}`;
      }
      if (payload.ok && payload.type === 'color_detect' && result.color) {
        msg = `✓ [${nid}] 取色: ${result.color}`;
      }
      if (payload.ok && payload.type === 'switch') {
        msg = `✓ [${nid}] 判断值=${JSON.stringify(result.value)} · ${payload.elapsed_ms}ms`;
      }
      appendLog({
        level: payload.ok ? 'ok' : payload.stopped ? 'warn' : 'error',
        nodeId: nid,
        message: msg,
        detail: payload.ok ? result : summarizeDetail(payload.error),
      });
    } else if (event === 'flow_paused') {
      set({ execStatus: 'paused' });
      appendLog({ level: 'warn', message: '流程已暂停' });
    } else if (event === 'flow_resumed') {
      set({ execStatus: 'running' });
      appendLog({ level: 'info', message: '流程已继续' });
    } else if (event === 'flow_stopping') {
      set({ execStatus: 'stopping' });
      appendLog({ level: 'warn', message: '正在停止流程…' });
    } else if (event === 'flow_stopped') {
      // Backend still finishing the worker thread — keep Stop/busy until flow_finished.
      set((state) => ({
        execStatus: state.execStatus === 'idle' ? 'idle' : 'stopping',
      }));
      // Avoid duplicate log if flow_stopping already arrived
      if (get().logs.slice(-1)[0]?.message !== '正在停止流程…') {
        appendLog({ level: 'warn', message: '正在停止流程…' });
      }
    } else if (event === 'flow_finished') {
      // Keep only the selected node's output for Inspector; drop the rest.
      set((state) => {
        const keepId = state.selectedNodeId;
        const slim =
          keepId && state.nodeOutputs[keepId]
            ? { [keepId]: state.nodeOutputs[keepId] }
            : {};
        // Drop in-flight "running" marks so nodes don't keep spinning after stop/finish.
        const nextStates = { ...state.execNodeStates };
        for (const [id, st] of Object.entries(nextStates)) {
          if (st === 'running') delete nextStates[id];
        }
        return {
          execStatus: 'idle',
          execNodeId: null,
          execNodeStates: payload.stopped ? {} : nextStates,
          nodeOutputs: slim,
        };
      });
      // flow_stopped/stopping already logged when user clicked stop; avoid duplicate.
      if (!payload.stopped) {
        appendLog({
          level: payload.ok ? 'ok' : 'error',
          message: payload.ok ? '流程执行完成' : `流程结束: ${payload.error || '失败'}`,
        });
      } else {
        appendLog({ level: 'warn', message: '流程已停止' });
      }
      get().pushRunHistory({
        id: Math.random().toString(36).slice(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        status: payload.ok ? 'completed' : payload.stopped ? 'stopped' : 'failed',
        workflowName: get().flow.name || '未命名流程',
      });
    } else if (event === 'recording_stopped') {
      if (payload?.ok && payload.nodes?.length) {
        get().appendRecordedNodes(payload.nodes);
      }
      const nodes = payload?.nodes || [];
      const clicks = nodes.filter((n) => n?.type === 'click');
      const btnCount = { left: 0, right: 0, middle: 0 };
      for (const n of clicks) {
        const b = String(n?.params?.button || 'left');
        if (b in btnCount) btnCount[b] += 1;
        else btnCount.left += 1;
      }
      const btnHint =
        clicks.length > 0
          ? `（点击 ${clicks.length}：左${btnCount.left}/右${btnCount.right}/中${btnCount.middle}）`
          : '';
      appendLog({
        level: 'ok',
        message: `快捷键停止录制，追加 ${nodes.length || 0} 个节点${btnHint}`,
      });
    } else if (event === 'log') {
      appendLog({
        level: payload?.level || 'info',
        nodeId: payload?.node_id || payload?.nodeId || undefined,
        message: payload?.node_id
          ? `[${payload.node_id}] ${payload?.message || ''}`
          : payload?.message || '',
        detail: summarizeDetail(payload?.detail),
      });
    }
  },
}));

export function flowToJson(flow) {
  return JSON.stringify(flow, null, 2);
}
