import { create } from 'zustand';

function uid(prefix = 'node') {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function defaultParams(schema) {
  const params = {};
  for (const input of schema?.inputs || []) {
    if (input.default !== undefined) {
      params[input.name] = Array.isArray(input.default)
        ? JSON.parse(JSON.stringify(input.default))
        : input.default && typeof input.default === 'object'
          ? { ...input.default }
          : input.default;
      continue;
    }
    if (input.type === 'number') params[input.name] = 0;
    else if (input.type === 'keys' || input.type === 'cases' || input.type === 'condition_list')
      params[input.name] = [];
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
  execStatus: 'idle', // idle | running | paused
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
      return {
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: { ...node, params: { ...node.params, ...params } },
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
      const field = handle || 'next';
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
          ...JSON.parse(JSON.stringify(src)),
          position: { x: pos.x + offset.x, y: pos.y + offset.y },
        };
        for (const key of ['next', 'then', 'else', 'body']) {
          if (copy[key]) copy[key] = idMap[copy[key]] || null;
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
  nodeOutputs: {}, // nodeId -> last result object
  clearLogs: () =>
    set({ logs: [], execNodeStates: {}, execNodeId: null, execStatus: 'idle', nodeOutputs: {} }),
  appendLog: (entry) =>
    set((state) => ({
      logs: [...state.logs.slice(-500), { ...entry, ts: Date.now() }],
    })),
  onRuntimeEvent: (event, payload) => {
    const appendLog = get().appendLog;
    if (event === 'node_start') {
      set((state) => ({
        execStatus: 'running',
        execNodeId: payload.node_id,
        execNodeStates: { ...state.execNodeStates, [payload.node_id]: 'running' },
      }));
      appendLog({
        level: 'info',
        message: `▶ ${payload.node_id} (${payload.type})`,
        detail: payload.params,
      });
    } else if (event === 'node_end') {
      const result = payload.result || {};
      set((state) => ({
        execNodeStates: {
          ...state.execNodeStates,
          [payload.node_id]: payload.ok ? 'done' : 'error',
        },
        nodeOutputs: payload.ok
          ? { ...state.nodeOutputs, [payload.node_id]: result }
          : state.nodeOutputs,
      }));
      let msg = payload.ok
        ? `✓ ${payload.node_id} ${payload.elapsed_ms}ms`
        : `✗ ${payload.node_id}: ${payload.error}`;
      if (payload.ok && payload.type === 'ocr_recognize') {
        const t = result.text;
        msg =
          t !== undefined && t !== ''
            ? `✓ OCR 识别到: ${String(t).slice(0, 120)}`
            : `✓ OCR 完成但未识别到文字（请确认已框选区域且区域内有清晰文字）`;
      }
      if (payload.ok && payload.type === 'if_text_contains') {
        msg = `✓ 文字匹配 ${result.matched ? '成立' : '不成立'} · 实际: ${String(result.actual_text || '').slice(0, 80)}`;
      }
      if (payload.ok && payload.type === 'color_detect' && result.color) {
        msg = `✓ 取色: ${result.color}`;
      }
      appendLog({
        level: payload.ok ? 'ok' : 'error',
        message: msg,
        detail: payload.result || payload.error,
      });
    } else if (event === 'flow_paused') {
      set({ execStatus: 'paused' });
      appendLog({ level: 'warn', message: '流程已暂停' });
    } else if (event === 'flow_resumed') {
      set({ execStatus: 'running' });
      appendLog({ level: 'info', message: '流程已继续' });
    } else if (event === 'flow_stopped') {
      set({ execStatus: 'idle', execNodeId: null });
      appendLog({ level: 'warn', message: '流程已停止' });
    } else if (event === 'flow_finished') {
      set({ execStatus: 'idle', execNodeId: null });
      appendLog({
        level: payload.ok ? 'ok' : 'error',
        message: payload.ok ? '流程执行完成' : `流程结束: ${payload.error || '失败'}`,
      });
      get().pushRunHistory({
        id: Math.random().toString(36).slice(2, 9),
        timestamp: new Date().toLocaleTimeString(),
        status: payload.ok ? 'completed' : 'failed',
        workflowName: get().flow.name || '未命名流程',
      });
    } else if (event === 'recording_stopped') {
      if (payload?.ok && payload.nodes?.length) {
        get().appendRecordedNodes(payload.nodes);
      }
      appendLog({
        level: 'ok',
        message: `快捷键停止录制，追加 ${payload?.nodes?.length || 0} 个节点`,
      });
    } else if (event === 'log') {
      appendLog({
        level: payload?.level || 'info',
        message: payload?.message || '',
        detail: payload?.detail,
      });
    }
  },
}));

export function flowToJson(flow) {
  return JSON.stringify(flow, null, 2);
}
