/**
 * CanvasFlow UI shell wired to Nexuz store + bridge.
 * Unused design-only UI (AI Assistant, demo templates) kept as-is.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react';
import Toolbar from './components/Toolbar';
import Sidebar from './components/Sidebar';
import Canvas from './components/Canvas';
import Inspector from './components/Inspector';
import CodeEditor from './components/CodeEditor';
import AIAssistant from './components/AIAssistant';
import SaveNameDialog from './components/SaveNameDialog';
import RecordingBanner from './components/RecordingBanner';
import RunningBanner from './components/RunningBanner';
import SettingsPage from './components/SettingsPage';
import FlowchartView from './components/FlowchartView';
import DebugBar from './components/DebugBar';
import DebugWatchPanel from './components/DebugWatchPanel';
import { AppDialogProvider, useAppDialog } from './components/AppDialogs';
import { UpdateDialogProvider, useUpdateDialog } from './components/UpdateDialog';
import { useScreenshotPick } from './hooks/useScreenshotPick';
import { getThemeColors } from './theme';
import {
  applyDefaultCaptureMode,
  applyDefaultCoordinateMode,
  applyDefaultOutputCoordinateMode,
  dataOutField,
  formatNodeRef,
  collectDownstreamNodeIds,
  flowToCanvas,
  isDataOutSocket,
  isParamInSocket,
  listBindableParams,
  mapLogLevel,
  paramInName,
  pickBestBindParam,
} from './nexuzAdapter';
import { parseNodeRef } from './bindValue';
import { collectFlowBindIssues } from './bindValidate';
import { DEFAULT_HOTKEYS, formatHotkeyLabel, useFlowStore } from '../../src/store/flowModelStore';
import { bridge, waitForBridge, MOCK_SCHEMAS } from '../../src/bridge';
import WindowResizeHandles from './components/WindowResizeHandles';
import RunMonitorView from './components/RunMonitorView';
import SplitHandle from './components/SplitHandle';

function loadPanelCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function persistPanelCollapsed(key: string, collapsed: boolean) {
  try {
    localStorage.setItem(key, collapsed ? '1' : '0');
  } catch {
    /* ignore */
  }
}

function loadPanelSize(key: string, fallback: number, min: number, max: number): number {
  try {
    const n = Number(localStorage.getItem(key));
    if (Number.isFinite(n)) return Math.min(max, Math.max(min, Math.round(n)));
  } catch {
    /* ignore */
  }
  return fallback;
}

function persistPanelSize(key: string, value: number) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* ignore */
  }
}

const LEFT_CONTENT_WIDTH_KEY = 'nexuz.leftPanelContentWidth';
const RIGHT_PANEL_WIDTH_KEY = 'nexuz.rightPanelWidth';
const DEFAULT_LEFT_CONTENT_WIDTH = 280;
const DEFAULT_RIGHT_PANEL_WIDTH = 384;
const MIN_LEFT_CONTENT_WIDTH = 200;
const MAX_LEFT_CONTENT_WIDTH = 520;
const MIN_RIGHT_PANEL_WIDTH = 280;
const MAX_RIGHT_PANEL_WIDTH = 640;

async function readNoticeReadId(): Promise<string> {
  try {
    const res = await bridge.getNoticeReadId?.();
    if (res?.ok && res.id) return String(res.id);
  } catch {
    /* ignore */
  }
  try {
    return localStorage.getItem('nexuz.noticeReadId') || '';
  } catch {
    return '';
  }
}

async function writeNoticeReadId(id: string): Promise<void> {
  const value = String(id || '');
  try {
    await bridge.setNoticeReadId?.(value);
  } catch {
    /* ignore */
  }
  try {
    localStorage.setItem('nexuz.noticeReadId', value);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new CustomEvent('nexuz-notice-read', { detail: { id: value } }));
}

const REQUIRED_BLOCK_TYPES = [
  'ocr_recognize',
  'if_text_contains',
  'find_image',
  'color_detect',
  'if_color_match',
  'if_logic',
  'screenshot',
  'wait_until',
  'schedule_trigger',
  'call_subflow',
];

function mergeSchemas(list: any[] | null | undefined) {
  const byType = new Map<string, any>();
  for (const s of MOCK_SCHEMAS) byType.set(s.type, s);
  for (const s of list || []) {
    if (s?.type) byType.set(s.type, s);
  }
  // Ensure P1 vision blocks always visible even if backend registry is stale
  for (const t of REQUIRED_BLOCK_TYPES) {
    const mock = MOCK_SCHEMAS.find((s) => s.type === t);
    if (mock && !byType.has(t)) byType.set(t, mock);
  }
  return Array.from(byType.values());
}

function applyCssVars(colors: ReturnType<typeof getThemeColors>, themeMode: string) {
  const root = document.documentElement;
  root.classList.toggle('dark', themeMode === 'dark');
  root.style.setProperty('--background', colors.background);
  root.style.setProperty('--foreground', colors.text);
  root.style.setProperty('--primary', colors.primary);
  root.style.setProperty('--primary-foreground', '#ffffff');
  root.style.setProperty('--muted-foreground', colors.secondaryText);
  root.style.setProperty('--destructive', colors.danger);
  root.style.setProperty('--ring', colors.primary);
  root.style.setProperty('--card', colors.surface);
  root.style.setProperty('--card-foreground', colors.text);
  root.style.setProperty('--border', colors.border);
  const popoverBg = themeMode === 'dark' ? 'rgba(18, 22, 35, 0.98)' : 'rgba(255, 255, 255, 0.98)';
  root.style.setProperty('--popover', popoverBg);
  root.style.setProperty('--popover-foreground', colors.text);
}

let themeTransitionTimer: number | undefined;

/** Enable color transitions only for the duration of a theme change. */
function withThemeTransition(update: () => void) {
  const root = document.documentElement;
  root.classList.add('theme-transitioning');
  // Force style flush so the next paint interpolates from current colors.
  void root.offsetWidth;
  update();
  window.clearTimeout(themeTransitionTimer);
  themeTransitionTimer = window.setTimeout(() => {
    root.classList.remove('theme-transitioning');
  }, 420);
}

export default function App() {
  return (
    <AppDialogProvider>
      <UpdateDialogProvider>
        <AppShell />
      </UpdateDialogProvider>
    </AppDialogProvider>
  );
}

function AppShell() {
  const { confirm, alert } = useAppDialog();
  const { openUpdate } = useUpdateDialog();
  const flow = useFlowStore((s) => s.flow);
  const schemas = useFlowStore((s) => s.schemas);
  const schemaMap = useFlowStore((s) => s.schemaMap);
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const selectNode = useFlowStore((s) => s.selectNode);
  const viewMode = useFlowStore((s) => s.viewMode);
  const lastFlowViewMode = useFlowStore((s) =>
    s.lastFlowViewMode === 'code' || s.lastFlowViewMode === 'flowchart'
      ? s.lastFlowViewMode
      : 'canvas',
  );
  const hideSidePanelsOnSettings = useFlowStore(
    (s) => s.hideSidePanelsOnSettings !== false,
  );
  const settingsFocus = viewMode === 'settings' && hideSidePanelsOnSettings;
  const setViewMode = useFlowStore((s) => s.setViewMode);
  const [settingsExpandSection, setSettingsExpandSection] = useState<'ai' | null>(null);
  useEffect(() => {
    if (viewMode !== 'settings') setSettingsExpandSection(null);
  }, [viewMode]);
  const themeName = useFlowStore((s) => s.themeName);
  const themeMode = useFlowStore((s) => s.themeMode);
  const setThemeName = useFlowStore((s) => s.setThemeName);
  const setThemeMode = useFlowStore((s) => s.setThemeMode);
  const execStatus = useFlowStore((s) => s.execStatus);
  const execNodeId = useFlowStore((s) => s.execNodeId);
  const execNodeStates = useFlowStore((s) => s.execNodeStates);
  const debugMode = useFlowStore((s) => s.debugMode);
  const toggleDebugMode = useFlowStore((s) => s.toggleDebugMode);
  const toggleBreakpoint = useFlowStore((s) => s.toggleBreakpoint);
  const nodeOutputs = useFlowStore((s) => s.nodeOutputs);
  const logs = useFlowStore((s) => s.logs);
  const runLog = useFlowStore((s) => s.runLog);
  const runHistory = useFlowStore((s) => s.runHistory);
  const clearRunHistory = useFlowStore((s) => s.clearRunHistory);
  const filePath = useFlowStore((s) => s.filePath);
  const hideWindowOnRecord = useFlowStore((s) => s.hideWindowOnRecord);
  const autoSaveEnabled = useFlowStore((s) => s.autoSaveEnabled);
  const autoSaveIntervalSec = useFlowStore((s) => s.autoSaveIntervalSec);
  const saveAfterRun = useFlowStore((s) => s.saveAfterRun);
  const hotkeys = useFlowStore((s) => s.hotkeys);
  const hotkeyLabels = useMemo(() => {
    const h = hotkeys || DEFAULT_HOTKEYS;
    return {
      start_run: formatHotkeyLabel(h.start_run) || 'X+F3',
      stop_run: formatHotkeyLabel(h.stop_run) || 'X+F4',
      pause_run: formatHotkeyLabel(h.pause_run) || 'X+F5',
      record_stop: formatHotkeyLabel(h.record_stop) || 'X+F10',
    };
  }, [hotkeys]);
  const recordStopLabel = hotkeyLabels.record_stop;
  const defaultCaptureMode = useFlowStore((s) => s.defaultCaptureMode);
  const defaultPickMethod = useFlowStore((s) => s.defaultPickMethod);
  const defaultCoordinateMode = useFlowStore((s) => s.defaultCoordinateMode);
  const defaultOutputCoordinateMode = useFlowStore((s) => s.defaultOutputCoordinateMode);
  const defaultNodeIntervalMs = useFlowStore((s) => s.defaultNodeIntervalMs);
  const [leftCollapsed, setLeftCollapsed] = useState(() =>
    loadPanelCollapsed('nexuz.leftPanelCollapsed'),
  );
  const [rightCollapsed, setRightCollapsed] = useState(() =>
    loadPanelCollapsed('nexuz.rightPanelCollapsed'),
  );
  const [leftContentWidth, setLeftContentWidth] = useState(() =>
    loadPanelSize(
      LEFT_CONTENT_WIDTH_KEY,
      DEFAULT_LEFT_CONTENT_WIDTH,
      MIN_LEFT_CONTENT_WIDTH,
      MAX_LEFT_CONTENT_WIDTH,
    ),
  );
  const [rightPanelWidth, setRightPanelWidth] = useState(() =>
    loadPanelSize(
      RIGHT_PANEL_WIDTH_KEY,
      DEFAULT_RIGHT_PANEL_WIDTH,
      MIN_RIGHT_PANEL_WIDTH,
      MAX_RIGHT_PANEL_WIDTH,
    ),
  );
  const toggleLeftPanel = useCallback(() => {
    setLeftCollapsed((prev) => {
      const next = !prev;
      persistPanelCollapsed('nexuz.leftPanelCollapsed', next);
      return next;
    });
  }, []);
  const toggleRightPanel = useCallback(() => {
    setRightCollapsed((prev) => {
      const next = !prev;
      persistPanelCollapsed('nexuz.rightPanelCollapsed', next);
      return next;
    });
  }, []);
  const {
    pickPoint: screenshotPickPoint,
    pickRegion: screenshotPickRegion,
    captureTemplate: screenshotCaptureTemplate,
    dialog: screenPickDialog,
  } = useScreenshotPick({ hideWindow: hideWindowOnRecord });

  const runCoordPick = useCallback(
    (kind: 'point' | 'region' | 'template', method?: string) => {
      const m = method === 'live' || method === 'screenshot' ? method : defaultPickMethod;
      if (m === 'live') {
        if (kind === 'point') {
          return bridge.pickPoint(hideWindowOnRecord, defaultCoordinateMode || 'window_client');
        }
        if (kind === 'region') return bridge.pickRegion(hideWindowOnRecord);
        return bridge.captureTemplate(hideWindowOnRecord);
      }
      if (kind === 'point') return screenshotPickPoint();
      if (kind === 'region') return screenshotPickRegion();
      return screenshotCaptureTemplate();
    },
    [
      defaultPickMethod,
      defaultCoordinateMode,
      hideWindowOnRecord,
      screenshotPickPoint,
      screenshotPickRegion,
      screenshotCaptureTemplate,
    ],
  );

  const setSchemas = useFlowStore((s) => s.setSchemas);
  const setBridgeReady = useFlowStore((s) => s.setBridgeReady);
  const updateFlowMeta = useFlowStore((s) => s.updateFlowMeta);
  const addNodeFromSchema = useFlowStore((s) => s.addNodeFromSchema);
  const updateNodeParams = useFlowStore((s) => s.updateNodeParams);
  const updateNodeName = useFlowStore((s) => s.updateNodeName);
  const setNodeCollapsed = useFlowStore((s) => s.setNodeCollapsed);
  const setNodesCollapsed = useFlowStore((s) => s.setNodesCollapsed);
  const setBreakpointsForNodes = useFlowStore((s) => s.setBreakpointsForNodes);
  const setNodesDisabled = useFlowStore((s) => s.setNodesDisabled);
  const disconnectNodes = useFlowStore((s) => s.disconnectNodes);
  const clearNodesFlowOuts = useFlowStore((s) => s.clearNodesFlowOuts);
  const updateNodePosition = useFlowStore((s) => s.updateNodePosition);
  const setNodeLink = useFlowStore((s) => s.setNodeLink);
  const removeNodeLink = useFlowStore((s) => s.removeNodeLink);
  const deleteNodes = useFlowStore((s) => s.deleteNodes);
  const duplicateNodes = useFlowStore((s) => s.duplicateNodes);
  const updateNodePositions = useFlowStore((s) => s.updateNodePositions);
  const setFlow = useFlowStore((s) => s.setFlow);
  const undo = useFlowStore((s) => s.undo);
  const redo = useFlowStore((s) => s.redo);
  const canUndo = useFlowStore((s) => (s.past?.length || 0) > 0);
  const canRedo = useFlowStore((s) => (s.future?.length || 0) > 0);
  const clearLogs = useFlowStore((s) => s.clearLogs);
  const appendLog = useFlowStore((s) => s.appendLog);
  const onRuntimeEvent = useFlowStore((s) => s.onRuntimeEvent);
  const appendRecordedNodes = useFlowStore((s) => s.appendRecordedNodes);

  const [isAssistantOpen, setIsAssistantOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingMode, setRecordingMode] = useState<'coord' | 'frida_ui'>('coord');
  const [runMonitorActive, setRunMonitorActive] = useState(false);
  const [runMonitorFlowName, setRunMonitorFlowName] = useState('');
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [flowsRefreshToken, setFlowsRefreshToken] = useState(0);

  const colors = getThemeColors(themeName as any, themeMode as any);
  // paused / stopping / stepping still own the interpreter — must not start a second run
  const isBusy =
    execStatus === 'running' ||
    execStatus === 'paused' ||
    execStatus === 'stopping' ||
    execStatus === 'breakpoint';
  const isExecuting = isBusy;

  useEffect(() => {
    applyCssVars(colors, themeMode);
  }, [themeName, themeMode, colors]);

  const handleSetThemeMode = (nextMode: string) => {
    const next = (nextMode === 'light' ? 'light' : 'dark') as 'light' | 'dark';
    withThemeTransition(() => {
      applyCssVars(getThemeColors(themeName as any, next), next);
      setThemeMode(next);
    });
  };

  const handleSetThemeName = (name: string) => {
    withThemeTransition(() => {
      applyCssVars(getThemeColors(name as any, themeMode as any), themeMode);
      setThemeName(name);
    });
  };

  const bindIssues = useMemo(
    () => collectFlowBindIssues(flow, schemaMap),
    [flow, schemaMap],
  );

  // Avoid stuffing every nodeOutputs blob into the canvas graph — Inspector
  // reads the selected node's output separately, which cuts React retention.
  const { nodes, connections } = useMemo(() => {
    const base = flowToCanvas(flow, schemaMap, execNodeStates, execNodeId, {});
    const errCount = new Map<string, number>();
    for (const iss of bindIssues) {
      if (iss.level !== 'error') continue;
      errCount.set(iss.nodeId, (errCount.get(iss.nodeId) || 0) + 1);
    }
    const issueByConn = new Map<string, 'broken' | 'type_warn'>();
    for (const iss of bindIssues) {
      if (!iss.sourceId || !iss.field) continue;
      const mark = iss.level === 'error' ? ('broken' as const) : ('type_warn' as const);
      const base = `${iss.sourceId}|${iss.nodeId}|${iss.field}`;
      issueByConn.set(`${base}|`, mark);
      if (iss.paramName) {
        issueByConn.set(`${base}|${iss.paramName}`, mark);
        const leaf = iss.paramName.includes('.')
          ? iss.paramName.slice(iss.paramName.lastIndexOf('.') + 1)
          : iss.paramName;
        issueByConn.set(`${base}|${leaf}`, mark);
      }
    }
    const nodes = base.nodes.map((n) => {
      const count = errCount.get(n.id) || 0;
      return count ? { ...n, bindErrorCount: count } : n;
    });
    const connections = base.connections.map((c) => {
      if (c.kind !== 'data') return c;
      const field = isDataOutSocket(c.sourceSocketId)
        ? dataOutField(c.sourceSocketId)
        : (c.label || '').split('→')[0];
      const param = isParamInSocket(c.targetSocketId)
        ? paramInName(c.targetSocketId)
        : '';
      const base = `${c.sourceNodeId}|${c.targetNodeId}|${field}`;
      const hit =
        (param && issueByConn.get(`${base}|${param}`)) || issueByConn.get(`${base}|`);
      if (!hit) return c;
      return { ...c, bindIssue: hit };
    });
    return { nodes, connections };
  }, [flow, schemaMap, execNodeStates, execNodeId, bindIssues]);

  const selectedNode = useMemo(() => {
    const n = nodes.find((node) => node.id === selectedNodeId) || null;
    if (!n) return null;
    const outputData = nodeOutputs[n.id] ?? null;
    return outputData ? { ...n, outputData } : n;
  }, [nodes, selectedNodeId, nodeOutputs]);

  const canvasLogs = useMemo(
    () =>
      logs.map((l, i) => ({
        id: `${l.ts || 0}-${i}-${String(l.message || '').slice(0, 24)}`,
        timestamp: new Date(l.ts || Date.now()).toLocaleTimeString(),
        type: mapLogLevel(l.level),
        level: l.level,
        category: l.category || 'runtime',
        scope: l.scope,
        message: l.message,
        nodeId: l.nodeId || undefined,
        nodeName: undefined,
        detail: l.detail,
        ts: l.ts,
      })),
    [logs],
  );

  const handleRunWorkflowRef = useRef<() => void>(() => {});

  // Bridge boot + runtime events
  useEffect(() => {
    const handleRuntimeMessage = (msg: any) => {
      if (!msg) return;
      if (msg.event === 'update_download_progress') {
        window.dispatchEvent(
          new CustomEvent('nexuz-update-progress', { detail: msg.payload || {} }),
        );
      }
      if (msg.event === 'ai_progress') {
        window.dispatchEvent(
          new CustomEvent('nexuz-ai-progress', { detail: msg.payload || {} }),
        );
      }
      if (msg.event === 'hotkey_run') {
        if (msg.payload?.message) {
          appendLog({
            level: 'info',
            category: 'system',
            scope: 'app',
            message: String(msg.payload.message),
          });
        }
        void handleRunWorkflowRef.current?.();
        return;
      }
      // View switch only — pause/stop never depend on this.
      if (msg.event === 'flow_finished' || msg.event === 'force_reset') {
        setRunMonitorActive(false);
        setRunMonitorFlowName('');
      }
      onRuntimeEvent(msg.event, msg.payload || {});
    };
    (window as any).__nexuzEmit = handleRuntimeMessage;
    (window as any).__nexuzEmitBatch = (messages: any[]) => {
      if (!Array.isArray(messages)) return;
      for (const msg of messages) handleRuntimeMessage(msg);
    };
    let cancelled = false;
    let drainTimer: number | undefined;
    let drainBusy = false;
    const pollUiEvents = () => {
      if (cancelled || drainBusy) return;
      drainBusy = true;
      void bridge.drainUiEvents?.()
        .then((res: any) => {
          const messages = res?.messages;
          if (!Array.isArray(messages) || !messages.length) return;
          for (const msg of messages) handleRuntimeMessage(msg);
        })
        .catch(() => {})
        .finally(() => {
          drainBusy = false;
        });
    };
    (async () => {
      await waitForBridge(8000);
      if (cancelled) return;
      setBridgeReady(true);
      drainTimer = window.setInterval(pollUiEvents, 50);
      pollUiEvents();
      try {
        const keys = useFlowStore.getState().hotkeys || DEFAULT_HOTKEYS;
        await bridge.setHotkeys?.(keys);
      } catch {
        /* ignore */
      }
      try {
        let diag = false;
        try {
          diag = localStorage.getItem('nexuz.diagLogging') === '1';
        } catch {
          /* ignore */
        }
        await bridge.setDiagLogging?.(diag);
      } catch {
        /* ignore */
      }
      try {
        const ping = await bridge.ping();
        appendLog({
          level: 'info',
          category: 'system',
          scope: 'app',
          message: `桥接: ${ping?.message || 'ok'} (DPI ${ping?.dpi_scale ?? '?'})`,
        });
      } catch (e: any) {
        appendLog({
          level: 'error',
          category: 'system',
          scope: 'app',
          message: String(e),
        });
      }
      try {
        const info = await bridge.getAppInfo();
        if (info?.version) {
          appendLog({
            level: 'info',
            category: 'system',
            scope: 'app',
            message: `版本 ${info.version}`,
          });
        }
      } catch {
        /* ignore */
      }
      const list = await bridge.getBlockRegistry();
      if (!cancelled) {
        const merged = mergeSchemas(list);
        setSchemas(merged);
        const hasOcr = merged.some((s) => s.type === 'ocr_recognize');
        appendLog({
          level: 'info',
          category: 'system',
          scope: 'app',
          message: hasOcr
            ? `积木已加载 ${merged.length} 个（含 OCR / 找图）`
            : `积木已加载 ${merged.length} 个`,
        });
      }

      // Soft check: notice (sticky) + update
      if (!cancelled) {
        try {
          const res = await bridge.fetchNotice();
          const n = res?.notice;
          if (n?.id && n?.body) {
            const readId = await readNoticeReadId();
            if (String(n.id) !== readId) {
              await alert({
                title: n.title || '通知',
                description: String(n.body),
                okText: '我知道了',
              });
              await writeNoticeReadId(String(n.id));
            }
          }
        } catch {
          /* ignore network errors on boot */
        }
      }
      if (!cancelled) {
        let autoCheck = true;
        try {
          const v = localStorage.getItem('nexuz.autoCheckUpdate');
          if (v === '0' || v === 'false') autoCheck = false;
        } catch {
          /* ignore */
        }
        if (autoCheck) {
          try {
            const upd = await bridge.checkForUpdate();
            if (upd?.ok && upd.update_available) {
              appendLog({
                level: 'info',
                message: `有可用更新：${upd.current_version} → ${upd.latest_version}`,
              });
              await openUpdate(upd);
            }
          } catch {
            /* ignore */
          }
        }
      }
    })();
    return () => {
      cancelled = true;
      if (drainTimer != null) window.clearInterval(drainTimer);
      delete (window as any).__nexuzEmit;
      delete (window as any).__nexuzEmitBatch;
    };
  }, [onRuntimeEvent, setBridgeReady, setSchemas, appendLog, alert, openUpdate, setViewMode]);

  useEffect(() => {
    const last = logs[logs.length - 1];
    if (last?.message?.startsWith('快捷键停止录制')) setRecording(false);
  }, [logs]);

  const handleRunWorkflow = async () => {
    // At breakpoint / pause → continue (not a second run)
    if (execStatus === 'breakpoint' || execStatus === 'paused') {
      appendLog({ level: 'info', message: '继续运行…' });
      const res = await bridge.continueFlow();
      if (res?.ok === false) {
        appendLog({ level: 'error', message: res?.error || '继续失败' });
      }
      return;
    }
    if (execStatus === 'running' || execStatus === 'stopping') {
      appendLog({
        level: 'warn',
        message:
          execStatus === 'stopping'
            ? '正在停止中，请稍候…'
            : '流程正在运行，请先暂停/停止，或使用调试栏「单步」',
      });
      return;
    }
    clearLogs();
    const errN = bindIssues.filter((i) => i.level === 'error').length;
    if (errN > 0) {
      appendLog({
        level: 'error',
        message: `无法运行：有 ${errN} 个配置错误（如未取点、绑定失效），请先在画布/检查器中修复`,
      });
      return;
    }
    const bps = Array.isArray(flow.breakpoints) ? flow.breakpoints : [];
    const useDebug = !!debugMode;
    appendLog({
      level: 'info',
      message: useDebug
        ? `调试运行…${bps.length ? `（${bps.length} 个断点）` : '（无断点）'}`
        : hideWindowOnRecord
          ? '开始运行流程（已隐藏窗口，避免点击落到本程序上）…'
          : '开始运行流程…',
    });
    const prepared = applyDefaultOutputCoordinateMode(
      applyDefaultCoordinateMode(
        applyDefaultCaptureMode(flow, defaultCaptureMode),
        defaultCoordinateMode,
      ),
      defaultOutputCoordinateMode,
    );
    const runtimeFlow = { ...prepared, __global_node_interval_ms: defaultNodeIntervalMs };
    const payload = filePath ? { ...runtimeFlow, __file_path__: filePath } : runtimeFlow;
    const hide = hideWindowOnRecord && !useDebug;
    const res = await bridge.runFlow(payload, false, hide, useDebug, bps);
    if (res?.run_log) useFlowStore.setState({ runLog: res.run_log });
    if (res?.resumed) {
      appendLog({ level: 'info', message: '已继续暂停中的流程' });
      return;
    }
    if (!res?.ok) {
      appendLog({ level: 'error', message: res?.error || '启动失败' });
      return;
    }
    // Frontend-owned view switch (compact monitor). Pause/stop stay the same handlers.
    if (res?.run_monitor) {
      setRunMonitorActive(true);
      setRunMonitorFlowName(String(payload?.name || flow?.name || ''));
    }
  };
  handleRunWorkflowRef.current = () => {
    void handleRunWorkflow();
  };

  const handleStop = async () => {
    if (execStatus === 'idle') return;
    useFlowStore.setState({ execStatus: 'stopping' });
    appendLog({ level: 'warn', message: '正在停止流程…' });
    const res = await bridge.stopFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '停止失败' });
    }
  };

  const handleForceReset = async () => {
    // Unlock UI immediately even if the bridge is wedged.
    setRecording(false);
    setRunMonitorActive(false);
    setRunMonitorFlowName('');
    useFlowStore.setState({
      execStatus: 'idle',
      execNodeId: null,
      execNodeStates: {},
    });
    appendLog({ level: 'warn', message: '正在强制重置…' });
    try {
      const res = await Promise.race([
        bridge.forceReset(),
        new Promise((resolve) =>
          setTimeout(() => resolve({ ok: false, error: 'timeout' }), 4000),
        ),
      ]);
      if (res?.ok === false && res?.error === 'timeout') {
        appendLog({
          level: 'warn',
          message: '后端响应超时，界面已解锁；若仍异常请重启程序',
        });
        return;
      }
      appendLog({
        level: 'ok',
        message: (res as any)?.message || '已强制重置，可以重新运行',
      });
    } catch (e: any) {
      appendLog({
        level: 'warn',
        message: `界面已解锁（后端：${e?.message || e || '调用失败'}）`,
      });
    }
  };

  const handlePause = async () => {
    const res = await bridge.pauseFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '暂停失败' });
    }
  };

  const handleResume = async () => {
    const res = await bridge.continueFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '继续失败' });
    }
  };

  const handleToggleDebug = () => {
    const next = !debugMode;
    toggleDebugMode();
    appendLog({
      level: 'info',
      message: next
        ? '已开启调试：可在节点左侧设断点，使用画布上方调试栏'
        : '已关闭调试模式',
    });
  };

  const handleDebugStep = async () => {
    if (execStatus === 'stopping') {
      appendLog({ level: 'warn', message: '正在停止中，请稍候…' });
      return;
    }
    const bps = Array.isArray(flow.breakpoints) ? flow.breakpoints : [];

    // Already running / at BP → step one node
    if (
      execStatus === 'breakpoint' ||
      execStatus === 'paused' ||
      execStatus === 'running'
    ) {
      if (!debugMode) useFlowStore.setState({ debugMode: true });
      const res = await bridge.stepFlow();
      if (res?.ok === false) {
        appendLog({ level: 'error', message: res?.error || '单步失败' });
      }
      return;
    }

    // idle → start debug run, break before first node
    if (!debugMode) useFlowStore.setState({ debugMode: true });
    const errN = bindIssues.filter((i) => i.level === 'error').length;
    if (errN > 0) {
      appendLog({
        level: 'error',
        message: `无法调试：有 ${errN} 个配置错误，请先修复`,
      });
      return;
    }
    clearLogs();
    appendLog({ level: 'info', message: '调试单步启动：将在首个节点暂停…' });
    const prepared = applyDefaultOutputCoordinateMode(
      applyDefaultCoordinateMode(
        applyDefaultCaptureMode(flow, defaultCaptureMode),
        defaultCoordinateMode,
      ),
      defaultOutputCoordinateMode,
    );
    const runtimeFlow = { ...prepared, __global_node_interval_ms: defaultNodeIntervalMs };
    const payload = filePath ? { ...runtimeFlow, __file_path__: filePath } : runtimeFlow;
    const res = await bridge.runFlow(payload, true, false, true, bps);
    if (!res?.ok) {
      useFlowStore.setState({ execStatus: 'idle' });
      appendLog({ level: 'error', message: res?.error || '启动单步失败' });
    }
  };

  const handleToggleBreakpoint = useCallback(
    (nodeId: string) => {
      const before = new Set(
        (useFlowStore.getState().flow.breakpoints || []).map(String),
      );
      const adding = !before.has(nodeId);
      toggleBreakpoint(nodeId);
      queueMicrotask(() => {
        const bps = useFlowStore.getState().flow.breakpoints || [];
        const st = useFlowStore.getState().execStatus;
        if (st !== 'idle') {
          bridge.setBreakpoints(bps);
        }
        appendLog({
          level: 'info',
          message: adding ? `已设置断点: ${nodeId}` : `已取消断点: ${nodeId}`,
        });
      });
    },
    [toggleBreakpoint, appendLog],
  );

  const buildAutoFlowName = (curFlow: { name?: string; nodes?: Record<string, unknown> }) => {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const nodeCount = Object.keys(curFlow?.nodes || {}).length;
    return `${stamp}_${nodeCount}节点`;
  };

  const saveCurrentFlow = useCallback(
    async (mode: 'manual' | 'auto' | 'after_run' = 'manual') => {
      const state = useFlowStore.getState();
      const curFlow = state.flow;
      const path = state.filePath;
      if (!path) {
        if (mode === 'manual') {
          setSaveDialogOpen(true);
          return false;
        }
        if (mode === 'auto') {
          // Timed autosave still requires an existing file.
          return false;
        }
        // after_run: first-time save with auto name (time + node count)
        const autoName = buildAutoFlowName(curFlow);
        const payload = { ...curFlow, name: autoName };
        const res = await bridge.saveFlow(payload, null, autoName);
        if (res?.ok) {
          useFlowStore.setState({ filePath: res.path || null });
          updateFlowMeta({ name: res.name || autoName });
          setFlowsRefreshToken((n) => n + 1);
          appendLog({
            level: 'ok',
            message: `运行后已自动保存: ${res.name || autoName}`,
          });
          return true;
        }
        if (!res?.cancelled) {
          appendLog({ level: 'error', message: res?.error || '自动保存失败' });
        }
        return false;
      }
      const res = await bridge.saveFlow(curFlow, path, curFlow.name || null);
      if (res?.ok) {
        useFlowStore.setState({ filePath: res.path || path });
        if (res.name) updateFlowMeta({ name: res.name });
        setFlowsRefreshToken((n) => n + 1);
        if (mode === 'manual') {
          appendLog({ level: 'ok', message: `已保存: ${res.name || curFlow.name || '流程'}` });
        } else if (mode === 'after_run') {
          appendLog({
            level: 'ok',
            message: `运行后已自动保存: ${res.name || curFlow.name || '流程'}`,
          });
        } else {
          appendLog({
            level: 'info',
            message: `自动保存: ${res.name || curFlow.name || '流程'}`,
          });
        }
        return true;
      }
      if (!res?.cancelled) {
        appendLog({
          level: 'error',
          message: res?.error || (mode === 'manual' ? '保存失败' : '自动保存失败'),
        });
      }
      return false;
    },
    [appendLog, updateFlowMeta],
  );

  const handleSave = async () => saveCurrentFlow('manual');

  // Timed auto-save (only when flow already has a file path)
  useEffect(() => {
    if (!autoSaveEnabled) return;
    const sec = Math.min(3600, Math.max(10, Number(autoSaveIntervalSec) || 60));
    const timer = window.setInterval(() => {
      const path = useFlowStore.getState().filePath;
      if (!path) return;
      void saveCurrentFlow('auto');
    }, sec * 1000);
    return () => window.clearInterval(timer);
  }, [autoSaveEnabled, autoSaveIntervalSec, saveCurrentFlow]);

  // Save after a run session ends
  const prevExecStatusRef = useRef(execStatus);
  useEffect(() => {
    const prev = prevExecStatusRef.current;
    prevExecStatusRef.current = execStatus;
    if (!saveAfterRun) return;
    if (execStatus !== 'idle') return;
    if (!['running', 'stopping', 'paused', 'breakpoint'].includes(prev)) return;
    void saveCurrentFlow('after_run');
  }, [execStatus, saveAfterRun, saveCurrentFlow]);

  const handleSaveWithName = async (name: string) => {
    setSaveDialogOpen(false);
    updateFlowMeta({ name });
    const payload = { ...flow, name };
    const res = await bridge.saveFlow(payload, null, name);
    if (res?.ok) {
      useFlowStore.setState({ filePath: res.path });
      setFlowsRefreshToken((n) => n + 1);
      appendLog({ level: 'ok', message: `已保存: ${name}` });
      return true;
    }
    if (!res?.cancelled) appendLog({ level: 'error', message: res?.error || '保存失败' });
    return false;
  };

  const handleImport = async () => {
    const preview = await bridge.importFlow();
    if (preview?.ok && preview.import_token) {
      const capabilities = Array.isArray(preview.risks?.capabilities)
        ? preview.risks.capabilities
        : [];
      const unknownTypes = Array.isArray(preview.risks?.unknown_types)
        ? preview.risks.unknown_types
        : [];
      const capabilityLines = capabilities.map(
        (item: any) => `• ${item.label || item.type} × ${item.count || 1}`,
      );
      const unknownLines = unknownTypes.map(
        (item: any) => `• 未知/自定义积木 ${item.type} × ${item.count || 1}`,
      );
      const detected = [...capabilityLines, ...unknownLines];
      const trusted = await confirm({
        title: preview.risks?.needs_strong_warning ? '导入含高权限能力的流程？' : '导入外部流程？',
        description: [
          `文件：${preview.name || '未命名流程'}`,
          '运行外部流程可操控键鼠，并可能以当前用户权限读写文件、访问网络或执行代码。',
          detected.length ? `\n检测到的能力：\n${detected.join('\n')}` : '\n未检测到脚本、命令或网络类积木。',
          '\n请仅在你已审查并完全信任文件来源时继续。',
        ].join('\n'),
        confirmText: '我信任此来源，继续导入',
        destructive: true,
      });
      if (!trusted) return;
      const res = await bridge.commitImportFlow(preview.import_token);
      if (!res?.ok || !res.flow) {
        appendLog({ level: 'error', category: 'system', message: res?.error || '导入失败' });
        await alert({ title: '导入失败', description: res?.error || '无法保存导入的流程' });
        return;
      }
      setFlow(res.flow, res.path);
      setFlowsRefreshToken((n) => n + 1);
      const fmt = res.format === 'zip' ? '（已解压模板图片）' : '';
      const name = res.name || res.flow.name || '流程';
      useFlowStore.getState().appendAuditLog?.(`导入流程${fmt}: ${name}`, {
        path: res.path,
        format: res.format,
      });
    } else if (!preview?.cancelled) {
      appendLog({ level: 'error', category: 'system', message: preview?.error || '导入失败' });
    }
  };

  const handleExport = async () => {
    const res = await bridge.exportFlow(flow, flow.name || null);
    if (res?.ok) {
      const fmt = res.format === 'zip' ? '（含模板图片的流程包）' : '';
      useFlowStore.getState().appendAuditLog?.(
        `导出流程${fmt}: ${res.path || flow.name || '流程'}`,
        { path: res.path, format: res.format },
      );
    } else if (!res?.cancelled) {
      appendLog({ level: 'error', category: 'system', message: res?.error || '导出失败' });
    }
  };

  const handleOpenFlowPath = async (path: string) => {
    const res = await bridge.loadFlow(path);
    if (res?.ok && res.flow) {
      setFlow(res.flow, res.path);
      appendLog({ level: 'ok', message: `已打开: ${res.flow.name || path}` });
    } else if (!res?.cancelled) {
      appendLog({ level: 'error', message: res?.error || '打开失败' });
    }
  };

  const handleRenameFlow = async (path: string, newName: string) => {
    const res = await bridge.renameFlow(path, newName);
    if (!res?.ok) {
      const message = res?.error || '重命名失败';
      appendLog({ level: 'error', message });
      await alert({ title: '重命名失败', description: message });
      return false;
    }
    const normalizePath = (value: string | null | undefined) =>
      String(value || '').replace(/\\/g, '/').toLowerCase();
    if (normalizePath(filePath) === normalizePath(path)) {
      updateFlowMeta({ name: res.name || newName });
    }
    setFlowsRefreshToken((n) => n + 1);
    appendLog({ level: 'ok', message: `流程已重命名为: ${res.name || newName}` });
    return true;
  };

  const handleNewFlow = async () => {
    if (Object.keys(flow.nodes || {}).length) {
      const ok = await confirm({
        title: '新建流程',
        description: '新建流程将清空当前画布，是否继续？',
        confirmText: '新建',
        destructive: true,
      });
      if (!ok) return;
    }
    setFlow({
      flow_id: `flow_${Date.now()}`,
      name: '',
      version: 1,
      variables: {},
      entry: null,
      nodes: {},
    }, null);
    appendLog({ level: 'info', message: '已新建空白流程' });
  };

  const handleClearCanvas = async () => {
    const ok = await confirm({
      title: '清空画布',
      description: '确定清空当前画布上的全部节点？可用撤销恢复。',
      confirmText: '清空',
      destructive: true,
    });
    if (!ok) return;
    const ids = Object.keys(flow.nodes || {});
    if (ids.length) deleteNodes(ids);
    appendLog({ level: 'warn', message: '画布已清空' });
  };

  const stopRecordingNow = async () => {
    const res = await bridge.stopRecording();
    setRecording(false);
    if (res?.ok) {
      const nodes = res.nodes || [];
      appendRecordedNodes(nodes);
      const clicks = nodes.filter((n: any) => n?.type === 'click');
      const btnCount = { left: 0, right: 0, middle: 0 };
      for (const n of clicks) {
        const b = String(n?.params?.button || 'left');
        if (b in btnCount) (btnCount as any)[b] += 1;
        else btnCount.left += 1;
      }
      const btnHint =
        clicks.length > 0
          ? `（点击 ${clicks.length}：左${btnCount.left}/右${btnCount.right}/中${btnCount.middle}）`
          : '';
      appendLog({
        level: 'ok',
        message: `录制结束，追加 ${nodes.length || 0} 个节点${btnHint}`,
      });
    }
  };

  const handleToggleRecord = async () => {
    if (!recording) {
      const hide = !!hideWindowOnRecord;
      const mode = (defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord') as
        | 'coord'
        | 'frida_ui';
      const modeLabel = mode === 'frida_ui' ? 'Frida UI（游戏内点击组件）' : '坐标（屏幕鼠键）';
      const ok = await confirm({
        title: '开始录制',
        description:
          mode === 'frida_ui'
            ? hide
              ? `模式：${modeLabel}\n\n请在游戏内点击 UI 控件。主窗口将隐藏，用外部浮窗或 ${recordStopLabel} 停止。\n需先在设置页连接 Frida。`
              : `模式：${modeLabel}\n\n请在游戏内点击 UI 控件。右上角会出现停止浮层，也可按 ${recordStopLabel}。\n需先在设置页连接 Frida。`
            : hide
              ? `模式：${modeLabel}\n\n录制支持：点击 / 按键 / 延迟 / 滚轮。\n不含：拖拽、悬停、文本输入（请手动加节点）。\n\n已开启隐藏窗口：用右上角浮窗或 ${recordStopLabel} 停止。`
              : `模式：${modeLabel}\n\n录制支持：点击 / 按键 / 延迟 / 滚轮。\n不含：拖拽、悬停、文本输入（请手动加节点）。\n右上角浮层或 ${recordStopLabel} 停止。`,
        confirmText: '开始录制',
      });
      if (!ok) return;

      const res = await bridge.startRecording(
        50,
        hide,
        mode,
        defaultCoordinateMode || 'window_client',
      );
      if (res?.ok) {
        setRecording(true);
        setRecordingMode(mode);
        const stopHint = String(res?.stop_hotkey || recordStopLabel);
        appendLog({
          level: 'info',
          message: hide
            ? `开始录制 [${modeLabel}]（窗口已隐藏）。停止：外部浮窗 或 ${stopHint}`
            : `开始录制 [${modeLabel}]。点右上角浮层「停止录制」或按 ${stopHint}`,
        });
      } else {
        appendLog({
          level: 'error',
          message: res?.error || res?.message || '无法开始录制',
        });
      }
    } else {
      await stopRecordingNow();
    }
  };

  const handleAddNexuzNode = useCallback(
    (blockType: string, position?: { x: number; y: number }) => {
      const id = addNodeFromSchema(
        blockType,
        position || {
          x: 250 + Math.random() * 80,
          y: 150 + Math.random() * 80,
        },
      );
      if (id) appendLog({ level: 'info', message: `已添加节点: ${blockType}` });
      else appendLog({ level: 'warn', message: `未知积木类型: ${blockType}` });
    },
    [addNodeFromSchema, appendLog],
  );

  const handleDropBlock = useCallback(
    (blockType: string, x: number, y: number) => {
      handleAddNexuzNode(blockType, {
        x: Math.round(x / 10) * 10,
        y: Math.round(y / 10) * 10,
      });
    },
    [handleAddNexuzNode],
  );

  // Design-only demo nodes (unused for backend) — keep Sidebar/AI API shape
  const handleAddDemoNode = (subType: string) => {
    appendLog({
      level: 'warn',
      message: `设计稿节点「${subType}」未接入 Nexuz 后端，请从 Nodes 中选择动作/识别/控制积木`,
    });
  };

  const handleLoadTemplate = (templateId: string) => {
    if (templateId === 'click-loop') {
      setFlow(
        {
          flow_id: `flow_${Date.now()}`,
          name: '点击循环模板',
          version: 1,
          variables: {},
          entry: 'n1',
          nodes: {
            n1: { type: 'delay', params: { ms: 300 }, next: 'n2', position: { x: 100, y: 180 } },
            n2: {
              type: 'loop_n',
              params: { times: 3 },
              body: 'n3',
              next: null,
              position: { x: 360, y: 180 },
            },
            n3: {
              type: 'click',
              params: { x: 100, y: 100, button: 'left', click_type: 'single', move_duration: 0 },
              next: null,
              position: { x: 620, y: 180 },
            },
          },
        },
        null,
      );
      appendLog({ level: 'info', message: '已加载点击循环模板' });
      return;
    }
    if (templateId === 'color-branch') {
      setFlow(
        {
          flow_id: `flow_${Date.now()}`,
          name: '颜色分支模板',
          version: 1,
          variables: {},
          entry: 'c1',
          nodes: {
            c1: {
              type: 'if_color_match',
              params: { x: 10, y: 10, target_color: '#FF0000', tolerance: 30 },
              then: 'c2',
              else: 'c3',
              position: { x: 120, y: 180 },
            },
            c2: { type: 'delay', params: { ms: 100 }, next: null, position: { x: 400, y: 80 } },
            c3: { type: 'delay', params: { ms: 100 }, next: null, position: { x: 400, y: 280 } },
          },
        },
        null,
      );
      appendLog({ level: 'info', message: '已加载颜色分支模板' });
      return;
    }
    // Unknown builtin id
    appendLog({
      level: 'warn',
      message: `未知模板「${templateId}」`,
    });
  };

  const handleUpdateNodePosition = useCallback(
    (nodeId: string, x: number, y: number) => {
      updateNodePosition(nodeId, { x, y });
    },
    [updateNodePosition],
  );

  const handleUpdateNodePositions = useCallback(
    (updates: { id: string; x: number; y: number }[]) => {
      updateNodePositions(updates);
    },
    [updateNodePositions],
  );

  const handleAddConnection = useCallback(
    (
      sourceNodeId: string,
      sourceSocketId: string,
      targetNodeId: string,
      targetSocketId: string,
    ) => {
      // Data port → write {{source.field}} into target param
      if (isDataOutSocket(sourceSocketId)) {
        const field = dataOutField(sourceSocketId);
        const targetNode = flow?.nodes?.[targetNodeId];
        if (!targetNode) return;
        const schema = schemaMap[targetNode.type] || {};
        let paramName: string | null = isParamInSocket(targetSocketId)
          ? paramInName(targetSocketId)
          : null;
        if (!paramName) {
          const srcSchema = schemaMap[flow?.nodes?.[sourceNodeId]?.type] || {};
          const outMeta = (srcSchema.outputs || []).find((o: any) => o.name === field);
          paramName = pickBestBindParam(schema, field, outMeta?.type);
        }
        if (!paramName) {
          const available = listBindableParams(schema);
          appendLog({
            level: 'warn',
            message: available.length
              ? `无法自动绑定：请拖到目标节点左侧的参数口（如 ${available[0].label}）`
              : '目标节点没有可绑定的参数',
          });
          return;
        }
        const ref = formatNodeRef(sourceNodeId, field);
        updateNodeParams(targetNodeId, { [paramName]: ref });
        appendLog({
          level: 'info',
          message: `已绑定 ${ref} → ${targetNodeId}.${paramName}`,
        });
        return;
      }

      // Flow edges only: reject data-in targets
      if (isParamInSocket(targetSocketId)) {
        appendLog({ level: 'warn', message: '执行连线请拖到「执行」入口，数据请从紫色输出口拖出' });
        return;
      }

      const handle = sourceSocketId || 'next';
      if (isDataOutSocket(handle)) return;
      if (sourceNodeId === targetNodeId) {
        appendLog({
          level: 'warn',
          message: '不能连回自身（容易死循环）；重试请用循环节点',
        });
        return;
      }
      setNodeLink(sourceNodeId, handle, targetNodeId);
      appendLog({ level: 'info', message: `已连接 ${sourceNodeId}.${handle} → ${targetNodeId}` });
    },
    [setNodeLink, appendLog, flow, schemaMap, updateNodeParams],
  );

  const handleRemoveConnection = useCallback(
    (connectionId: string) => {
      const conn = connections.find((c) => c.id === connectionId);
      if (!conn) return;
      if (conn.kind === 'data') {
        const targetNode = flow?.nodes?.[conn.targetNodeId];
        if (!targetNode) return;
        const field = isDataOutSocket(conn.sourceSocketId)
          ? dataOutField(conn.sourceSocketId)
          : conn.label?.split('→')[0] || '';
        const expected = formatNodeRef(conn.sourceNodeId, field);
        let paramName = isParamInSocket(conn.targetSocketId)
          ? paramInName(conn.targetSocketId)
          : null;
        if (!paramName) {
          const params = targetNode.params || {};
          paramName =
            Object.keys(params).find((k) => {
              const v = params[k];
              return typeof v === 'string' && (v.trim() === expected || parseNodeRef(v)?.field === field);
            }) || null;
        }
        if (paramName) {
          const schema = schemaMap[targetNode.type];
          const input = (schema?.inputs || []).find((i: any) => i.name === paramName);
          const fallback = input?.type === 'number' ? 0 : '';
          updateNodeParams(conn.targetNodeId, { [paramName]: fallback });
          appendLog({ level: 'info', message: `已清除绑定 ${conn.targetNodeId}.${paramName}` });
        } else {
          appendLog({ level: 'warn', message: '未找到对应参数绑定，请在检查器中修改' });
        }
        return;
      }
      removeNodeLink(conn.sourceNodeId, conn.sourceSocketId);
      appendLog({ level: 'info', message: '已移除连线' });
    },
    [connections, removeNodeLink, appendLog, flow, schemaMap, updateNodeParams],
  );

  const handleRemoveNode = useCallback(
    (nodeId: string) => {
      deleteNodes([nodeId]);
      appendLog({ level: 'info', message: `已删除节点 ${nodeId}` });
    },
    [deleteNodes, appendLog],
  );

  const handleRemoveNodes = useCallback(
    (nodeIds: string[]) => {
      if (!nodeIds.length) return;
      deleteNodes(nodeIds);
      appendLog({ level: 'info', message: `已删除 ${nodeIds.length} 个节点` });
    },
    [deleteNodes, appendLog],
  );

  const handleDuplicateNodes = useCallback(
    (nodeIds: string[]) => {
      const newIds = duplicateNodes(nodeIds);
      if (newIds?.length) {
        appendLog({ level: 'info', message: `已复制 ${newIds.length} 个节点` });
      }
      return newIds || [];
    },
    [duplicateNodes, appendLog],
  );

  const handleUpdateNodeConfig = useCallback(
    (nodeId: string, updatedConfig: any) => {
      updateNodeParams(nodeId, updatedConfig);
    },
    [updateNodeParams],
  );

  const handleUpdateNodeName = useCallback(
    (nodeId: string, name: string) => {
      updateNodeName(nodeId, name);
    },
    [updateNodeName],
  );

  const handleToggleNodeCollapsed = useCallback(
    (nodeId: string) => {
      const node = useFlowStore.getState().flow.nodes[nodeId];
      if (!node) return;
      setNodeCollapsed(nodeId, !node.collapsed);
    },
    [setNodeCollapsed],
  );

  const handleSetNodesCollapsed = useCallback(
    (nodeIds: string[], collapsed: boolean) => {
      setNodesCollapsed(nodeIds, collapsed);
    },
    [setNodesCollapsed],
  );

  const handleSetBreakpointsForNodes = useCallback(
    (nodeIds: string[], enabled: boolean) => {
      setBreakpointsForNodes(nodeIds, enabled);
      queueMicrotask(() => {
        const bps = useFlowStore.getState().flow.breakpoints || [];
        const st = useFlowStore.getState().execStatus;
        if (st !== 'idle') {
          bridge.setBreakpoints(bps);
        }
        appendLog({
          level: 'info',
          message: enabled
            ? `已设置断点 ×${nodeIds.length}`
            : `已取消断点 ×${nodeIds.length}`,
        });
      });
    },
    [setBreakpointsForNodes, appendLog],
  );

  const handleSetNodesDisabled = useCallback(
    (nodeIds: string[], disabled: boolean) => {
      setNodesDisabled(nodeIds, disabled);
      appendLog({
        level: 'info',
        message: disabled
          ? `已禁用 ${nodeIds.length} 个节点`
          : `已启用 ${nodeIds.length} 个节点`,
      });
    },
    [setNodesDisabled, appendLog],
  );

  const handleDisconnectNodes = useCallback(
    async (nodeIds: string[]) => {
      const ids = (nodeIds || []).filter(Boolean);
      if (!ids.length) return;
      const ok = await confirm({
        title: '断开全部连线',
        description: `将清除 ${ids.length} 个节点的全部执行连线与相关数据绑定，是否继续？`,
        confirmText: '断开',
        destructive: true,
      });
      if (!ok) return;
      disconnectNodes(ids);
      appendLog({ level: 'info', message: `已断开 ${ids.length} 个节点的连线` });
    },
    [confirm, disconnectNodes, appendLog],
  );

  const handleDeleteOtherNodes = useCallback(
    async (keepId: string) => {
      const all = Object.keys(flow?.nodes || {});
      const others = all.filter((id) => id !== keepId);
      if (!others.length) {
        appendLog({ level: 'info', message: '没有其他节点可删' });
        return;
      }
      const ok = await confirm({
        title: '删除其他节点',
        description: `将删除其余 ${others.length} 个节点，仅保留当前节点，是否继续？`,
        confirmText: '删除',
        destructive: true,
      });
      if (!ok) return;
      deleteNodes(others);
      if (flow?.entry !== keepId) {
        useFlowStore.getState().setEntry(keepId);
      }
      selectNode(keepId);
      appendLog({ level: 'warn', message: `已删除其他节点 ×${others.length}` });
    },
    [flow, confirm, deleteNodes, appendLog, selectNode],
  );

  const handleDeleteDownstreamNodes = useCallback(
    async (startId: string) => {
      const down = collectDownstreamNodeIds(flow, startId);
      if (!down.length) {
        appendLog({ level: 'info', message: '没有后续节点可删' });
        return;
      }
      const ok = await confirm({
        title: '删除后续节点',
        description: `将删除从当前节点可达的 ${down.length} 个后续节点（保留本节点），是否继续？`,
        confirmText: '删除',
        destructive: true,
      });
      if (!ok) return;
      deleteNodes(down);
      clearNodesFlowOuts([startId]);
      appendLog({ level: 'warn', message: `已删除后续节点 ×${down.length}` });
    },
    [flow, confirm, deleteNodes, clearNodesFlowOuts, appendLog],
  );

  const handleRunFromNode = useCallback(
    async (nodeId: string) => {
      if (isExecuting) {
        appendLog({
          level: 'warn',
          message: '已有流程在执行，请先停止后再运行',
        });
        return;
      }
      const src = flow.nodes?.[nodeId];
      if (!src) {
        appendLog({ level: 'error', message: `节点不存在: ${nodeId}` });
        return;
      }
      clearLogs();
      appendLog({
        level: 'info',
        message: `从此节点开始运行 [${nodeId}] ${src.type || ''}…`,
      });
      const fromFlow = { ...flow, entry: nodeId };
      const prepared = applyDefaultOutputCoordinateMode(
        applyDefaultCoordinateMode(
          applyDefaultCaptureMode(fromFlow, defaultCaptureMode),
          defaultCoordinateMode,
        ),
        defaultOutputCoordinateMode,
      );
      const runtimeFlow = { ...prepared, __global_node_interval_ms: defaultNodeIntervalMs };
      const payload = filePath ? { ...runtimeFlow, __file_path__: filePath } : runtimeFlow;
      const useDebug = !!debugMode;
      const bps = useDebug ? flow.breakpoints || [] : [];
      const hide = hideWindowOnRecord && !useDebug;
      const res = await bridge.runFlow(payload, false, hide, useDebug, bps);
      if (res?.run_log) useFlowStore.setState({ runLog: res.run_log });
      if (!res?.ok) {
        appendLog({ level: 'error', message: res?.error || '启动失败' });
        return;
      }
      if (res?.run_monitor) {
        setRunMonitorActive(true);
        setRunMonitorFlowName(String(payload?.name || flow?.name || ''));
      }
    },
    [
      isExecuting,
      flow,
      appendLog,
      clearLogs,
      defaultCaptureMode,
      defaultCoordinateMode,
      defaultOutputCoordinateMode,
      defaultNodeIntervalMs,
      filePath,
      hideWindowOnRecord,
      debugMode,
    ],
  );

  const handleRunSingleNode = useCallback(
    async (nodeId: string) => {
      if (isExecuting) {
        appendLog({
          level: 'warn',
          message: '已有流程在执行，请先停止后再单节点运行',
        });
        return;
      }
      const src = flow.nodes?.[nodeId];
      if (!src) {
        appendLog({ level: 'error', message: `节点不存在: ${nodeId}` });
        return;
      }
      // Solo flow: same variables, only this node, no outgoing links
      const soloNode = JSON.parse(JSON.stringify(src));
      delete soloNode.next;
      delete soloNode.then;
      delete soloNode.else;
      delete soloNode.body;
      delete soloNode.default;
      if (soloNode.params && typeof soloNode.params === 'object') {
        // switch cases keep values for display but clear jump targets so we don't leave solo graph
        if (Array.isArray(soloNode.params.cases)) {
          soloNode.params = {
            ...soloNode.params,
            cases: soloNode.params.cases.map((c: any) =>
              c && typeof c === 'object' ? { ...c, node_id: '' } : c,
            ),
            default: '',
          };
        }
      }
      const soloFlow = {
        ...flow,
        entry: nodeId,
        nodes: { [nodeId]: soloNode },
        breakpoints: [],
      };
      clearLogs();
      appendLog({
        level: 'info',
        message: `单节点运行 [${nodeId}] ${src.type || ''}…`,
      });
      const prepared = applyDefaultOutputCoordinateMode(
        applyDefaultCoordinateMode(
          applyDefaultCaptureMode(soloFlow, defaultCaptureMode),
          defaultCoordinateMode,
        ),
        defaultOutputCoordinateMode,
      );
      const runtimeFlow = { ...prepared, __global_node_interval_ms: defaultNodeIntervalMs };
      const payload = filePath ? { ...runtimeFlow, __file_path__: filePath } : runtimeFlow;
      const hide = hideWindowOnRecord && !debugMode;
      const res = await bridge.runFlow(payload, false, hide, false, []);
      if (!res?.ok) {
        appendLog({ level: 'error', message: res?.error || '单节点启动失败' });
        return;
      }
      if (res?.run_monitor) {
        setRunMonitorActive(true);
        setRunMonitorFlowName(String(payload?.name || flow?.name || ''));
      }
    },
    [
      isExecuting,
      flow,
      appendLog,
      clearLogs,
      defaultCaptureMode,
      defaultCoordinateMode,
      defaultOutputCoordinateMode,
      defaultNodeIntervalMs,
      filePath,
      hideWindowOnRecord,
      debugMode,
    ],
  );

  if (runMonitorActive) {
    const node = execNodeId ? flow?.nodes?.[execNodeId] : null;
    const nodeName = node
      ? String(node.name || node.type || execNodeId)
      : execNodeId || '—';
    const nodeLabel = execNodeId && node ? `${nodeName} (${execNodeId})` : nodeName;
    return (
      <div
        className="plugin-shell h-screen w-screen overflow-hidden font-sans"
        style={{ backgroundColor: '#0c0e14' }}
        data-plugin-chrome
      >
        <WindowResizeHandles />
        <RunMonitorView
          flowName={runMonitorFlowName || flow?.name || ''}
          nodeLabel={nodeLabel}
          execStatus={execStatus}
          onPause={handlePause}
          onResume={handleResume}
          onStop={handleStop}
          hotkeyLabels={hotkeyLabels}
          themeName={themeName as any}
          themeMode={themeMode as any}
        />
      </div>
    );
  }

  return (
    <div
      style={{ backgroundColor: colors.background }}
      className="plugin-shell flex flex-col h-screen w-screen overflow-hidden font-sans"
      data-plugin-chrome
    >
      <WindowResizeHandles />
      <Toolbar
        themeName={themeName as any}
        setThemeName={handleSetThemeName as any}
        themeMode={themeMode as any}
        setThemeMode={handleSetThemeMode as any}
        hotkeyLabels={hotkeyLabels}
        onRunWorkflow={handleRunWorkflow}
        isExecuting={isExecuting}
        showFlowAi
        onToggleAssistant={() => setIsAssistantOpen(!isAssistantOpen)}
        isAssistantOpen={isAssistantOpen}
        onClearCanvas={handleClearCanvas}
        onUndo={undo}
        onRedo={redo}
        canUndo={canUndo}
        canRedo={canRedo}
        onSave={handleSave}
        onImport={handleImport}
        onExport={handleExport}
        onToggleRecord={handleToggleRecord}
        recording={recording}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
        onForceReset={handleForceReset}
        onToggleDebug={handleToggleDebug}
        debugMode={debugMode}
        execStatus={execStatus}
        viewMode={viewMode as 'canvas' | 'code' | 'flowchart' | 'settings'}
        flowViewMode={
          (viewMode === 'settings' ? lastFlowViewMode : viewMode) as
            | 'canvas'
            | 'code'
            | 'flowchart'
        }
        onViewModeChange={(m) => setViewMode(m)}
      />

      <div className="flex-1 flex overflow-hidden relative">
        {/* Optional: hide flow side panels while settings is open (pref). */}
        {!settingsFocus && !leftCollapsed ? (
          <>
            <Sidebar
              themeName={themeName as any}
              themeMode={themeMode as any}
              onAddNode={handleAddDemoNode}
              onAddNexuzNode={handleAddNexuzNode}
              nexuzSchemas={schemas}
              onLoadTemplate={handleLoadTemplate}
              runHistory={runHistory}
              onClearHistory={clearRunHistory}
              interactionLocked={isExecuting}
              currentFlowPath={filePath}
              onOpenFlowPath={handleOpenFlowPath}
              onRenameFlow={handleRenameFlow}
              onNewFlow={handleNewFlow}
              flowsRefreshToken={flowsRefreshToken}
              contentWidth={leftContentWidth}
            />
            <SplitHandle
              orientation="vertical"
              value={leftContentWidth}
              onChange={setLeftContentWidth}
              onCommit={(w) => persistPanelSize(LEFT_CONTENT_WIDTH_KEY, w)}
              onReset={() => {
                setLeftContentWidth(DEFAULT_LEFT_CONTENT_WIDTH);
                persistPanelSize(LEFT_CONTENT_WIDTH_KEY, DEFAULT_LEFT_CONTENT_WIDTH);
              }}
              min={MIN_LEFT_CONTENT_WIDTH}
              max={MAX_LEFT_CONTENT_WIDTH}
              label="拖动调整左侧宽度"
              gripColor={colors.secondaryText}
            />
          </>
        ) : null}

        <div className="relative flex-1 min-w-0 min-h-0 flex flex-col">
          {!settingsFocus ? (
            <>
              <button
                type="button"
                onClick={toggleLeftPanel}
                title={leftCollapsed ? '展开左侧' : '收起左侧'}
                aria-label={leftCollapsed ? '展开左侧' : '收起左侧'}
                className="absolute left-2 top-1/2 -translate-y-1/2 z-30 h-8 w-8 rounded-lg border shadow-sm flex items-center justify-center transition-colors hover:opacity-100 opacity-80"
                style={{
                  backgroundColor: colors.surface,
                  borderColor: colors.border,
                  color: colors.text,
                }}
              >
                {leftCollapsed ? (
                  <PanelLeftOpen className="w-3.5 h-3.5" />
                ) : (
                  <PanelLeftClose className="w-3.5 h-3.5" />
                )}
              </button>
              <button
                type="button"
                onClick={toggleRightPanel}
                title={rightCollapsed ? '展开右侧' : '收起右侧'}
                aria-label={rightCollapsed ? '展开右侧' : '收起右侧'}
                className="absolute right-2 top-1/2 -translate-y-1/2 z-30 h-8 w-8 rounded-lg border shadow-sm flex items-center justify-center transition-colors hover:opacity-100 opacity-80"
                style={{
                  backgroundColor: colors.surface,
                  borderColor: colors.border,
                  color: colors.text,
                }}
              >
                {rightCollapsed ? (
                  <PanelRightOpen className="w-3.5 h-3.5" />
                ) : (
                  <PanelRightClose className="w-3.5 h-3.5" />
                )}
              </button>
            </>
          ) : null}

          {viewMode === 'settings' ? (
            <SettingsPage
              themeName={themeName as any}
              themeMode={themeMode as any}
              expandSection={settingsExpandSection || undefined}
              onClose={() => {
                setSettingsExpandSection(null);
                setViewMode(lastFlowViewMode);
              }}
            />
          ) : viewMode === 'code' ? (
            <CodeEditor themeName={themeName as any} themeMode={themeMode as any} />
          ) : viewMode === 'flowchart' ? (
            <FlowchartView
              nodes={nodes}
              connections={connections}
              activeNodeId={execNodeId}
              entryId={flow?.entry ?? null}
              execStatus={execStatus}
              themeName={themeName as any}
              themeMode={themeMode as any}
            />
          ) : (
            <>
              {debugMode ? (
                <DebugBar
                  themeName={themeName as any}
                  themeMode={themeMode as any}
                  execStatus={execStatus}
                  breakpointCount={(flow.breakpoints || []).length}
                  onContinue={handleResume}
                  onStep={handleDebugStep}
                  onStop={handleStop}
                  onForceReset={handleForceReset}
                  onPause={handlePause}
                />
              ) : null}
              {debugMode ? (
                <DebugWatchPanel themeName={themeName as any} themeMode={themeMode as any} />
              ) : null}
              <Canvas
                nodes={nodes}
                connections={connections}
                selectedNodeId={selectedNodeId}
                onSelectNode={selectNode}
                onUpdateNodePosition={handleUpdateNodePosition}
                onUpdateNodePositions={handleUpdateNodePositions}
                onAddConnection={handleAddConnection}
                onRemoveConnection={handleRemoveConnection}
                onRemoveNode={handleRemoveNode}
                onRemoveNodes={handleRemoveNodes}
                onDuplicateNodes={handleDuplicateNodes}
                onDropBlock={handleDropBlock}
                onRunSingleNode={handleRunSingleNode}
                onRunFromNode={handleRunFromNode}
                onToggleBreakpoint={handleToggleBreakpoint}
                onSetBreakpointsForNodes={handleSetBreakpointsForNodes}
                onUpdateNodeName={handleUpdateNodeName}
                onToggleNodeCollapsed={handleToggleNodeCollapsed}
                onSetNodesCollapsed={handleSetNodesCollapsed}
                onSetEntry={(id: string) => useFlowStore.getState().setEntry(id)}
                onSetNodesDisabled={handleSetNodesDisabled}
                onDisconnectNodes={handleDisconnectNodes}
                onDeleteOtherNodes={handleDeleteOtherNodes}
                onDeleteDownstreamNodes={handleDeleteDownstreamNodes}
                themeName={themeName as any}
                themeMode={themeMode as any}
                isExecuting={isExecuting}
                execStatus={execStatus}
                executingNodeId={execNodeId}
                debugMode={debugMode}
                breakpoints={flow.breakpoints || []}
              />
            </>
          )}
        </div>

        {!settingsFocus && !rightCollapsed ? (
          <>
            <SplitHandle
              orientation="vertical"
              value={rightPanelWidth}
              onChange={setRightPanelWidth}
              onCommit={(w) => persistPanelSize(RIGHT_PANEL_WIDTH_KEY, w)}
              onReset={() => {
                setRightPanelWidth(DEFAULT_RIGHT_PANEL_WIDTH);
                persistPanelSize(RIGHT_PANEL_WIDTH_KEY, DEFAULT_RIGHT_PANEL_WIDTH);
              }}
              min={MIN_RIGHT_PANEL_WIDTH}
              max={MAX_RIGHT_PANEL_WIDTH}
              invert
              label="拖动调整右侧宽度"
              gripColor={colors.secondaryText}
            />
            <Inspector
            selectedNode={selectedNode}
            onUpdateNodeConfig={handleUpdateNodeConfig}
            onUpdateNodeName={handleUpdateNodeName}
            onDeselect={() => selectNode(null)}
            themeName={themeName as any}
            themeMode={themeMode as any}
            logs={canvasLogs}
            rawLogs={logs}
            runLog={runLog}
            schemaMap={schemaMap}
            bindIssues={bindIssues}
            width={rightPanelWidth}
            onPickPoint={(method?: string) => runCoordPick('point', method)}
            onPickClick={(mode: string, method?: string) =>
              mode === 'frida_ui'
                ? bridge.pickClick(mode, hideWindowOnRecord, defaultCoordinateMode || 'window_client')
                : runCoordPick('point', method)
            }
            onPickRegion={(method?: string) => runCoordPick('region', method)}
            onCaptureTemplate={(method?: string) => runCoordPick('template', method)}
            onRemoveNode={(id: string) => {
              deleteNodes([id]);
              appendLog({ level: 'info', message: `已删除节点 ${id}` });
            }}
            onSetEntry={(id: string) => useFlowStore.getState().setEntry(id)}
            defaultCaptureMode={defaultCaptureMode}
            defaultPickMethod={defaultPickMethod}
            defaultCoordinateMode={defaultCoordinateMode}
            defaultOutputCoordinateMode={defaultOutputCoordinateMode}
            defaultNodeIntervalMs={defaultNodeIntervalMs}
          />
          </>
        ) : null}

        {screenPickDialog}

        {isAssistantOpen ? (
          <AIAssistant
            isOpen={isAssistantOpen}
            onClose={() => setIsAssistantOpen(false)}
            themeName={themeName as any}
            themeMode={themeMode as any}
            currentFlow={flow as any}
            onApplyFlow={(nextFlow, warnings) => {
              setFlow(nextFlow as any, filePath, { recordHistory: true });
              if (warnings?.length) {
                appendLog({
                  level: 'warn',
                  message: `AI 草稿已应用（注意: ${warnings.join('；')}）`,
                });
              } else {
                appendLog({ level: 'ok', message: 'AI 草稿已应用到画布' });
              }
            }}
            onOpenSettings={() => {
              setIsAssistantOpen(false);
              setSettingsExpandSection('ai');
              setViewMode('settings');
            }}
          />
        ) : null}
      </div>

      <RecordingBanner
        open={recording && !hideWindowOnRecord}
        mode={recordingMode}
        stopHotkeyLabel={recordStopLabel}
        onStop={() => {
          void stopRecordingNow();
        }}
      />

      <RunningBanner
        open={isExecuting && !recording}
        execStatus={execStatus}
        pauseHotkeyLabel={hotkeyLabels.pause_run}
        stopHotkeyLabel={hotkeyLabels.stop_run}
        onPause={() => {
          void handlePause();
        }}
        onContinue={() => {
          void handleResume();
        }}
        onStop={() => {
          void handleStop();
        }}
      />

      <SaveNameDialog
        open={saveDialogOpen}
        initialName={flow.name || ''}
        onCancel={() => setSaveDialogOpen(false)}
        onConfirm={(name) => {
          void handleSaveWithName(name);
        }}
      />
    </div>
  );
}
