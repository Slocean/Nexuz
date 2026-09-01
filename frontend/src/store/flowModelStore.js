import { create } from 'zustand';

// UI memory is deliberately bounded. Complete per-run logs are streamed by
// Python to flow-scoped rolling files and exported through the bridge.
const MAX_LOGS = 500;

const LOG_CATEGORIES = ['system', 'runtime', 'audit', 'diag'];

function normalizeLogCategory(raw, fallback = 'runtime') {
  const s = String(raw || '')
    .trim()
    .toLowerCase();
  return LOG_CATEGORIES.includes(s) ? s : fallback;
}

function eventCategory(event, payload) {
  if (payload?.category) return normalizeLogCategory(payload.category);
  const ev = String(event || '');
  if (ev === 'log') return normalizeLogCategory(payload?.category, 'runtime');
  if (ev.startsWith('node_') || ev.startsWith('flow_') || ev.startsWith('schedule_')) {
    return 'runtime';
  }
  if (ev === 'recording_stopped') return 'audit';
  if (ev === 'plugin_mode_changed' || ev === 'force_reset' || ev === 'hotkey_run') return 'system';
  return 'runtime';
}

/** Display tag for logs: custom name / schema label + id. */
function formatNodeTag(nodeId, nodeName) {
  const id = nodeId || '?';
  const name = nodeName && String(nodeName).trim();
  return name ? `${name} · ${id}` : id;
}

function resolveNodeName(state, nodeId) {
  const id = String(nodeId || '').trim();
  if (!id) return '';
  const node = state?.flow?.nodes?.[id];
  if (!node) return '';
  const custom = node.name && String(node.name).trim();
  if (custom) return custom;
  const schema = state?.schemaMap?.[node.type];
  return (schema?.label && String(schema.label).trim()) || '';
}

function formatRuntimeNodeEnd(payload, nodeName) {
  const nid = payload?.node_id;
  const tag = formatNodeTag(nid, nodeName);
  const result = payload?.result || {};
  const type = payload?.type || 'node';
  if (payload?.summary) {
    return `✓ [${tag}] ${payload.summary}`;
  }
  if (!payload?.ok) {
    if (payload?.stopped) return `■ [${tag}] 已停止`;
    return `✗ [${tag}]: ${payload?.error || '失败'}`;
  }
  if (type === 'ocr_recognize') {
    const t = result.text;
    return t !== undefined && t !== ''
      ? `✓ [${tag}] OCR 识别到: ${String(t).slice(0, 120)}`
      : `✓ [${tag}] OCR 完成但未识别到文字`;
  }
  if (type === 'if_text_contains') {
    if (result.matched) {
      const actual = result.actual_text != null ? ` · 实际: ${String(result.actual_text).slice(0, 80)}` : '';
      return `✓ [${tag}] 文字匹配 成立${actual}`;
    }
    if (result.recognized === false || (result.recognized == null && !result.actual_text)) {
      return `✓ [${tag}] 文字匹配 不成立 · 识别为空`;
    }
    return `✓ [${tag}] 文字匹配 不成立 · 实际: ${String(result.actual_text ?? '').slice(0, 80)}`;
  }
  if (type === 'if_condition' || type === 'if_color_match' || type === 'if_logic') {
    return `✓ [${tag}] 条件${result.matched ? '成立' : '不成立'}${
      result.actual_text != null ? ` · 实际: ${String(result.actual_text).slice(0, 80)}` : ''
    }`;
  }
  if (type === 'color_detect' && result.color) {
    return `✓ [${tag}] 取色: ${result.color}`;
  }
  if (type === 'find_image') {
    return result.found
      ? `✓ [${tag}] 找图命中 score=${result.score} @ (${result.x}, ${result.y})`
      : `✓ [${tag}] 找图未命中`;
  }
  if (type === 'click') {
    const x = result.x ?? result.screen_x;
    const y = result.y ?? result.screen_y;
    const count = Number(result.count || 1);
    const ms = payload.elapsed_ms != null ? ` · ${payload.elapsed_ms}ms` : '';
    if (count > 1) {
      const pts = Array.isArray(result.clicks) ? result.clicks : [];
      const trail = pts
        .filter((p) => p && p.x != null && p.y != null)
        .map((p) => `(${p.x}, ${p.y})`)
        .join(' → ');
      if (trail) return `✓ [${tag}] 多点点击 ${count} 次 ${trail}${ms}`;
      if (x != null && y != null) return `✓ [${tag}] 多点点击 ${count} 次 · 末点 (${x}, ${y})${ms}`;
      return `✓ [${tag}] 多点点击 ${count} 次${ms}`;
    }
    if (x != null && y != null) return `✓ [${tag}] 点击 (${x}, ${y})${ms}`;
  }
  if (type === 'switch') {
    return `✓ [${tag}] 判断值=${JSON.stringify(result.value)} · ${payload.elapsed_ms}ms`;
  }
  if (String(type).startsWith('window_')) {
    if (result.found === false) return `✓ [${tag}] ${type} 未找到窗口`;
    if (result.title || result.matched_title) {
      return `✓ [${tag}] ${type} → ${String(result.title || result.matched_title).slice(0, 80)}`;
    }
  }
  if (type === 'assign') {
    return `✓ [${tag}] 赋值 ${result.name || result.variable || ''}`.trim();
  }
  if (type === 'drag' || type === 'mouse_hover') {
    return `✓ [${tag}] ${type === 'drag' ? '拖拽' : '悬停'}完成 · ${payload.elapsed_ms}ms`;
  }
  if (String(type).startsWith('loop_') || type === 'foreach' || type === 'while') {
    const n = result.iteration ?? result.index ?? result.count;
    return n != null
      ? `✓ [${tag}] ${type} · 第 ${n} 次 · ${payload.elapsed_ms}ms`
      : `✓ [${tag}] ${type} · ${payload.elapsed_ms}ms`;
  }
  if (String(type).startsWith('if_')) {
    if (result.matched !== undefined) {
      return `✓ [${tag}] 条件${result.matched ? '成立' : '不成立'} · ${payload.elapsed_ms}ms`;
    }
  }
  return `✓ [${tag}] ${type} · ${payload.elapsed_ms}ms`;
}

let _highlightClearTimer = null;
let _auditConfigTimer = null;
let _auditConfigPending = null;

function emitAuditToBridge(message, detail) {
  try {
    const api = typeof window !== 'undefined' ? window.pywebview?.api : null;
    if (api && typeof api.log_audit === 'function') {
      void Promise.resolve(api.log_audit(message, detail || null)).catch(() => {});
    }
  } catch {
    /* ignore */
  }
}
const HEAVY_KEYS = new Set(['box', 'image', 'bitmap', 'pixels', 'raw', 'screenshot']);
const LIGHT_LIST_KEYS = new Set(['boxes', 'matches']);

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
    if (Array.isArray(value)) return value.map(v => cloneValue(v));
    return { ...value };
  }
}

const MAX_UNDO = 50;
let historyCoalesce = false;
let historyCoalesceTimer = null;

function resetHistoryCoalesce() {
  historyCoalesce = false;
  if (historyCoalesceTimer != null) {
    clearTimeout(historyCoalesceTimer);
    historyCoalesceTimer = null;
  }
}

/** Snapshot current flow into past and clear future. coalesce merges rapid edits into one step. */
function takeFlowHistory(state, { coalesce = false } = {}) {
  if (coalesce) {
    if (historyCoalesce) {
      if (historyCoalesceTimer != null) clearTimeout(historyCoalesceTimer);
      historyCoalesceTimer = setTimeout(resetHistoryCoalesce, 500);
      return {};
    }
    historyCoalesce = true;
    historyCoalesceTimer = setTimeout(resetHistoryCoalesce, 500);
  } else {
    resetHistoryCoalesce();
  }
  return {
    past: [...(state.past || []), cloneValue(state.flow)].slice(-MAX_UNDO),
    future: []
  };
}

function clearFlowHistory() {
  resetHistoryCoalesce();
  return { past: [], future: [] };
}

function compactWindowTarget(value) {
  if (Array.isArray(value)) return value.slice(0, 24).map(compactWindowTarget).filter(Boolean);
  if (!value || typeof value !== 'object') return null;
  const out = {};
  for (const key of [
    'pid',
    'process_name',
    'class_name',
    'title',
    'client_width',
    'client_height',
    'dpi',
    'point_norm'
  ]) {
    if (!(key in value)) continue;
    const val = value[key];
    if (key === 'point_norm' && Array.isArray(val) && val.length >= 2) {
      const a = Number(val[0]);
      const b = Number(val[1]);
      if (Number.isFinite(a) && Number.isFinite(b)) out[key] = [a, b];
    } else if (key === 'process_name' || key === 'class_name' || key === 'title') {
      out[key] = String(val || '').slice(0, 160);
    } else {
      out[key] = val;
    }
  }
  return Object.keys(out).length ? out : null;
}

/** Preserve live keys/structure; only strip heavy payloads and truncate sizes. */
function compactStructuredDict(item, depth = 0) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return {};
  const entry = {};
  const keys = Object.keys(item);
  for (let i = 0; i < keys.length; i++) {
    if (i >= 40) {
      entry['…'] = `+${keys.length - 40} keys`;
      break;
    }
    const key = keys[i];
    const lk = String(key).toLowerCase();
    if (HEAVY_KEYS.has(lk)) continue;
    const val = item[key];
    if (lk === 'window_target') {
      const wt = compactWindowTarget(val);
      if (wt != null) entry[key] = wt;
      continue;
    }
    if (val == null || typeof val === 'boolean' || typeof val === 'number') {
      entry[key] = val;
    } else if (typeof val === 'string') {
      entry[key] = val.length > 120 ? val.slice(0, 120) : val;
    } else if (Array.isArray(val)) {
      entry[key] = val.slice(0, 24).map(x => {
        if (x == null || typeof x === 'boolean' || typeof x === 'number') return x;
        if (typeof x === 'string') return x.slice(0, 80);
        if (x && typeof x === 'object' && !Array.isArray(x)) return compactStructuredDict(x, depth + 1);
        const n = Number(x);
        return Number.isFinite(n) ? n : String(x).slice(0, 80);
      });
    } else if (typeof val === 'object') {
      entry[key] = depth >= 3 ? '{…}' : compactStructuredDict(val, depth + 1);
    } else {
      entry[key] = String(val).slice(0, 120);
    }
  }
  return entry;
}

/** Slim runtime values kept in UI store / logs to avoid retaining OCR polygons etc. */
function summarizeRuntimeValue(value, depth = 0, key = null) {
  if (value == null || typeof value === 'boolean' || typeof value === 'number') return value;
  if (typeof value === 'string') {
    return value.length > 240 ? `${value.slice(0, 240)}…(+${value.length - 240})` : value;
  }

  const leaf = key != null ? String(key).toLowerCase() : '';
  if (LIGHT_LIST_KEYS.has(leaf) && Array.isArray(value)) {
    return value
      .slice(0, 80)
      .filter(v => v && typeof v === 'object' && !Array.isArray(v))
      .map(v => compactStructuredDict(v));
  }
  if (HEAVY_KEYS.has(leaf)) {
    if (Array.isArray(value)) return { _omitted: leaf, count: value.length };
    return value == null ? value : { _omitted: leaf };
  }
  if (depth >= 6) return '…';

  if (Array.isArray(value)) {
    if (value.length && value.every(v => v == null || typeof v === 'boolean' || typeof v === 'number')) {
      const head = value.slice(0, 24);
      if (value.length > 24) head.push(`…(+${value.length - 24})`);
      return head;
    }
    const head = value.slice(0, 24).map(v => summarizeRuntimeValue(v, depth + 1));
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

function interpolateDoneLog(template, result) {
  // 完成日志模板：{{字段}} 或 {{a.b}} 引用本节点原始输出，缺失字段替换为空串
  return String(template)
    .replace(/\{\{\s*([\w.$]+)\s*\}\}/g, (_, path) => {
      const value = path
        .split('.')
        .reduce((acc, key) => (acc == null ? undefined : acc[key]), result);
      if (value == null) return '';
      if (Array.isArray(value)) return value.map(v => (v == null ? '' : String(v))).join(', ');
      if (typeof value === 'object') return JSON.stringify(value);
      return String(value);
    })
    .trim();
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
              children: [{ kind: 'expr', id: 'c0', expression: '', not: false, label: '' }]
            };
    else if (input.type === 'keymap') params[input.name] = {};
    else params[input.name] = '';
  }
  return params;
}

/** Built-in globals seeded into every flow (missing keys only; never overwrite). */
const DEFAULT_FLOW_VARIABLES = {
  $true: true,
  $false: false,
  $empty: '',
  $zero: 0
};

const DEFAULT_FLOW_VARIABLE_SCHEMAS = {
  $true: { type: 'boolean' },
  $false: { type: 'boolean' },
  $empty: { type: 'string' },
  $zero: { type: 'number' }
};

const SYSTEM_DEFAULT_VAR_BARE = new Set(
  Object.keys(DEFAULT_FLOW_VARIABLES).map(k => String(k).replace(/^\$/, ''))
);

/** Built-in constants ($true / $false / $empty / $zero) — not editable in the Variables panel. */
export function isSystemDefaultVariable(name) {
  const bare = String(name || '')
    .trim()
    .replace(/^\$/, '');
  return !!bare && SYSTEM_DEFAULT_VAR_BARE.has(bare);
}

function hasVarKey(bag, key) {
  if (!bag || typeof bag !== 'object') return false;
  if (key in bag) return true;
  const bare = String(key).replace(/^\$/, '');
  return bare in bag || `$${bare}` in bag;
}

function withDefaultVariables(flow) {
  const base = flow && typeof flow === 'object' ? flow : {};
  const variables = { ...(base.variables || {}) };
  const variable_schemas = { ...(base.variable_schemas || {}) };
  for (const [k, v] of Object.entries(DEFAULT_FLOW_VARIABLES)) {
    if (!hasVarKey(variables, k)) variables[k] = v;
  }
  for (const [k, schema] of Object.entries(DEFAULT_FLOW_VARIABLE_SCHEMAS)) {
    if (!hasVarKey(variable_schemas, k)) variable_schemas[k] = cloneValue(schema);
  }
  return { ...base, variables, variable_schemas };
}

function createEmptyFlow() {
  return withDefaultVariables({
    flow_id: uid('flow'),
    name: '未命名流程',
    version: 1,
    execution_policy: { mode: 'safe' },
    variables: {},
    variable_schemas: {},
    nodes: {},
    entry: null,
    breakpoints: []
  });
}

function normalizeOutputCoordinateMode(v) {
  if (v === 'region_rel' || v === 'screen_abs' || v === 'window_client') return v;
  return 'window_client';
}

const OUTPUT_COORD_NODE_TYPES = new Set(['ocr_recognize', 'find_image']);

/** Defaults for file-backed UI settings (config.json `ui`). */
export const DEFAULT_UI_SETTINGS = {
  hideWindowOnRecord: false,
  showToolbarLabels: true,
  nodeContextMenuMode: 'grouped',
  hideSidePanelsOnSettings: true,
  autoSaveEnabled: false,
  autoSaveIntervalSec: 60,
  saveAfterRun: true,
  defaultCaptureMode: 'coord',
  defaultPickMethod: 'screenshot',
  defaultCoordinateMode: 'window_client',
  defaultOutputCoordinateMode: 'window_client',
  // Default 500ms between nodes when unset
  defaultNodeIntervalMs: 500,
  themeName: 'Ocean',
  themeMode: 'dark',
  diagLogging: false,
  autoCheckUpdate: true,
  aiMode: 'chat'
};

const LEGACY_UI_STORAGE_KEYS = [
  'nexuz.hideWindowOnRecord',
  'nexuz.showToolbarLabels',
  'nexuz.nodeContextMenuMode',
  'nexuz.hideSidePanelsOnSettings',
  'nexuz.autoSaveEnabled',
  'nexuz.autoSaveIntervalSec',
  'nexuz.saveAfterRun',
  'nexuz.defaultCaptureMode',
  'nexuz.defaultPickMethod',
  'nexuz.defaultCoordinateMode',
  'nexuz.defaultOutputCoordinateMode',
  'nexuz.defaultNodeIntervalMs',
  'nexuz.hotkeys',
  'nexuz.recordStopHotkey',
  'nexuz.themeName',
  'nexuz.themeMode',
  'nexuz.diagLogging',
  'nexuz.autoCheckUpdate',
  'nexuz.ai.mode'
];

function boolFromLegacy(v, fallback) {
  if (v === null || v === undefined) return fallback;
  if (v === '1' || v === 'true') return true;
  if (v === '0' || v === 'false') return false;
  return fallback;
}

/** One-time migrate from browser localStorage → file settings. */
export function collectLegacyUiSettingsFromLocalStorage() {
  const out = {};
  try {
    const hide = localStorage.getItem('nexuz.hideWindowOnRecord');
    if (hide !== null) out.hideWindowOnRecord = boolFromLegacy(hide, false);
    const labels = localStorage.getItem('nexuz.showToolbarLabels');
    if (labels !== null) out.showToolbarLabels = boolFromLegacy(labels, true);
    const menu = localStorage.getItem('nexuz.nodeContextMenuMode');
    if (menu === 'flat' || menu === 'grouped') out.nodeContextMenuMode = menu;
    const hideSide = localStorage.getItem('nexuz.hideSidePanelsOnSettings');
    if (hideSide !== null) out.hideSidePanelsOnSettings = boolFromLegacy(hideSide, true);
    const autoSave = localStorage.getItem('nexuz.autoSaveEnabled');
    if (autoSave !== null) out.autoSaveEnabled = boolFromLegacy(autoSave, false);
    const autoSec = Number(localStorage.getItem('nexuz.autoSaveIntervalSec'));
    if (Number.isFinite(autoSec)) out.autoSaveIntervalSec = Math.min(3600, Math.max(10, Math.round(autoSec)));
    const saveAfter = localStorage.getItem('nexuz.saveAfterRun');
    if (saveAfter !== null) out.saveAfterRun = boolFromLegacy(saveAfter, true);
    const capture = localStorage.getItem('nexuz.defaultCaptureMode');
    if (capture === 'frida_ui' || capture === 'coord') out.defaultCaptureMode = capture;
    const pick = localStorage.getItem('nexuz.defaultPickMethod');
    if (pick === 'live' || pick === 'screenshot') out.defaultPickMethod = pick;
    const coord = localStorage.getItem('nexuz.defaultCoordinateMode');
    if (coord === 'window_client' || coord === 'virtual_norm' || coord === 'screen_abs') {
      out.defaultCoordinateMode = coord;
    }
    const outCoord = localStorage.getItem('nexuz.defaultOutputCoordinateMode');
    if (outCoord) out.defaultOutputCoordinateMode = normalizeOutputCoordinateMode(outCoord);
    const interval = Number(localStorage.getItem('nexuz.defaultNodeIntervalMs'));
    if (Number.isFinite(interval)) out.defaultNodeIntervalMs = Math.max(0, Math.round(interval));
    const themeName = localStorage.getItem('nexuz.themeName');
    if (themeName) out.themeName = themeName;
    const themeMode = localStorage.getItem('nexuz.themeMode');
    if (themeMode === 'light' || themeMode === 'dark') out.themeMode = themeMode;
    const diag = localStorage.getItem('nexuz.diagLogging');
    if (diag !== null) out.diagLogging = boolFromLegacy(diag, false);
    const autoCheck = localStorage.getItem('nexuz.autoCheckUpdate');
    if (autoCheck !== null) out.autoCheckUpdate = boolFromLegacy(autoCheck, true);
    const aiMode = localStorage.getItem('nexuz.ai.mode');
    if (aiMode === 'chat' || aiMode === 'flow') out.aiMode = aiMode;
    const hotRaw = localStorage.getItem('nexuz.hotkeys');
    if (hotRaw) {
      try {
        const parsed = JSON.parse(hotRaw);
        if (parsed && typeof parsed === 'object') out.hotkeys = parsed;
      } catch {
        /* ignore */
      }
    }
  } catch {
    /* ignore */
  }
  return out;
}

export function clearLegacyUiSettingsLocalStorage() {
  try {
    for (const key of LEGACY_UI_STORAGE_KEYS) localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

function persistUiSettings(patch) {
  if (!patch || typeof patch !== 'object') return;
  void import('../bridge.js')
    .then(mod => mod.bridge?.setUiSettings?.(patch))
    .catch(() => {});
}

export const DEFAULT_HOTKEYS = {
  start_run: ['x', 'f3'],
  stop_run: ['x', 'f4'],
  pause_run: ['x', 'f5'],
  record_stop: ['x', 'f10'],
  plugin_mode: ['x', 'f6'],
  click_through: ['x', 'f7']
};

/** @deprecated use DEFAULT_HOTKEYS.record_stop */
export const DEFAULT_RECORD_STOP_HOTKEY = DEFAULT_HOTKEYS.record_stop;

export const HOTKEY_SLOTS = ['start_run', 'stop_run', 'pause_run', 'record_stop', 'plugin_mode', 'click_through'];

export function formatHotkeyLabel(keys) {
  const arr = Array.isArray(keys) ? keys : [];
  const modLabel = { ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', win: 'Win' };
  return arr
    .map(k => {
      const s = String(k || '').toLowerCase();
      if (modLabel[s]) return modLabel[s];
      if (/^f\d{1,2}$/.test(s)) return s.toUpperCase();
      if (s.length === 1) return s.toUpperCase();
      return s;
    })
    .filter(Boolean)
    .join('+');
}

function normalizeHotkey(keys, fallback) {
  const mods = ['ctrl', 'alt', 'shift', 'win'];
  const items = [];
  const seen = new Set();
  for (const raw of Array.isArray(keys) ? keys : []) {
    const k = String(raw || '')
      .trim()
      .toLowerCase();
    if (!k || seen.has(k)) continue;
    seen.add(k);
    items.push(k);
  }
  const fb = Array.isArray(fallback) ? [...fallback] : [...DEFAULT_HOTKEYS.record_stop];
  if (!items.length) return fb;
  const modPart = mods.filter(m => items.includes(m));
  const others = items.filter(k => !mods.includes(k));
  if (!others.length) return fb;
  const trigger = others[others.length - 1];
  const held = others.slice(0, -1);
  return [...modPart, ...held, trigger];
}

function defaultHotkeys() {
  const out = {};
  for (const slot of HOTKEY_SLOTS) {
    out[slot] = [...DEFAULT_HOTKEYS[slot]];
  }
  return out;
}

function persistHotkeys(hotkeys) {
  persistUiSettings({ hotkeys });
}

export const useFlowStore = create((set, get) => ({
  flow: createEmptyFlow(),
  past: [],
  future: [],
  schemas: [],
  schemaMap: {},
  selectedNodeId: null,
  viewMode: 'canvas', // canvas | code | flowchart | settings
  /** Last non-settings view; kept selected in the view group while settings is open. */
  lastFlowViewMode: 'canvas', // canvas | code | flowchart
  bridgeReady: false,
  filePath: null,
  uiSettingsReady: false,

  // theme (CanvasFlow)
  themeName: DEFAULT_UI_SETTINGS.themeName,
  themeMode: DEFAULT_UI_SETTINGS.themeMode,

  // app settings (hydrated from config.json via bridge)
  hideWindowOnRecord: DEFAULT_UI_SETTINGS.hideWindowOnRecord,
  showToolbarLabels: DEFAULT_UI_SETTINGS.showToolbarLabels,
  nodeContextMenuMode: DEFAULT_UI_SETTINGS.nodeContextMenuMode,
  hideSidePanelsOnSettings: DEFAULT_UI_SETTINGS.hideSidePanelsOnSettings,
  autoSaveEnabled: DEFAULT_UI_SETTINGS.autoSaveEnabled,
  autoSaveIntervalSec: DEFAULT_UI_SETTINGS.autoSaveIntervalSec,
  saveAfterRun: DEFAULT_UI_SETTINGS.saveAfterRun,
  defaultCaptureMode: DEFAULT_UI_SETTINGS.defaultCaptureMode,
  defaultPickMethod: DEFAULT_UI_SETTINGS.defaultPickMethod,
  defaultCoordinateMode: DEFAULT_UI_SETTINGS.defaultCoordinateMode,
  defaultOutputCoordinateMode: DEFAULT_UI_SETTINGS.defaultOutputCoordinateMode,
  defaultNodeIntervalMs: DEFAULT_UI_SETTINGS.defaultNodeIntervalMs,
  diagLogging: DEFAULT_UI_SETTINGS.diagLogging,
  autoCheckUpdate: DEFAULT_UI_SETTINGS.autoCheckUpdate,
  aiMode: DEFAULT_UI_SETTINGS.aiMode,
  hotkeys: defaultHotkeys(),

  // run history for sidebar
  runHistory: [],

  // execution
  execStatus: 'idle', // idle | running | paused | stopping | breakpoint
  /** Bumped when a scheduled job fires/errors so SchedulePanel can refresh. */
  scheduleRefreshToken: 0,
  /** Last plugin-mode snapshot from backend (hotkey / set_plugin_mode). */
  pluginModeRemote: null,
  execNodeId: null,
  execNodeStates: {}, // id -> running|done|error
  debugMode: false,
  /** Temporary red highlight from log click (auto-clears). */
  highlightNodeId: null,
  /** Bumps on each log-focus so re-clicking the same node restarts pan/pulse. */
  highlightSeq: 0,
  logs: [],
  runLog: null,

  hydrateUiSettings: (settings = {}) => {
    const s = settings && typeof settings === 'object' ? settings : {};
    const patch = { uiSettingsReady: true };
    if ('hideWindowOnRecord' in s) patch.hideWindowOnRecord = !!s.hideWindowOnRecord;
    if ('showToolbarLabels' in s) patch.showToolbarLabels = !!s.showToolbarLabels;
    if ('nodeContextMenuMode' in s) {
      patch.nodeContextMenuMode = s.nodeContextMenuMode === 'flat' ? 'flat' : 'grouped';
    }
    if ('hideSidePanelsOnSettings' in s) {
      patch.hideSidePanelsOnSettings = !!s.hideSidePanelsOnSettings;
    }
    if ('autoSaveEnabled' in s) patch.autoSaveEnabled = !!s.autoSaveEnabled;
    if ('autoSaveIntervalSec' in s) {
      const value = Number(s.autoSaveIntervalSec);
      patch.autoSaveIntervalSec = Number.isFinite(value)
        ? Math.min(3600, Math.max(10, Math.round(value)))
        : 60;
    }
    if ('saveAfterRun' in s) patch.saveAfterRun = !!s.saveAfterRun;
    if ('defaultCaptureMode' in s) {
      patch.defaultCaptureMode = s.defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
    }
    if ('defaultPickMethod' in s) {
      patch.defaultPickMethod = s.defaultPickMethod === 'live' ? 'live' : 'screenshot';
    }
    if ('defaultCoordinateMode' in s) {
      const mode = s.defaultCoordinateMode;
      patch.defaultCoordinateMode =
        mode === 'window_client' || mode === 'virtual_norm' || mode === 'screen_abs'
          ? mode
          : 'window_client';
    }
    if ('defaultOutputCoordinateMode' in s) {
      patch.defaultOutputCoordinateMode = normalizeOutputCoordinateMode(s.defaultOutputCoordinateMode);
    }
    if ('defaultNodeIntervalMs' in s) {
      const value = Number(s.defaultNodeIntervalMs);
      patch.defaultNodeIntervalMs = Number.isFinite(value)
        ? Math.max(0, Math.round(value))
        : DEFAULT_UI_SETTINGS.defaultNodeIntervalMs;
    }
    if ('themeName' in s && s.themeName) patch.themeName = String(s.themeName);
    if ('themeMode' in s) patch.themeMode = s.themeMode === 'light' ? 'light' : 'dark';
    if ('diagLogging' in s) patch.diagLogging = !!s.diagLogging;
    if ('autoCheckUpdate' in s) patch.autoCheckUpdate = !!s.autoCheckUpdate;
    if ('aiMode' in s) patch.aiMode = s.aiMode === 'flow' ? 'flow' : 'chat';
    if (s.hotkeys && typeof s.hotkeys === 'object') {
      const next = defaultHotkeys();
      for (const slot of HOTKEY_SLOTS) {
        if (s.hotkeys[slot] != null) {
          next[slot] = normalizeHotkey(s.hotkeys[slot], DEFAULT_HOTKEYS[slot]);
        }
      }
      patch.hotkeys = next;
    }
    set(patch);
    return get();
  },

  setHideWindowOnRecord: hideWindowOnRecord => {
    const value = !!hideWindowOnRecord;
    set({ hideWindowOnRecord: value });
    persistUiSettings({ hideWindowOnRecord: value });
  },

  setShowToolbarLabels: showToolbarLabels => {
    const value = !!showToolbarLabels;
    set({ showToolbarLabels: value });
    persistUiSettings({ showToolbarLabels: value });
  },

  setNodeContextMenuMode: mode => {
    const next = mode === 'flat' ? 'flat' : 'grouped';
    set({ nodeContextMenuMode: next });
    persistUiSettings({ nodeContextMenuMode: next });
  },

  setHideSidePanelsOnSettings: hideSidePanelsOnSettings => {
    const value = !!hideSidePanelsOnSettings;
    set({ hideSidePanelsOnSettings: value });
    persistUiSettings({ hideSidePanelsOnSettings: value });
  },

  setAutoSaveEnabled: autoSaveEnabled => {
    const value = !!autoSaveEnabled;
    set({ autoSaveEnabled: value });
    persistUiSettings({ autoSaveEnabled: value });
  },

  setAutoSaveIntervalSec: autoSaveIntervalSec => {
    const value = Number(autoSaveIntervalSec);
    const sec = Number.isFinite(value) ? Math.min(3600, Math.max(10, Math.round(value))) : 60;
    set({ autoSaveIntervalSec: sec });
    persistUiSettings({ autoSaveIntervalSec: sec });
  },

  setSaveAfterRun: saveAfterRun => {
    const value = !!saveAfterRun;
    set({ saveAfterRun: value });
    persistUiSettings({ saveAfterRun: value });
  },

  setHotkey: (slot, keys) => {
    const key = String(slot || '');
    if (!HOTKEY_SLOTS.includes(key)) return get().hotkeys;
    const fallback = DEFAULT_HOTKEYS[key];
    const nextKeys = normalizeHotkey(keys, fallback);
    const prev = get().hotkeys || defaultHotkeys();
    const next = { ...prev, [key]: nextKeys };
    // Reject duplicate combos against other slots.
    const sig = nextKeys.join('+');
    for (const other of HOTKEY_SLOTS) {
      if (other === key) continue;
      if ((next[other] || []).join('+') === sig) {
        return { ok: false, error: `与「${other}」快捷键冲突`, hotkeys: prev };
      }
    }
    persistHotkeys(next);
    set({ hotkeys: next });
    return { ok: true, hotkeys: next, keys: nextKeys };
  },

  setHotkeys: prefs => {
    const prev = get().hotkeys || defaultHotkeys();
    const next = { ...prev };
    for (const slot of HOTKEY_SLOTS) {
      if (prefs && prefs[slot] != null) {
        next[slot] = normalizeHotkey(prefs[slot], DEFAULT_HOTKEYS[slot]);
      }
    }
    const seen = new Map();
    for (const slot of HOTKEY_SLOTS) {
      const sig = (next[slot] || []).join('+');
      if (seen.has(sig)) {
        return {
          ok: false,
          error: `快捷键冲突：${formatHotkeyLabel(next[slot])}`,
          hotkeys: prev
        };
      }
      seen.set(sig, slot);
    }
    persistHotkeys(next);
    set({ hotkeys: next });
    return { ok: true, hotkeys: next };
  },

  resetHotkeys: () => {
    const next = defaultHotkeys();
    persistHotkeys(next);
    set({ hotkeys: next });
    return next;
  },

  setRecordStopHotkey: keys => {
    const res = get().setHotkey('record_stop', keys);
    return res?.keys || get().hotkeys.record_stop;
  },

  setDefaultCaptureMode: defaultCaptureMode => {
    const mode = defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
    set({ defaultCaptureMode: mode });
    persistUiSettings({ defaultCaptureMode: mode });
  },

  setDefaultPickMethod: defaultPickMethod => {
    const method = defaultPickMethod === 'live' ? 'live' : 'screenshot';
    set({ defaultPickMethod: method });
    persistUiSettings({ defaultPickMethod: method });
  },

  setDefaultCoordinateMode: defaultCoordinateMode => {
    const mode =
      defaultCoordinateMode === 'window_client' || defaultCoordinateMode === 'virtual_norm'
        ? defaultCoordinateMode
        : 'screen_abs';
    set({ defaultCoordinateMode: mode });
    persistUiSettings({ defaultCoordinateMode: mode });
  },

  setDefaultOutputCoordinateMode: defaultOutputCoordinateMode => {
    const mode = normalizeOutputCoordinateMode(defaultOutputCoordinateMode);
    set({ defaultOutputCoordinateMode: mode });
    persistUiSettings({ defaultOutputCoordinateMode: mode });
  },

  setDefaultNodeIntervalMs: defaultNodeIntervalMs => {
    const value = Number(defaultNodeIntervalMs);
    const interval = Number.isFinite(value)
      ? Math.max(0, Math.round(value))
      : DEFAULT_UI_SETTINGS.defaultNodeIntervalMs;
    set({ defaultNodeIntervalMs: interval });
    persistUiSettings({ defaultNodeIntervalMs: interval });
  },

  setDiagLogging: diagLogging => {
    const value = !!diagLogging;
    set({ diagLogging: value });
    persistUiSettings({ diagLogging: value });
  },

  setAutoCheckUpdate: autoCheckUpdate => {
    const value = !!autoCheckUpdate;
    set({ autoCheckUpdate: value });
    persistUiSettings({ autoCheckUpdate: value });
  },

  setAiMode: aiMode => {
    const value = aiMode === 'flow' ? 'flow' : 'chat';
    set({ aiMode: value });
    persistUiSettings({ aiMode: value });
  },

  /** Force all nodes with an explicit pick_method to the given value */
  syncAllPickMethods: method =>
    set(state => {
      const m = method === 'live' ? 'live' : 'screenshot';
      const nodes = { ...state.flow.nodes };
      let changed = false;
      for (const [id, node] of Object.entries(nodes)) {
        if (!node || typeof node !== 'object') continue;
        const prev = node.params?.pick_method;
        if (prev !== 'live' && prev !== 'screenshot') continue;
        if (prev === m) continue;
        changed = true;
        nodes[id] = {
          ...node,
          params: { ...(node.params || {}), pick_method: m }
        };
      }
      if (!changed) return state;
      return { ...takeFlowHistory(state), flow: { ...state.flow, nodes } };
    }),

  /** Force all click nodes to use the given capture_mode */
  syncAllClickCaptureModes: mode =>
    set(state => {
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
          params: { ...(node.params || {}), capture_mode: m }
        };
      }
      if (!changed) return state;
      return { ...takeFlowHistory(state), flow: { ...state.flow, nodes } };
    }),

  /** Force all coordinate-based click nodes to use the given coordinate_mode. */
  syncAllClickCoordinateModes: mode =>
    set(state => {
      const m = mode === 'window_client' || mode === 'virtual_norm' ? mode : 'screen_abs';
      const nodes = { ...state.flow.nodes };
      let changed = false;
      for (const [id, node] of Object.entries(nodes)) {
        if (node?.type !== 'click') continue;
        if ((node.params?.capture_mode || 'coord') !== 'coord') continue;
        const nestedMode =
          node.params?.coord && typeof node.params.coord === 'object' ? node.params.coord.coordinate_mode : null;
        if (node.params?.coordinate_mode === m && (!nestedMode || nestedMode === m)) continue;
        changed = true;
        const params = { ...(node.params || {}), coordinate_mode: m };
        if (params.coord && typeof params.coord === 'object') {
          params.coord = { ...params.coord, coordinate_mode: m };
        }
        nodes[id] = {
          ...node,
          params
        };
      }
      if (!changed) return state;
      return { ...takeFlowHistory(state), flow: { ...state.flow, nodes } };
    }),

  /** Force OCR / find_image nodes to use the given output_coordinate_mode. */
  syncAllOutputCoordinateModes: mode =>
    set(state => {
      const m = normalizeOutputCoordinateMode(mode);
      const nodes = { ...state.flow.nodes };
      let changed = false;
      for (const [id, node] of Object.entries(nodes)) {
        if (!OUTPUT_COORD_NODE_TYPES.has(node?.type)) continue;
        if (node.params?.output_coordinate_mode === m) continue;
        changed = true;
        nodes[id] = {
          ...node,
          params: { ...(node.params || {}), output_coordinate_mode: m }
        };
      }
      if (!changed) return state;
      return { ...takeFlowHistory(state), flow: { ...state.flow, nodes } };
    }),

  setThemeName: themeName => {
    set({ themeName });
    const persist = () => persistUiSettings({ themeName });
    if (typeof requestIdleCallback === 'function') requestIdleCallback(persist);
    else setTimeout(persist, 0);
  },

  setThemeMode: themeMode => {
    set({ themeMode });
    const persist = () => persistUiSettings({ themeMode });
    if (typeof requestIdleCallback === 'function') requestIdleCallback(persist);
    else setTimeout(persist, 0);
  },

  clearRunHistory: () => set({ runHistory: [] }),
  pushRunHistory: item =>
    set(state => ({
      runHistory: [item, ...state.runHistory].slice(0, 50)
    })),

  setBridgeReady: v => set({ bridgeReady: v }),
  setSchemas: schemas => {
    const schemaMap = {};
    for (const s of schemas) schemaMap[s.type] = s;
    set({ schemas, schemaMap });
  },

  setViewMode: viewMode => {
    if (viewMode === 'canvas' || viewMode === 'code' || viewMode === 'flowchart') {
      set({ viewMode, lastFlowViewMode: viewMode });
      return;
    }
    set({ viewMode });
  },
  selectNode: selectedNodeId => set({ selectedNodeId }),

  /** Select + red-highlight a node (e.g. from run.log click). Clears after 2.5s. */
  highlightNode: nodeId => {
    const id = nodeId ? String(nodeId).trim() : '';
    if (_highlightClearTimer) {
      clearTimeout(_highlightClearTimer);
      _highlightClearTimer = null;
    }
    if (!id) {
      set({ highlightNodeId: null });
      return;
    }
    set(state => ({
      highlightNodeId: id,
      selectedNodeId: id,
      highlightSeq: (state.highlightSeq || 0) + 1
    }));
    _highlightClearTimer = setTimeout(() => {
      set(state => (state.highlightNodeId === id ? { highlightNodeId: null } : {}));
      _highlightClearTimer = null;
    }, 2500);
  },

  setDebugMode: debugMode => set({ debugMode: !!debugMode }),

  toggleDebugMode: () =>
    set(state => {
      const next = !state.debugMode;
      if (!next && (state.execStatus === 'breakpoint' || state.execStatus === 'stepping')) {
        // Turning off debug while stopped at BP — leave session as-is; user can Stop.
      }
      return { debugMode: next };
    }),

  toggleBreakpoint: nodeId => {
    const id = String(nodeId || '').trim();
    if (!id) return;
    set(state => {
      const prev = Array.isArray(state.flow.breakpoints) ? state.flow.breakpoints.map(String) : [];
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, breakpoints: [...next] }
      };
    });
  },

  setBreakpoints: nodeIds => {
    const breakpoints = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    set(state => ({
      ...takeFlowHistory(state),
      flow: { ...state.flow, breakpoints }
    }));
  },

  /** Enable or disable breakpoints for a set of nodes (unified multi-select). */
  setBreakpointsForNodes: (nodeIds, enabled) => {
    const ids = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    if (!ids.length) return;
    set(state => {
      const prev = Array.isArray(state.flow.breakpoints)
        ? state.flow.breakpoints.map(String)
        : [];
      const next = new Set(prev);
      for (const id of ids) {
        if (enabled) next.add(id);
        else next.delete(id);
      }
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, breakpoints: [...next] }
      };
    });
  },

  /**
   * Replace the whole flow.
   * @param {object} [options]
   * @param {boolean} [options.recordHistory] - push current flow onto undo stack (e.g. JSON apply)
   */
  setFlow: (flow, filePath = undefined, options = {}) =>
    set(state => {
      const normalizedFlow = withDefaultVariables({
        ...createEmptyFlow(),
        ...flow,
        nodes: flow.nodes || {},
        breakpoints: Array.isArray(flow.breakpoints) ? flow.breakpoints.map(String) : []
      });
      // Missing policy identifies a legacy/imported flow and preserves its
      // historical runtime behavior. Newly created flows declare safe mode.
      if (!Object.prototype.hasOwnProperty.call(flow, 'execution_policy')) {
        delete normalizedFlow.execution_policy;
      }
      const next = {
        flow: normalizedFlow,
        selectedNodeId: null,
        highlightNodeId: null,
        filePath: filePath === undefined ? state.filePath : filePath,
        execNodeStates: {},
        execNodeId: null
      };
      if (options?.recordHistory) {
        return { ...next, ...takeFlowHistory(state, { coalesce: !!options.coalesce }) };
      }
      return { ...next, ...clearFlowHistory() };
    }),

  undo: () =>
    set(state => {
      if (!state.past?.length) return state;
      resetHistoryCoalesce();
      const previous = state.past[state.past.length - 1];
      const past = state.past.slice(0, -1);
      const future = [cloneValue(state.flow), ...(state.future || [])].slice(0, MAX_UNDO);
      const selectedNodeId =
        state.selectedNodeId && previous.nodes?.[state.selectedNodeId] ? state.selectedNodeId : null;
      return { flow: previous, past, future, selectedNodeId };
    }),

  redo: () =>
    set(state => {
      if (!state.future?.length) return state;
      resetHistoryCoalesce();
      const next = state.future[0];
      const future = state.future.slice(1);
      const past = [...(state.past || []), cloneValue(state.flow)].slice(-MAX_UNDO);
      const selectedNodeId =
        state.selectedNodeId && next.nodes?.[state.selectedNodeId] ? state.selectedNodeId : null;
      return { flow: next, past, future, selectedNodeId };
    }),

  updateFlowMeta: patch =>
    set(state => ({
      ...takeFlowHistory(state, { coalesce: true }),
      flow: { ...state.flow, ...patch }
    })),

  setVariable: (name, value, schema) =>
    set(state => {
      const key = String(name || '').trim();
      if (!key || isSystemDefaultVariable(key)) return state;
      const variables = { ...(state.flow.variables || {}), [key]: value };
      let variable_schemas = { ...(state.flow.variable_schemas || {}) };
      if (schema && typeof schema === 'object') {
        variable_schemas[key] = schema;
      }
      return {
        ...takeFlowHistory(state, { coalesce: true }),
        flow: { ...state.flow, variables, variable_schemas }
      };
    }),

  setVariableSchema: (name, schema) =>
    set(state => {
      const key = String(name || '').trim();
      if (!key || isSystemDefaultVariable(key)) return state;
      const variable_schemas = { ...(state.flow.variable_schemas || {}) };
      if (!schema) {
        delete variable_schemas[key];
        delete variable_schemas[String(key).replace(/^\$/, '')];
        delete variable_schemas[`$${String(key).replace(/^\$/, '')}`];
      } else {
        variable_schemas[key] = schema;
      }
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, variable_schemas }
      };
    }),

  deleteVariable: name =>
    set(state => {
      if (isSystemDefaultVariable(name)) return state;
      const variables = { ...(state.flow.variables || {}) };
      const variable_schemas = { ...(state.flow.variable_schemas || {}) };
      const bare = String(name).replace(/^\$/, '');
      const dollar = `$${bare}`;
      delete variables[name];
      delete variables[bare];
      delete variables[dollar];
      delete variable_schemas[name];
      delete variable_schemas[bare];
      delete variable_schemas[dollar];
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, variables, variable_schemas }
      };
    }),

  renameVariable: (oldName, newName) =>
    set(state => {
      const from = String(oldName || '').trim();
      const to = String(newName || '').trim();
      if (!from || !to || from === to) return state;
      if (isSystemDefaultVariable(from) || isSystemDefaultVariable(to)) return state;
      const variables = { ...(state.flow.variables || {}) };
      const variable_schemas = { ...(state.flow.variable_schemas || {}) };
      if (!(from in variables)) return state;
      variables[to] = variables[from];
      delete variables[from];
      if (from in variable_schemas) {
        variable_schemas[to] = variable_schemas[from];
        delete variable_schemas[from];
      }
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, variables, variable_schemas }
      };
    }),

  addNodeFromSchema: (type, position = { x: 120, y: 120 }) => {
    const schema = get().schemaMap[type];
    if (!schema) return null;
    const id = uid('node');
    const params = defaultParams(schema);
    if (type === 'click') {
      const mode = get().defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
      params.capture_mode = mode;
      params.coordinate_mode = get().defaultCoordinateMode || 'window_client';
    }
    if (type === 'drag' || type === 'mouse_hover') {
      params.coordinate_mode = get().defaultCoordinateMode || 'window_client';
    }
    if (OUTPUT_COORD_NODE_TYPES.has(type)) {
      params.output_coordinate_mode = get().defaultOutputCoordinateMode || 'window_client';
    }
    const node = {
      type,
      params,
      next: null,
      position
    };
    if (['if_condition', 'if_color_match', 'if_text_contains', 'if_logic'].includes(type)) {
      node.then = null;
      node.else = null;
      delete node.next;
    }
    if (['loop_n', 'loop_while', 'loop_forever', 'loop_foreach'].includes(type)) {
      node.body = null;
      node.next = null;
    }
    if (type === 'try_catch') {
      node.body = null;
      node.catch = null;
      node.finally = null;
      node.next = null;
    }
    set(state => {
      const nodes = { ...state.flow.nodes, [id]: node };
      const entry = state.flow.entry || id;
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, nodes, entry },
        selectedNodeId: id
      };
    });
    get().appendAuditLog?.(`添加节点 ${type}`, { node_id: id, type });
    return id;
  },

  appendRecordedNodes: recorded => {
    if (!recorded?.length) return;
    set(state => {
      const nodes = { ...state.flow.nodes };
      let lastId = null;
      // find a tail from entry for chaining, or just set entry
      const existingIds = Object.keys(nodes);
      if (!state.flow.entry && recorded[0]) {
        // will set entry to first
      } else if (state.flow.entry) {
        // find node with no next
        for (const [id, n] of Object.entries(nodes)) {
          if (!n.next && !n.then && !n.body && !n.catch && !n.finally) lastId = id;
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
        let params = cloneValue(item.params || {});
        if (item.type === 'click' && (params.capture_mode || 'coord') === 'coord') {
          const coordinateMode = state.defaultCoordinateMode || 'window_client';
          params = { ...params, coordinate_mode: coordinateMode };
          if (params.coord && typeof params.coord === 'object') {
            params.coord = { ...params.coord, coordinate_mode: coordinateMode };
          }
        }
        nodes[id] = {
          type: item.type,
          params,
          next: null,
          position: { x, y }
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
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes,
          entry: state.flow.entry || firstId
        }
      };
    });
  },

  updateNodeParams: (nodeId, params) => {
    set(state => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const nextParams = { ...node.params, ...params };
      // Clear inherit / null overrides so node follows global defaultPickMethod
      if (
        Object.prototype.hasOwnProperty.call(params, 'pick_method') &&
        (params.pick_method == null || params.pick_method === 'inherit')
      ) {
        delete nextParams.pick_method;
      }
      const patch = { ...node, params: nextParams };
      // Keep switch default ↔ next in sync for legacy interpreter fallback
      if (node.type === 'switch' && Object.prototype.hasOwnProperty.call(params, 'default')) {
        patch.next = params.default || null;
      }
      return {
        ...takeFlowHistory(state, { coalesce: true }),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: patch
          }
        }
      };
    });
    // Debounce audit for rapid param edits
    _auditConfigPending = {
      message: `修改节点参数 [${nodeId}]`,
      detail: { node_id: nodeId, keys: Object.keys(params || {}) }
    };
    if (_auditConfigTimer) clearTimeout(_auditConfigTimer);
    _auditConfigTimer = setTimeout(() => {
      const pending = _auditConfigPending;
      _auditConfigPending = null;
      _auditConfigTimer = null;
      if (pending) get().appendAuditLog?.(pending.message, pending.detail);
    }, 800);
  },

  updateNodeName: (nodeId, name) => {
    set(state => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const raw = String(name ?? '');
      const nextNode = { ...node };
      if (raw.trim()) nextNode.name = raw;
      else delete nextNode.name;
      return {
        ...takeFlowHistory(state, { coalesce: true }),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: nextNode
          }
        }
      };
    });
    get().appendAuditLog?.(`重命名节点 [${nodeId}]`, {
      node_id: nodeId,
      name: String(name ?? '').trim() || null
    });
  },

  setNodeCollapsed: (nodeId, collapsed) =>
    set(state => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const nextNode = { ...node };
      if (collapsed) nextNode.collapsed = true;
      else delete nextNode.collapsed;
      return {
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: nextNode
          }
        }
      };
    }),

  setNodesCollapsed: (nodeIds, collapsed) => {
    const ids = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    if (!ids.length) return;
    set(state => {
      let changed = false;
      const nodes = { ...state.flow.nodes };
      for (const id of ids) {
        const node = nodes[id];
        if (!node) continue;
        const nextNode = { ...node };
        if (collapsed) nextNode.collapsed = true;
        else delete nextNode.collapsed;
        nodes[id] = nextNode;
        changed = true;
      }
      if (!changed) return state;
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, nodes }
      };
    });
  },

  setNodeDisabled: (nodeId, disabled) =>
    set(state => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      const nextNode = { ...node };
      if (disabled) nextNode.disabled = true;
      else delete nextNode.disabled;
      return {
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: nextNode
          }
        }
      };
    }),

  setNodesDisabled: (nodeIds, disabled) => {
    const ids = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    if (!ids.length) return;
    set(state => {
      let changed = false;
      const nodes = { ...state.flow.nodes };
      for (const id of ids) {
        const node = nodes[id];
        if (!node) continue;
        const nextNode = { ...node };
        if (disabled) nextNode.disabled = true;
        else delete nextNode.disabled;
        nodes[id] = nextNode;
        changed = true;
      }
      if (!changed) return state;
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, nodes }
      };
    });
  },

  setNodesAiRefine: (nodeIds, enabled) => {
    const ids = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    if (!ids.length) return;
    set(state => {
      let changed = false;
      const nodes = { ...state.flow.nodes };
      for (const id of ids) {
        const node = nodes[id];
        if (!node) continue;
        const nextNode = { ...node };
        if (enabled) nextNode.ai_refine = true;
        else delete nextNode.ai_refine;
        nodes[id] = nextNode;
        changed = true;
      }
      if (!changed) return state;
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, nodes }
      };
    });
  },

  /** Clear all flow out-edges on nodes (next/then/else/body/switch). */
  clearNodesFlowOuts: nodeIds => {
    const ids = [...new Set((nodeIds || []).map(String).filter(Boolean))];
    if (!ids.length) return;
    set(state => {
      let changed = false;
      const nodes = { ...state.flow.nodes };
      for (const id of ids) {
        const node = nodes[id];
        if (!node) continue;
        const nextNode = { ...node };
        for (const k of ['next', 'then', 'else', 'body', 'catch', 'finally']) {
          if (nextNode[k]) {
            nextNode[k] = null;
            changed = true;
          }
        }
        if (nextNode.type === 'switch' && nextNode.params) {
          const params = { ...nextNode.params };
          if (Array.isArray(params.cases)) {
            params.cases = params.cases.map(c =>
              c && typeof c === 'object' ? { ...c, node_id: '' } : c
            );
          }
          params.default = '';
          nextNode.params = params;
          nextNode.next = null;
          changed = true;
        }
        nodes[id] = nextNode;
      }
      if (!changed) return state;
      return {
        ...takeFlowHistory(state),
        flow: { ...state.flow, nodes }
      };
    });
  },

  /**
   * Disconnect nodes completely: clear their flow outs, inbound flow pointers,
   * and exact {{node.field}} data bindings involving them.
   */
  disconnectNodes: nodeIds => {
    const idSet = new Set((nodeIds || []).map(String).filter(Boolean));
    if (!idSet.size) return;
    const NODE_REF = /^\{\{\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)\s*\}\}$/;
    const clearParams = (params, clearOutgoingRefs) => {
      if (!params || typeof params !== 'object' || Array.isArray(params)) return params;
      let changed = false;
      const next = { ...params };
      for (const [k, v] of Object.entries(params)) {
        if (typeof v !== 'string') continue;
        const m = NODE_REF.exec(v.trim());
        if (!m) continue;
        const srcId = m[1];
        if (idSet.has(srcId) || clearOutgoingRefs) {
          next[k] = '';
          changed = true;
        }
      }
      return changed ? next : params;
    };

    set(state => {
      const hist = takeFlowHistory(state);
      const nodes = { ...state.flow.nodes };
      let changed = false;

      for (const id of Object.keys(nodes)) {
        const prev = nodes[id];
        let nextNode = prev;
        const touch = () => {
          if (nextNode === prev) nextNode = { ...prev };
        };

        if (idSet.has(id)) {
          touch();
          for (const k of ['next', 'then', 'else', 'body', 'catch', 'finally']) nextNode[k] = null;
          if (nextNode.type === 'switch') {
            const params = { ...(nextNode.params || {}) };
            if (Array.isArray(params.cases)) {
              params.cases = params.cases.map(c =>
                c && typeof c === 'object' ? { ...c, node_id: '' } : c
              );
            }
            params.default = '';
            nextNode.params = params;
            nextNode.next = null;
          }
          const cleared = clearParams(nextNode.params || {}, true);
          if (cleared !== (nextNode.params || {})) {
            nextNode.params = cleared;
          }
          changed = true;
        } else {
          for (const k of ['next', 'then', 'else', 'body', 'catch', 'finally']) {
            if (prev[k] && idSet.has(prev[k])) {
              touch();
              nextNode[k] = null;
              changed = true;
            }
          }
          if (prev.type === 'switch' && prev.params) {
            const params = { ...prev.params };
            let paramsChanged = false;
            if (Array.isArray(params.cases)) {
              params.cases = params.cases.map(c => {
                if (c?.node_id && idSet.has(c.node_id)) {
                  paramsChanged = true;
                  return { ...c, node_id: '' };
                }
                return c;
              });
            }
            if (params.default && idSet.has(params.default)) {
              params.default = '';
              paramsChanged = true;
            }
            if (paramsChanged) {
              touch();
              nextNode.params = params;
              changed = true;
            }
          }
          const cleared = clearParams(prev.params || {}, false);
          if (cleared !== (prev.params || {})) {
            touch();
            nextNode.params = cleared;
            changed = true;
          }
        }
        if (nextNode !== prev) nodes[id] = nextNode;
      }

      if (!changed) return state;
      return {
        ...hist,
        flow: { ...state.flow, nodes }
      };
    });
    get().appendAuditLog?.(`断开节点连线`, { node_ids: [...idSet] });
  },

  updateNodePosition: (nodeId, position) =>
    set(state => {
      const node = state.flow.nodes[nodeId];
      if (!node) return state;
      return {
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [nodeId]: { ...node, position }
          }
        }
      };
    }),

  updateNodePositions: updates =>
    set(state => {
      if (!updates?.length) return state;
      const nodes = { ...state.flow.nodes };
      for (const u of updates) {
        const node = nodes[u.id];
        if (!node) continue;
        nodes[u.id] = { ...node, position: { x: u.x, y: u.y } };
      }
      return { ...takeFlowHistory(state), flow: { ...state.flow, nodes } };
    }),

  setNodeLink: (sourceId, handle, targetId) => {
    const prev = get().flow?.nodes?.[sourceId];
    if (!prev || sourceId === targetId) return;
    set(state => {
      const node = state.flow.nodes[sourceId];
      if (!node) return state;
      if (sourceId === targetId) return state; // 禁止自环
      const field = handle || 'next';

      // switch case:/default → write params (canvas ↔ inspector dual binding)
      if (node.type === 'switch' && String(field).startsWith('case:')) {
        const idx = Number(String(field).slice(5));
        if (!Number.isFinite(idx) || idx < 0) return state;
        const cases = Array.isArray(node.params?.cases) ? node.params.cases.map(c => ({ ...c })) : [];
        while (cases.length <= idx) cases.push({ name: '', value: '', node_id: '' });
        cases[idx] = {
          ...cases[idx],
          name: cases[idx].name || '',
          value: cases[idx].value || '',
          node_id: targetId
        };
        return {
          ...takeFlowHistory(state),
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                params: { ...(node.params || {}), cases }
              }
            }
          }
        };
      }
      if (node.type === 'switch' && field === 'default') {
        return {
          ...takeFlowHistory(state),
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                next: targetId,
                params: { ...(node.params || {}), default: targetId }
              }
            }
          }
        };
      }

      return {
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [sourceId]: { ...node, [field]: targetId }
          }
        }
      };
    });
    get().appendAuditLog?.(`连接节点`, {
      source: sourceId,
      handle: handle || 'next',
      target: targetId
    });
  },

  removeNodeLink: (sourceId, handle) => {
    if (!get().flow?.nodes?.[sourceId]) return;
    set(state => {
      const node = state.flow.nodes[sourceId];
      if (!node) return state;
      const field = handle || 'next';

      if (node.type === 'switch' && String(field).startsWith('case:')) {
        const idx = Number(String(field).slice(5));
        if (!Number.isFinite(idx) || idx < 0) return state;
        const cases = Array.isArray(node.params?.cases) ? node.params.cases.map(c => ({ ...c })) : [];
        if (cases[idx]) cases[idx] = { ...cases[idx], node_id: '' };
        return {
          ...takeFlowHistory(state),
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                params: { ...(node.params || {}), cases }
              }
            }
          }
        };
      }
      if (node.type === 'switch' && field === 'default') {
        return {
          ...takeFlowHistory(state),
          flow: {
            ...state.flow,
            nodes: {
              ...state.flow.nodes,
              [sourceId]: {
                ...node,
                next: null,
                params: { ...(node.params || {}), default: '' }
              }
            }
          }
        };
      }

      return {
        ...takeFlowHistory(state),
        flow: {
          ...state.flow,
          nodes: {
            ...state.flow.nodes,
            [sourceId]: { ...node, [field]: null }
          }
        }
      };
    });
    get().appendAuditLog?.(`断开连接`, {
      source: sourceId,
      handle: handle || 'next'
    });
  },

  deleteNodes: ids => {
    const idList = Array.isArray(ids) ? ids : [];
    set(state => {
      const idSet = new Set(idList);
      if (!idSet.size) return state;
      let removed = 0;
      for (const id of idSet) {
        if (state.flow.nodes[id]) removed += 1;
      }
      if (!removed) return state;
      // Snapshot before mutating node link fields
      const hist = takeFlowHistory(state);
      const nodes = { ...state.flow.nodes };
      for (const id of idSet) delete nodes[id];
      for (const id of Object.keys(nodes)) {
        const prev = nodes[id];
        let nextNode = prev;
        for (const key of ['next', 'then', 'else', 'body', 'catch', 'finally']) {
          if (prev[key] && idSet.has(prev[key])) {
            if (nextNode === prev) nextNode = { ...prev };
            nextNode[key] = null;
          }
        }
        if (prev.type === 'switch' && prev.params) {
          const params = { ...prev.params };
          let paramsChanged = false;
          if (Array.isArray(params.cases)) {
            params.cases = params.cases.map(c => (c?.node_id && idSet.has(c.node_id) ? { ...c, node_id: '' } : c));
            paramsChanged = true;
          }
          if (params.default && idSet.has(params.default)) {
            params.default = '';
            paramsChanged = true;
          }
          if (paramsChanged) {
            if (nextNode === prev) nextNode = { ...prev };
            nextNode.params = params;
          }
        }
        if (nextNode !== prev) nodes[id] = nextNode;
      }
      let entry = state.flow.entry;
      if (entry && idSet.has(entry)) {
        entry = Object.keys(nodes)[0] || null;
      }
      return {
        ...hist,
        flow: { ...state.flow, nodes, entry },
        selectedNodeId: idSet.has(state.selectedNodeId) ? null : state.selectedNodeId
      };
    });
    if (idList.length) {
      get().appendAuditLog?.(`删除节点 ×${idList.length}`, { node_ids: idList });
    }
  },

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

    const remap = v => (v && idMap[v] ? idMap[v] : v && mappedIds.includes(v) ? null : v);

    set(s => {
      const nodes = { ...s.flow.nodes };
      for (const oldId of mappedIds) {
        const src = srcNodes[oldId];
        const newId = idMap[oldId];
        const pos = src.position || { x: 100, y: 100 };
        const copy = {
          ...cloneValue(src),
          position: { x: pos.x + offset.x, y: pos.y + offset.y }
        };
        for (const key of ['next', 'then', 'else', 'body', 'catch', 'finally']) {
          if (copy[key]) copy[key] = idMap[copy[key]] || null;
        }
        if (copy.type === 'switch' && copy.params) {
          const params = { ...copy.params };
          if (Array.isArray(params.cases)) {
            params.cases = params.cases.map(c => ({
              ...c,
              node_id: c?.node_id && idMap[c.node_id] ? idMap[c.node_id] : c?.node_id || ''
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
        ...takeFlowHistory(s),
        flow: { ...s.flow, nodes },
        selectedNodeId: idMap[ids[ids.length - 1]] || s.selectedNodeId
      };
    });
    return mappedIds.map(id => idMap[id]);
  },

  setEntry: entry => {
    set(state => ({
      ...takeFlowHistory(state),
      flow: { ...state.flow, entry }
    }));
    get().appendAuditLog?.(`设置入口节点`, { entry });
  },

  // execution UI
  nodeOutputs: {}, // nodeId -> last summarized result (UI only)
  pendingDoneLogs: [], // 本次运行中各节点配置的完成日志摘要，flow_finished 时拼进完成日志并清空
  debugContext: {}, // runtime context snapshot at breakpoint
  clearLogs: () => set({ logs: [], runLog: null }),
  appendLog: entry =>
    set(state => {
      const category = normalizeLogCategory(entry.category, 'runtime');
      const nodeId = entry.nodeId || undefined;
      const nodeName =
        entry.nodeName || (nodeId ? resolveNodeName(state, nodeId) : '') || undefined;
      const row = {
        ...entry,
        category,
        nodeId,
        nodeName,
        scope: entry.scope || (nodeId ? 'node' : 'run'),
        detail: entry.detail !== undefined ? summarizeDetail(entry.detail) : undefined,
        ts: entry.ts || Date.now()
      };
      return {
        logs: [...state.logs.slice(-(MAX_LOGS - 1)), row]
      };
    }),
  appendAuditLog: (message, detail) => {
    const msg = String(message || '');
    get().appendLog({
      level: 'info',
      category: 'audit',
      scope: 'flow',
      message: msg,
      detail: detail !== undefined ? summarizeDetail(detail) : undefined
    });
    emitAuditToBridge(msg, detail);
  },
  onRuntimeEvent: (event, payload) => {
    const appendLog = get().appendLog;
    const cat = eventCategory(event, payload);
    if (event === 'node_start') {
      const nid = payload.node_id;
      const nodeName = resolveNodeName(get(), nid);
      set(state => ({
        // Don't clobber pause/stopping if a late event races the control channel.
        execStatus: state.execStatus === 'stopping' ? 'stopping' : 'running',
        execNodeId: nid,
        execNodeStates: { ...state.execNodeStates, [nid]: 'running' }
      }));
      appendLog({
        level: 'info',
        category: 'runtime',
        scope: 'node',
        nodeId: nid,
        nodeName: nodeName || undefined,
        message: `▶ [${formatNodeTag(nid, nodeName)}] ${payload.type}`,
        detail: summarizeDetail(payload.params)
      });
    } else if (event === 'node_end') {
      const result = summarizeDetail(payload.result || {}) || {};
      const nid = payload.node_id;
      const nodeName = resolveNodeName(get(), nid);
      // 完成日志模板：节点上手动填写的优先，否则回落到 Block SCHEMA 内置的代码级模板
      const node = get().flow.nodes?.[nid];
      const schemaDoneLog = String(get().schemaMap?.[node?.type]?.done_log || '').trim();
      const doneLogTemplate =
        payload.ok && !payload.stopped
          ? String(node?.config?.done_log || '').trim() || schemaDoneLog
          : '';
      const doneSummary = doneLogTemplate
        ? interpolateDoneLog(doneLogTemplate, payload.result || {})
        : '';
      set(state => {
        // Interrupted mid-node: leave idle — flow_stopped/finished clears UI; don't paint error.
        if (payload.stopped) {
          const next = { ...state.execNodeStates };
          delete next[nid];
          return { execNodeStates: next };
        }
        return {
          execNodeStates: {
            ...state.execNodeStates,
            [nid]: payload.ok ? 'done' : 'error'
          },
          nodeOutputs: payload.ok ? { ...state.nodeOutputs, [nid]: result } : state.nodeOutputs,
          pendingDoneLogs: doneSummary
            ? [...state.pendingDoneLogs, doneSummary]
            : state.pendingDoneLogs
        };
      });
      appendLog({
        level: payload.ok ? 'ok' : payload.stopped ? 'warn' : 'error',
        category: 'runtime',
        scope: 'node',
        nodeId: nid,
        nodeName: nodeName || undefined,
        message: formatRuntimeNodeEnd({ ...payload, result }, nodeName),
        detail: payload.ok ? result : summarizeDetail(payload.error)
      });
    } else if (event === 'flow_breakpoint') {
      const nid = payload?.node_id;
      const nodeName = resolveNodeName(get(), nid);
      set({
        execStatus: 'breakpoint',
        execNodeId: nid || null,
        debugMode: true,
        debugContext: payload?.context && typeof payload.context === 'object' ? payload.context : {}
      });
      const reason = payload?.reason === 'step' ? '单步暂停' : '命中断点';
      appendLog({
        level: 'warn',
        category: 'runtime',
        scope: 'run',
        nodeId: nid,
        nodeName: nodeName || undefined,
        message: `${reason} · 待执行 [${formatNodeTag(nid, nodeName)}]`,
        detail: payload?.context ? summarizeDetail(payload.context) : undefined
      });
    } else if (event === 'flow_debug') {
      set({ debugMode: true });
      const n = (payload?.breakpoints || []).length;
      appendLog({
        level: 'info',
        category: 'runtime',
        scope: 'run',
        message: payload?.step_first
          ? '调试已启动（单步：将在首个节点暂停）'
          : `调试运行中${n ? `（${n} 个断点）` : '（无断点，可随时单步暂停）'}`
      });
    } else if (event === 'flow_stepping') {
      appendLog({ level: 'info', category: 'runtime', scope: 'run', message: '将在下一节点暂停…' });
    } else if (event === 'flow_paused') {
      set({ execStatus: 'paused' });
      appendLog({ level: 'warn', category: 'runtime', scope: 'run', message: '流程已暂停' });
    } else if (event === 'flow_resumed') {
      set({ execStatus: 'running' });
      appendLog({ level: 'info', category: 'runtime', scope: 'run', message: '流程已继续' });
    } else if (event === 'flow_stopping') {
      const prev = get().execStatus;
      if (prev === 'idle') {
        // Late/stale stop after session already ended — ignore.
        return;
      }
      set({ execStatus: 'stopping' });
      appendLog({ level: 'warn', category: 'runtime', scope: 'run', message: '正在停止流程…' });
    } else if (event === 'flow_stopped') {
      // Backend still finishing the worker thread — keep Stop/busy until flow_finished.
      set(state => ({
        execStatus: state.execStatus === 'idle' ? 'idle' : 'stopping'
      }));
      // Avoid duplicate log if flow_stopping already arrived
      if (get().execStatus !== 'idle' && get().logs.slice(-1)[0]?.message !== '正在停止流程…') {
        appendLog({ level: 'warn', category: 'runtime', scope: 'run', message: '正在停止流程…' });
      }
    } else if (event === 'flow_finished') {
      const doneSummaries = get().pendingDoneLogs;
      // Keep only the selected node's output for Inspector; drop the rest.
      set(state => {
        const keepId = state.selectedNodeId;
        const slim = keepId && state.nodeOutputs[keepId] ? { [keepId]: state.nodeOutputs[keepId] } : {};
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
          pendingDoneLogs: [],
          debugContext: {},
          runLog: payload?.run_log || state.runLog
        };
      });
      // flow_stopped/stopping already logged when user clicked stop; avoid duplicate.
      if (payload.forced) {
        appendLog({
          level: 'warn',
          category: 'system',
          scope: 'app',
          message: '流程状态已强制重置'
        });
      } else if (!payload.stopped) {
        appendLog({
          level: payload.ok ? 'ok' : 'error',
          category: 'runtime',
          scope: 'run',
          message: payload.ok
            ? doneSummaries.length
              ? `流程执行完成；${doneSummaries.join('；')}`
              : '流程执行完成'
            : `流程结束: ${payload.error || '失败'}`
        });
      } else {
        appendLog({ level: 'warn', category: 'runtime', scope: 'run', message: '流程已停止' });
      }
      if (!payload.forced) {
        get().pushRunHistory({
          id: Math.random().toString(36).slice(2, 9),
          timestamp: new Date().toLocaleTimeString(),
          status: payload.ok ? 'completed' : payload.stopped ? 'stopped' : 'failed',
          workflowName: get().flow.name || '未命名流程'
        });
      }
    } else if (event === 'force_reset') {
      set({
        execStatus: 'idle',
        execNodeId: null,
        execNodeStates: {},
        runLog: payload?.run_log || get().runLog
      });
    } else if (event === 'recording_stopped') {
      if (payload?.ok && payload.nodes?.length && !payload.forced) {
        get().appendRecordedNodes(payload.nodes);
      }
      if (payload?.forced) {
        appendLog({
          level: 'warn',
          category: 'audit',
          scope: 'flow',
          message: '录制已强制结束（未追加节点）'
        });
        return;
      }
      const nodes = payload?.nodes || [];
      const clicks = nodes.filter(n => n?.type === 'click');
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
        category: 'audit',
        scope: 'flow',
        message: `停止录制，追加 ${nodes.length || 0} 个节点${btnHint}`,
        detail: { count: nodes.length }
      });
    } else if (event === 'schedule_fired') {
      set(state => ({ scheduleRefreshToken: (state.scheduleRefreshToken || 0) + 1 }));
      appendLog({
        level: 'ok',
        category: 'runtime',
        scope: 'run',
        message: `定时任务已触发：${payload?.job_id || ''}`
      });
    } else if (event === 'schedule_pending') {
      set(state => ({ scheduleRefreshToken: (state.scheduleRefreshToken || 0) + 1 }));
      appendLog({
        level: 'warn',
        category: 'runtime',
        scope: 'run',
        message: `定时任务等待补跑：${payload?.job_id || ''}`
      });
    } else if (event === 'schedule_error') {
      set(state => ({ scheduleRefreshToken: (state.scheduleRefreshToken || 0) + 1 }));
      appendLog({
        level: 'error',
        category: 'runtime',
        scope: 'run',
        message: `定时任务失败：${payload?.job_id || ''} ${payload?.error || ''}`.trim()
      });
    } else if (event === 'plugin_mode_changed') {
      set(state => ({
        pluginModeRemote: {
          enabled: !!payload?.enabled,
          opacity: Number(payload?.opacity ?? 0.85),
          click_through: !!payload?.click_through,
          on_top: !!payload?.on_top,
          rev: (state.pluginModeRemote?.rev || 0) + 1
        }
      }));
      appendLog({
        level: 'info',
        category: 'system',
        scope: 'app',
        message: payload?.enabled ? '插件模式已开启' : '插件模式已关闭',
        detail: summarizeDetail({
          opacity: payload?.opacity,
          click_through: payload?.click_through
        })
      });
    } else if (event === 'log') {
      const nid = payload?.node_id || payload?.nodeId || undefined;
      const nodeName = nid ? resolveNodeName(get(), nid) : '';
      appendLog({
        level: payload?.level || 'info',
        category: cat,
        scope: payload?.scope || (nid ? 'node' : 'app'),
        nodeId: nid,
        nodeName: nodeName || undefined,
        message: nid
          ? `[${formatNodeTag(nid, nodeName)}] ${payload?.message || ''}`
          : payload?.message || '',
        detail: summarizeDetail(payload?.detail)
      });
    }
  }
}));

export function flowToJson(flow) {
  return JSON.stringify(flow, null, 2);
}
