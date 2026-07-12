/**
 * CanvasFlow UI shell wired to Nexuz store + bridge.
 * Unused design-only UI (AI Assistant, demo templates) kept as-is.
 */
import React, { useEffect, useMemo, useState } from 'react';
import Toolbar from './components/Toolbar';
import Sidebar from './components/Sidebar';
import Canvas from './components/Canvas';
import Inspector from './components/Inspector';
import CodeEditor from './components/CodeEditor';
import AIAssistant from './components/AIAssistant';
import SaveNameDialog from './components/SaveNameDialog';
import RecordingBanner from './components/RecordingBanner';
import { AppDialogProvider, useAppDialog } from './components/AppDialogs';
import { getThemeColors } from './theme';
import { flowToCanvas, mapLogLevel } from './nexuzAdapter';
import { useFlowStore } from '../../src/store/flowModelStore';
import { bridge, waitForBridge, MOCK_SCHEMAS } from '../../src/bridge';

const REQUIRED_BLOCK_TYPES = [
  'ocr_recognize',
  'if_text_contains',
  'find_image',
  'color_detect',
  'if_color_match',
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

  const setSchemas = useFlowStore((s) => s.setSchemas);
  const setBridgeReady = useFlowStore((s) => s.setBridgeReady);
  const updateFlowMeta = useFlowStore((s) => s.updateFlowMeta);
  const addNodeFromSchema = useFlowStore((s) => s.addNodeFromSchema);
  const updateNodeParams = useFlowStore((s) => s.updateNodeParams);
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
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);

  const colors = getThemeColors(themeName as any, themeMode as any);
  const isExecuting = execStatus === 'running';

  useEffect(() => {
    applyCssVars(colors, themeMode);
  }, [colors, themeMode]);

  const { nodes, connections } = useMemo(
    () => flowToCanvas(flow, schemaMap, execNodeStates, execNodeId, nodeOutputs),
    [flow, schemaMap, execNodeStates, execNodeId, nodeOutputs],
  );

  const selectedNode = nodes.find((n) => n.id === selectedNodeId) || null;

  const canvasLogs = useMemo(
    () =>
      [...logs].reverse().map((l) => ({
        id: String(l.ts) + l.message,
        timestamp: new Date(l.ts).toLocaleTimeString(),
        type: mapLogLevel(l.level),
        message: l.message,
        nodeId: undefined,
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
    clearLogs();
    appendLog({
      level: 'info',
      message: hideWindowOnRecord
        ? '开始运行流程（已隐藏窗口，避免点击落到本程序上）…'
        : '开始运行流程…',
    });
    const payload = filePath ? { ...flow, __file_path__: filePath } : flow;
    const res = await bridge.runFlow(payload, false, hideWindowOnRecord);
    if (!res?.ok) appendLog({ level: 'error', message: res?.error || '启动失败' });
  };

  const handleStep = async () => {
    if (execStatus === 'idle') {
      clearLogs();
      appendLog({ level: 'info', message: '单步模式启动…' });
      const payload = filePath ? { ...flow, __file_path__: filePath } : flow;
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
      appendRecordedNodes(res.nodes || []);
      appendLog({ level: 'ok', message: `录制结束，追加 ${res.nodes?.length || 0} 个节点` });
    }
  };

  const handleToggleRecord = async () => {
    if (!recording) {
      const ok = await confirm({
        title: '开始录制',
        description:
          '录制会把你的鼠标点击、键盘操作转成流程节点，并追加到当前画布。\n\n录制时窗口保持显示，右上角会出现「停止录制」浮层；也可按 Ctrl+Shift+F10。',
        confirmText: '开始录制',
      });
      if (!ok) return;

      // Always keep window visible so RecordingBanner works
      const res = await bridge.startRecording(50, false);
      if (res?.ok) {
        setRecording(true);
        appendLog({
          level: 'info',
          message: '开始录制。点右上角浮层「停止录制」或按 Ctrl+Shift+F10',
        });
      } else {
        appendLog({ level: 'error', message: res?.error || '无法开始录制' });
      }
    } else {
      await stopRecordingNow();
    }
  };

  const handleAddNexuzNode = (blockType: string, position?: { x: number; y: number }) => {
    const id = addNodeFromSchema(blockType, position || {
      x: 250 + Math.random() * 80,
      y: 150 + Math.random() * 80,
    });
    if (id) appendLog({ level: 'info', message: `已添加节点: ${blockType}` });
    else appendLog({ level: 'warn', message: `未知积木类型: ${blockType}` });
  };

  const handleDropBlock = (blockType: string, x: number, y: number) => {
    handleAddNexuzNode(blockType, { x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10 });
  };

  // Design-only demo nodes (unused for backend) — keep Sidebar/AI API shape
  const handleAddDemoNode = (subType: string) => {
    appendLog({
      level: 'warn',
      message: `设计稿节点「${subType}」未接入 Nexuz 后端，请从 Nodes 中选择动作/识别/控制积木`,
    });
  };

  const handleLoadTemplate = (templateId: string) => {
    if (templateId === 'click-loop') {
      setFlow({
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
      });
      appendLog({ level: 'info', message: '已加载点击循环模板' });
      return;
    }
    if (templateId === 'color-branch') {
      setFlow({
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
      });
      appendLog({ level: 'info', message: '已加载颜色分支模板' });
      return;
    }
    // Original design templates — leave UI, no backend wiring
    appendLog({
      level: 'warn',
      message: `设计稿模板「${templateId}」保留未接入，可改用 click-loop / color-branch`,
    });
  };

  const handleUpdateNodePosition = (nodeId: string, x: number, y: number) => {
    updateNodePosition(nodeId, { x, y });
  };

  const handleUpdateNodePositions = (updates: { id: string; x: number; y: number }[]) => {
    updateNodePositions(updates);
  };

  const handleAddConnection = (
    sourceNodeId: string,
    sourceSocketId: string,
    targetNodeId: string,
    _targetSocketId: string,
  ) => {
    const handle = sourceSocketId || 'next';
    setNodeLink(sourceNodeId, handle, targetNodeId);
    appendLog({ level: 'info', message: `已连接 ${sourceNodeId}.${handle} → ${targetNodeId}` });
  };

  const handleRemoveConnection = (connectionId: string) => {
    const conn = connections.find((c) => c.id === connectionId);
    if (!conn) return;
    if (conn.kind === 'data') {
      appendLog({
        level: 'warn',
        message: '数据连线由 {{node.field}} 引用生成，请在参数中修改',
      });
      return;
    }
    removeNodeLink(conn.sourceNodeId, conn.sourceSocketId);
    appendLog({ level: 'info', message: '已移除连线' });
  };

  const handleRemoveNode = (nodeId: string) => {
    deleteNodes([nodeId]);
    appendLog({ level: 'info', message: `已删除节点 ${nodeId}` });
  };

  const handleRemoveNodes = (nodeIds: string[]) => {
    if (!nodeIds.length) return;
    deleteNodes(nodeIds);
    appendLog({ level: 'info', message: `已删除 ${nodeIds.length} 个节点` });
  };

  const handleDuplicateNodes = (nodeIds: string[]) => {
    const newIds = duplicateNodes(nodeIds);
    if (newIds?.length) {
      appendLog({ level: 'info', message: `已复制 ${newIds.length} 个节点` });
    }
    return newIds || [];
  };

  const handleUpdateNodeConfig = (nodeId: string, updatedConfig: any) => {
    updateNodeParams(nodeId, updatedConfig);
  };

  const handleRunSingleNode = async (_nodeId: string) => {
    appendLog({
      level: 'warn',
      message: '单节点运行未单独暴露；请使用顶栏 Run Pipeline 执行整条流程',
    });
  };

  return (
    <div
      style={{ backgroundColor: colors.background }}
      className="flex flex-col h-screen w-screen overflow-hidden font-sans transition-all duration-300"
    >
      <Toolbar
        themeName={themeName as any}
        setThemeName={setThemeName as any}
        themeMode={themeMode as any}
        setThemeMode={setThemeMode as any}
        onRunWorkflow={handleRunWorkflow}
        isExecuting={isExecuting}
        onToggleAssistant={() => setIsAssistantOpen(!isAssistantOpen)}
        isAssistantOpen={isAssistantOpen}
        onClearCanvas={handleClearCanvas}
        onSave={handleSave}
        onOpen={handleOpen}
        onToggleRecord={handleToggleRecord}
        recording={recording}
        onPause={() => bridge.pauseFlow()}
        onResume={() => bridge.resumeFlow()}
        onStop={() => bridge.stopFlow()}
        onStep={handleStep}
        execStatus={execStatus}
        viewMode={viewMode as 'canvas' | 'code'}
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

        {viewMode === 'code' ? (
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
            themeName={themeName as any}
            themeMode={themeMode as any}
            isExecuting={isExecuting}
            executingNodeId={execNodeId}
          />
        )}

        <Inspector
          selectedNode={selectedNode}
          onUpdateNodeConfig={handleUpdateNodeConfig}
          onRunSingleNode={handleRunSingleNode}
          onDeselect={() => selectNode(null)}
          themeName={themeName as any}
          themeMode={themeMode as any}
          logs={canvasLogs}
          rawLogs={logs}
          schemaMap={schemaMap}
          hideWindowOnRecord={hideWindowOnRecord}
          setHideWindowOnRecord={useFlowStore.getState().setHideWindowOnRecord}
          onPickPoint={async () => bridge.pickPoint(hideWindowOnRecord)}
          onPickRegion={async () => bridge.pickRegion(hideWindowOnRecord)}
          onCaptureTemplate={async () => bridge.captureTemplate(hideWindowOnRecord)}
          onSetEntry={(id: string) => useFlowStore.getState().setEntry(id)}
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
        open={recording}
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
