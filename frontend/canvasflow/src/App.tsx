/**
 * CanvasFlow UI shell wired to Nexuz store + bridge.
 * Unused design-only UI (AI Assistant, demo templates) kept as-is.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Toolbar from './components/Toolbar';
import Sidebar from './components/Sidebar';
import Canvas from './components/Canvas';
import Inspector from './components/Inspector';
import CodeEditor from './components/CodeEditor';
import AIAssistant from './components/AIAssistant';
import SaveNameDialog from './components/SaveNameDialog';
import RecordingBanner from './components/RecordingBanner';
import SettingsPage from './components/SettingsPage';
import { AppDialogProvider, useAppDialog } from './components/AppDialogs';
import { getThemeColors } from './theme';
import {
  applyDefaultCaptureMode,
  dataOutField,
  formatNodeRef,
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
import { useFlowStore } from '../../src/store/flowModelStore';
import { bridge, waitForBridge, MOCK_SCHEMAS } from '../../src/bridge';

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
      <AppShell />
    </AppDialogProvider>
  );
}

function AppShell() {
  const { confirm } = useAppDialog();
  const flow = useFlowStore((s) => s.flow);
  const schemas = useFlowStore((s) => s.schemas);
  const schemaMap = useFlowStore((s) => s.schemaMap);
  const selectedNodeId = useFlowStore((s) => s.selectedNodeId);
  const selectNode = useFlowStore((s) => s.selectNode);
  const viewMode = useFlowStore((s) => s.viewMode);
  const setViewMode = useFlowStore((s) => s.setViewMode);
  const themeName = useFlowStore((s) => s.themeName);
  const themeMode = useFlowStore((s) => s.themeMode);
  const setThemeName = useFlowStore((s) => s.setThemeName);
  const setThemeMode = useFlowStore((s) => s.setThemeMode);
  const execStatus = useFlowStore((s) => s.execStatus);
  const execNodeId = useFlowStore((s) => s.execNodeId);
  const execNodeStates = useFlowStore((s) => s.execNodeStates);
  const nodeOutputs = useFlowStore((s) => s.nodeOutputs);
  const logs = useFlowStore((s) => s.logs);
  const runHistory = useFlowStore((s) => s.runHistory);
  const clearRunHistory = useFlowStore((s) => s.clearRunHistory);
  const filePath = useFlowStore((s) => s.filePath);
  const hideWindowOnRecord = useFlowStore((s) => s.hideWindowOnRecord);
  const defaultCaptureMode = useFlowStore((s) => s.defaultCaptureMode);

  const setSchemas = useFlowStore((s) => s.setSchemas);
  const setBridgeReady = useFlowStore((s) => s.setBridgeReady);
  const updateFlowMeta = useFlowStore((s) => s.updateFlowMeta);
  const addNodeFromSchema = useFlowStore((s) => s.addNodeFromSchema);
  const updateNodeParams = useFlowStore((s) => s.updateNodeParams);
  const updateNodeName = useFlowStore((s) => s.updateNodeName);
  const updateNodePosition = useFlowStore((s) => s.updateNodePosition);
  const setNodeLink = useFlowStore((s) => s.setNodeLink);
  const removeNodeLink = useFlowStore((s) => s.removeNodeLink);
  const deleteNodes = useFlowStore((s) => s.deleteNodes);
  const duplicateNodes = useFlowStore((s) => s.duplicateNodes);
  const updateNodePositions = useFlowStore((s) => s.updateNodePositions);
  const setFlow = useFlowStore((s) => s.setFlow);
  const clearLogs = useFlowStore((s) => s.clearLogs);
  const appendLog = useFlowStore((s) => s.appendLog);
  const onRuntimeEvent = useFlowStore((s) => s.onRuntimeEvent);
  const appendRecordedNodes = useFlowStore((s) => s.appendRecordedNodes);

  const [isAssistantOpen, setIsAssistantOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingMode, setRecordingMode] = useState<'coord' | 'frida_ui'>('coord');
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const colors = getThemeColors(themeName as any, themeMode as any);
  // paused / stopping still own the interpreter — must not start a second run
  const isBusy = execStatus === 'running' || execStatus === 'paused' || execStatus === 'stopping';
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
      logs
        .slice(-80)
        .reverse()
        .map((l, i) => ({
          id: `${l.ts || 0}-${i}-${String(l.message || '').slice(0, 24)}`,
          timestamp: new Date(l.ts || Date.now()).toLocaleTimeString(),
          type: mapLogLevel(l.level),
          message: l.message,
          nodeId: l.nodeId || undefined,
          nodeName: undefined,
        })),
    [logs],
  );

  // Bridge boot + runtime events
  useEffect(() => {
    (window as any).__nexuzEmit = (msg: any) => {
      if (!msg) return;
      onRuntimeEvent(msg.event, msg.payload || {});
    };
    let cancelled = false;
    (async () => {
      await waitForBridge(8000);
      if (cancelled) return;
      setBridgeReady(true);
      try {
        const ping = await bridge.ping();
        appendLog({
          level: 'info',
          message: `桥接: ${ping?.message || 'ok'} (DPI ${ping?.dpi_scale ?? '?'})`,
        });
      } catch (e: any) {
        appendLog({ level: 'error', message: String(e) });
      }
      const list = await bridge.getBlockRegistry();
      if (!cancelled) {
        const merged = mergeSchemas(list);
        setSchemas(merged);
        const hasOcr = merged.some((s) => s.type === 'ocr_recognize');
        appendLog({
          level: 'info',
          message: hasOcr
            ? `积木已加载 ${merged.length} 个（含 OCR / 找图）`
            : `积木已加载 ${merged.length} 个`,
        });
      }
    })();
    return () => {
      cancelled = true;
      delete (window as any).__nexuzEmit;
    };
  }, [onRuntimeEvent, setBridgeReady, setSchemas, appendLog]);

  useEffect(() => {
    const last = logs[logs.length - 1];
    if (last?.message?.startsWith('快捷键停止录制')) setRecording(false);
  }, [logs]);

  const handleRunWorkflow = async () => {
    // Paused → resume (same as 继续). Avoid "已有流程正在执行" deadlock.
    if (execStatus === 'paused') {
      appendLog({ level: 'info', message: '继续运行流程…' });
      const res = await bridge.resumeFlow();
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
            : '流程正在运行，请先暂停/停止，或使用「继续」',
      });
      return;
    }
    clearLogs();
    appendLog({
      level: 'info',
      message: hideWindowOnRecord
        ? '开始运行流程（已隐藏窗口，避免点击落到本程序上）…'
        : '开始运行流程…',
    });
    const prepared = applyDefaultCaptureMode(flow, defaultCaptureMode);
    const payload = filePath ? { ...prepared, __file_path__: filePath } : prepared;
    const res = await bridge.runFlow(payload, false, hideWindowOnRecord);
    if (res?.resumed) {
      appendLog({ level: 'info', message: '已继续暂停中的流程' });
      return;
    }
    if (!res?.ok) appendLog({ level: 'error', message: res?.error || '启动失败' });
  };

  const handleStop = async () => {
    if (execStatus === 'idle') return;
    useFlowStore.setState({ execStatus: 'stopping' });
    appendLog({ level: 'warn', message: '正在停止流程…' });
    const res = await bridge.stopFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '停止失败' });
      // Recover UI if backend already idle
      const st = await bridge.isRunning();
      if (!st?.running) useFlowStore.setState({ execStatus: 'idle' });
    }
  };

  const handlePause = async () => {
    const res = await bridge.pauseFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '暂停失败' });
    }
  };

  const handleResume = async () => {
    const res = await bridge.resumeFlow();
    if (res?.ok === false) {
      appendLog({ level: 'error', message: res?.error || '继续失败' });
    }
  };

  const handleStep = async () => {
    if (execStatus === 'paused') {
      const res = await bridge.resumeFlow();
      if (res?.ok === false) {
        appendLog({ level: 'error', message: res?.error || '继续失败' });
      }
      // After resume in step mode intent — also pulse step
      await bridge.stepFlow();
      return;
    }
    if (execStatus === 'stopping') {
      appendLog({ level: 'warn', message: '正在停止中，请稍候…' });
      return;
    }
    if (execStatus === 'idle') {
      clearLogs();
      appendLog({ level: 'info', message: '单步模式启动…' });
      const prepared = applyDefaultCaptureMode(flow, defaultCaptureMode);
      const payload = filePath ? { ...prepared, __file_path__: filePath } : prepared;
      const res = await bridge.runFlow(payload, true);
      if (!res?.ok) appendLog({ level: 'error', message: res?.error || '启动失败' });
      return;
    }
    const res = await bridge.stepFlow();
    if (res && res.ok === false) {
      appendLog({ level: 'error', message: res.error || '单步失败' });
    }
  };

  const handleSave = async () => {
    // Already saved once → overwrite in place
    if (filePath) {
      const res = await bridge.saveFlow(flow, filePath, flow.name || null);
      if (res?.ok) {
        useFlowStore.setState({ filePath: res.path });
        if (res.name) updateFlowMeta({ name: res.name });
        appendLog({ level: 'ok', message: `已保存: ${res.path}` });
        return true;
      }
      if (!res?.cancelled) appendLog({ level: 'error', message: res?.error || '保存失败' });
      return false;
    }
    // First save → ask for a name
    setSaveDialogOpen(true);
    return false;
  };

  const handleSaveWithName = async (name: string) => {
    setSaveDialogOpen(false);
    updateFlowMeta({ name });
    const payload = { ...flow, name };
    const res = await bridge.saveFlow(payload, null, name);
    if (res?.ok) {
      useFlowStore.setState({ filePath: res.path });
      appendLog({ level: 'ok', message: `已保存: ${res.path}` });
      return true;
    }
    if (!res?.cancelled) appendLog({ level: 'error', message: res?.error || '保存失败' });
    return false;
  };

  const handleOpen = async () => {
    const res = await bridge.loadFlow();
    if (res?.ok && res.flow) {
      setFlow(res.flow, res.path);
      appendLog({ level: 'ok', message: `已打开: ${res.path}` });
    } else if (!res?.cancelled) {
      appendLog({ level: 'error', message: res?.error || '打开失败' });
    }
  };

  const handleOpenFlowPath = async (path: string) => {
    const res = await bridge.loadFlow(path);
    if (res?.ok && res.flow) {
      setFlow(res.flow, res.path);
      appendLog({ level: 'ok', message: `已打开: ${res.path}` });
    } else if (!res?.cancelled) {
      appendLog({ level: 'error', message: res?.error || '打开失败' });
    }
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
      description: '确定清空当前画布上的全部节点？此操作不可撤销。',
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
              ? `模式：${modeLabel}\n\n请在游戏内点击 UI 控件。主窗口将隐藏，用外部浮窗或 Ctrl+Shift+F10 停止。\n需先在设置页连接 Frida。`
              : `模式：${modeLabel}\n\n请在游戏内点击 UI 控件。右上角会出现停止浮层，也可按 Ctrl+Shift+F10。\n需先在设置页连接 Frida。`
            : hide
              ? `模式：${modeLabel}\n\n录制会把鼠标/键盘操作转成流程节点。\n\n已开启「操作时隐藏主窗口」：请用屏幕右上角外部浮窗或 Ctrl+Shift+F10 停止。`
              : `模式：${modeLabel}\n\n录制会把鼠标/键盘操作转成流程节点。右上角会出现停止浮层；也可按 Ctrl+Shift+F10。`,
        confirmText: '开始录制',
      });
      if (!ok) return;

      const res = await bridge.startRecording(50, hide, mode);
      if (res?.ok) {
        setRecording(true);
        setRecordingMode(mode);
        appendLog({
          level: 'info',
          message: hide
            ? `开始录制 [${modeLabel}]（窗口已隐藏）。停止：外部浮窗 或 Ctrl+Shift+F10`
            : `开始录制 [${modeLabel}]。点右上角浮层「停止录制」或按 Ctrl+Shift+F10`,
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

  const handleRunSingleNode = useCallback(async (_nodeId: string) => {
    appendLog({
      level: 'warn',
      message: '单节点运行未单独暴露；请使用顶栏 Run Pipeline 执行整条流程',
    });
  }, [appendLog]);

  return (
    <div
      style={{ backgroundColor: colors.background }}
      className="flex flex-col h-screen w-screen overflow-hidden font-sans"
    >
      <Toolbar
        themeName={themeName as any}
        setThemeName={handleSetThemeName as any}
        themeMode={themeMode as any}
        setThemeMode={handleSetThemeMode as any}
        onRunWorkflow={handleRunWorkflow}
        isExecuting={isExecuting}
        onToggleAssistant={() => setIsAssistantOpen(!isAssistantOpen)}
        isAssistantOpen={isAssistantOpen}
        onClearCanvas={handleClearCanvas}
        onSave={handleSave}
        onOpen={handleOpen}
        onToggleRecord={handleToggleRecord}
        recording={recording}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
        onStep={handleStep}
        execStatus={execStatus}
        viewMode={viewMode as 'canvas' | 'code' | 'settings'}
        onViewModeChange={(m) => setViewMode(m)}
      />

      <div className="flex-1 flex overflow-hidden relative">
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
          onNewFlow={handleNewFlow}
          onOpenFromDisk={handleOpen}
        />

        {viewMode === 'settings' ? (
          <SettingsPage themeName={themeName as any} themeMode={themeMode as any} />
        ) : viewMode === 'code' ? (
          <CodeEditor themeName={themeName as any} themeMode={themeMode as any} />
        ) : (
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
            onUpdateNodeName={handleUpdateNodeName}
            themeName={themeName as any}
            themeMode={themeMode as any}
            isExecuting={isExecuting}
            execStatus={execStatus}
            executingNodeId={execNodeId}
          />
        )}

        <Inspector
          selectedNode={selectedNode}
          onUpdateNodeConfig={handleUpdateNodeConfig}
          onUpdateNodeName={handleUpdateNodeName}
          onRunSingleNode={handleRunSingleNode}
          onDeselect={() => selectNode(null)}
          themeName={themeName as any}
          themeMode={themeMode as any}
          logs={canvasLogs}
          rawLogs={logs}
          schemaMap={schemaMap}
          bindIssues={bindIssues}
          onPickPoint={async () => bridge.pickPoint(hideWindowOnRecord)}
          onPickClick={async (mode: string) => bridge.pickClick(mode, hideWindowOnRecord)}
          onPickRegion={async () => bridge.pickRegion(hideWindowOnRecord)}
          onCaptureTemplate={async () => bridge.captureTemplate(hideWindowOnRecord)}
          onSetEntry={(id: string) => useFlowStore.getState().setEntry(id)}
          defaultCaptureMode={defaultCaptureMode}
        />

        {/* Design-only: keep AI Assistant UI as-is */}
        <AIAssistant
          isOpen={isAssistantOpen}
          onClose={() => setIsAssistantOpen(false)}
          themeName={themeName as any}
          themeMode={themeMode as any}
          workflowContext={nodes}
          onAddCustomNode={(nodeData) => handleAddDemoNode(nodeData.subType)}
        />
      </div>

      <RecordingBanner
        open={recording && !hideWindowOnRecord}
        mode={recordingMode}
        onStop={() => {
          void stopRecordingNow();
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
