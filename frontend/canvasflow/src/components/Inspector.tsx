import React from 'react';
import { Settings, Play, Terminal, X, Copy, Check, ChevronRight, Download } from 'lucide-react';
import { WorkflowNode, ThemeName, ThemeMode, ExecutionLog } from '../types';
import { useFlowStore } from '@/store/flowModelStore';
import { getThemeColors } from '../theme';
import { logsToText } from '../nexuzAdapter';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useAppDialog } from './AppDialogs';

interface InspectorProps {
  selectedNode: WorkflowNode | null;
  onUpdateNodeConfig: (nodeId: string, updatedConfig: any) => void;
  onRunSingleNode: (nodeId: string) => void;
  onDeselect: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  logs: ExecutionLog[];
  schemaMap?: Record<string, any>;
  onPickPoint?: () => Promise<any>;
  onPickClick?: (mode: string) => Promise<any>;
  onPickRegion?: () => Promise<any>;
  onCaptureTemplate?: () => Promise<any>;
  onSetEntry?: (id: string) => void;
  defaultCaptureMode?: string;
  /** Raw store logs for file export */
  rawLogs?: { ts?: number; level?: string; message?: string; detail?: any }[];
}

function CasesEditor({
  value,
  onChange,
}: {
  value: { value?: string; node_id?: string }[];
  onChange: (cases: { value: string; node_id: string }[]) => void;
}) {
  const nodes = useFlowStore((s) => s.flow.nodes || {});
  const nodeIds = Object.keys(nodes);
  const cases = Array.isArray(value) ? value : [];

  const update = (idx: number, patch: Partial<{ value: string; node_id: string }>) => {
    const next = cases.map((c, i) =>
      i === idx ? { value: c.value || '', node_id: c.node_id || '', ...patch } : { ...c },
    );
    onChange(next as { value: string; node_id: string }[]);
  };

  return (
    <div className="space-y-2">
      {cases.map((c, idx) => (
        <div key={idx} className="flex gap-1.5 items-center">
          <Input
            className="h-8 text-xs flex-1"
            placeholder="匹配值"
            value={c.value ?? ''}
            onChange={(e) => update(idx, { value: e.target.value })}
          />
          <Select
            value={c.node_id || undefined}
            onValueChange={(v) => update(idx, { node_id: v })}
          >
            <SelectTrigger className="h-8 text-xs w-[120px]">
              <SelectValue placeholder="跳转节点" />
            </SelectTrigger>
            <SelectContent>
              {nodeIds.map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-rose-400 shrink-0"
            onClick={() => onChange(cases.filter((_, i) => i !== idx) as any)}
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        onClick={() =>
          onChange([...(cases as any), { value: '', node_id: nodeIds[0] || '' }])
        }
      >
        添加分支
      </Button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 min-w-0">
      <Label
        className="text-xs font-medium opacity-75 shrink-0 w-[4.75rem] leading-8 truncate"
        title={label}
      >
        {label}
      </Label>
      <div className="flex-1 min-w-0 flex items-center gap-1.5 flex-nowrap">{children}</div>
    </div>
  );
}

export default function Inspector({
  selectedNode,
  onUpdateNodeConfig,
  onRunSingleNode,
  onDeselect,
  themeName,
  themeMode,
  logs,
  schemaMap = {},
  onPickPoint,
  onPickClick,
  onPickRegion,
  onCaptureTemplate,
  onSetEntry,
  defaultCaptureMode = 'coord',
  rawLogs = [],
}: InspectorProps) {
  const { alert } = useAppDialog();
  const [copied, setCopied] = React.useState(false);
  const colors = getThemeColors(themeName, themeMode);

  const exportLogs = async () => {
    const text = logsToText(rawLogs.length ? rawLogs : logs.map((l) => ({
      ts: Date.now(),
      level: l.type,
      message: l.message,
    })));
    if (!text.trim()) {
      await alert({ title: '导出日志', description: '暂无日志可导出' });
      return;
    }
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexuz-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const logsPanel = (
    <div className="space-y-2 p-3 border-t border-black/10 dark:border-white/10 shrink-0 max-h-[40%] select-text">
      <div className="flex items-center justify-between gap-2 select-none">
        <h4 className="font-medium text-sm opacity-70 flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5" /> 运行日志
        </h4>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs gap-1 opacity-70 hover:opacity-100"
          onClick={exportLogs}
          title="导出日志为 .txt"
        >
          <Download className="w-3 h-3" /> 导出
        </Button>
      </div>
      <ScrollArea className="h-36">
        <div className="space-y-1.5 font-mono text-xs pr-2 select-text cursor-text">
          {logs.length === 0 && (
            <p style={{ color: colors.secondaryText }} className="opacity-60 py-2">
              尚无日志
            </p>
          )}
          {logs.slice(0, 40).map((log) => (
            <div
              key={log.id}
              className={`rounded-xl px-2 py-1.5 border border-black/10 dark:border-white/10 select-text ${
                log.type === 'error'
                  ? 'text-rose-400'
                  : log.type === 'success'
                    ? 'text-emerald-400'
                    : log.type === 'warning'
                      ? 'text-amber-400'
                      : 'text-slate-400'
              }`}
            >
              <span className="opacity-50 mr-2">{log.timestamp}</span>
              {log.message}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  );

  if (!selectedNode) {
    return (
      <aside
        style={{
          backgroundColor: colors.surface,
          borderColor: colors.border,
          color: colors.text,
        }}
        className="w-80 border-l flex flex-col h-full backdrop-blur-xl z-30 shrink-0"
      >
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 opacity-60">
          <div
            style={{ backgroundColor: colors.primary + '1A' }}
            className="w-10 h-10 rounded-xl mx-auto flex items-center justify-center"
          >
            <Settings style={{ color: colors.primary }} className="w-5 h-5" />
          </div>
          <h3 className="font-semibold text-sm mt-2">未选中</h3>
          <p
            style={{ color: colors.secondaryText }}
            className="text-sm leading-relaxed max-w-[180px] mx-auto mt-1"
          >
            点击节点编辑参数
          </p>
        </div>
        {logsPanel}
      </aside>
    );
  }

  const handleFieldChange = (key: string, value: any) => {
    onUpdateNodeConfig(selectedNode.id, {
      ...selectedNode.config,
      [key]: value,
    });
  };

  const applyRegionPick = (fieldName: string, res: any) => {
    if (!res?.ok || !res.region) return;
    const patch: any = { ...selectedNode.config };
    patch[fieldName] = res.region;
    patch.coord_space = res.coord_space || patch.coord_space;
    if (fieldName === 'search_region') {
      patch.search_region_norm = res.region_norm;
    } else {
      patch.region_norm = res.region_norm;
    }
    onUpdateNodeConfig(selectedNode.id, patch);
  };

  const applyPointPick = (xKey: string, res: any) => {
    if (!res?.ok) return;
    const yKey = xKey === 'from_x' ? 'from_y' : xKey === 'to_x' ? 'to_y' : 'y';
    const patch: any = { ...selectedNode.config };
    const params = res.params || {};
    patch[xKey] = params.x ?? res.x;
    patch[yKey] = params.y ?? res.y;
    patch.coord_space = params.coord_space || res.coord_space || patch.coord_space;
    if (xKey === 'from_x') patch.from_point_norm = params.point_norm || res.point_norm;
    else if (xKey === 'to_x') patch.to_point_norm = params.point_norm || res.point_norm;
    else patch.point_norm = params.point_norm || res.point_norm;
    if (params.button || res.button) patch.button = params.button || res.button;
    if (params.capture_mode) patch.capture_mode = params.capture_mode;
    if (params.coord) patch.coord = params.coord;
    if (selectedNode.subType.includes('color') && res.color) {
      patch.target_color = res.color;
    }
    onUpdateNodeConfig(selectedNode.id, patch);
  };

  const applyClickCapture = (res: any) => {
    if (!res?.ok) return;
    const params = res.params || {};
    const patch: any = { ...selectedNode.config, ...params };
    onUpdateNodeConfig(selectedNode.id, patch);
  };

  const resolveClickMode = () => {
    const nodeMode = selectedNode?.config?.capture_mode;
    if (nodeMode === 'coord' || nodeMode === 'frida_ui') return nodeMode;
    return defaultCaptureMode === 'frida_ui' ? 'frida_ui' : 'coord';
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderNexuzSchemaForm = () => {
    const schema = schemaMap[selectedNode.subType];
    if (!schema) return null;
    const showCapture = [
      'click',
      'drag',
      'color_detect',
      'if_color_match',
      'ocr_recognize',
      'if_text_contains',
      'find_image',
      'screenshot',
      'wait_until',
    ].includes(selectedNode.subType);
    const isClick = selectedNode.subType === 'click';
    const isOcr =
      selectedNode.subType === 'ocr_recognize' ||
      selectedNode.subType === 'if_text_contains';

    return (
      <div className="space-y-3">
        {isClick && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
            <p className="text-xs leading-relaxed opacity-90">
              顶栏「录制」可连续录入多步。此处「重新录入」只更新当前节点；左右键会自动写入。
            </p>
            <Field label="录入模式">
              <Select
                value={String(selectedNode.config?.capture_mode || 'inherit')}
                onValueChange={(v) => {
                  if (v === 'inherit') {
                    const next = { ...selectedNode.config };
                    delete next.capture_mode;
                    onUpdateNodeConfig(selectedNode.id, next);
                  } else {
                    handleFieldChange('capture_mode', v);
                  }
                }}
              >
                <SelectTrigger className="h-8 flex-1 min-w-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="inherit">
                    跟随全局（{defaultCaptureMode === 'frida_ui' ? 'Frida UI' : '坐标'}）
                  </SelectItem>
                  <SelectItem value="coord">坐标</SelectItem>
                  <SelectItem value="frida_ui">Frida UI</SelectItem>
                </SelectContent>
              </Select>
              {(onPickClick || onPickPoint) && (
                <Button
                  type="button"
                  size="sm"
                  className="h-8 shrink-0 px-2"
                  onClick={async () => {
                    const mode = resolveClickMode();
                    const res = onPickClick
                      ? await onPickClick(mode)
                      : await onPickPoint?.();
                    if (!res?.ok) {
                      await alert({
                        title: '录入失败',
                        description: res?.error || res?.message || '已取消或超时',
                      });
                      return;
                    }
                    applyClickCapture(res);
                  }}
                >
                  重新录入
                </Button>
              )}
            </Field>
            {selectedNode.config?.capture_mode === 'frida_ui' ||
            (!selectedNode.config?.capture_mode && defaultCaptureMode === 'frida_ui') ||
            selectedNode.config?.frida_ui?.hierarchy_path ? (
              <p className="text-xs font-mono opacity-70 break-all">
                {selectedNode.config?.frida_ui?.display_name ||
                  selectedNode.config?.frida_ui?.hierarchy_path ||
                  '尚未录入 Frida UI 目标'}
                {selectedNode.config?.button ? ` · ${selectedNode.config.button}` : ''}
              </p>
            ) : null}
          </div>
        )}
        {isOcr && (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 space-y-2">
            <p className="text-xs leading-relaxed opacity-90">
              推荐：全屏拖拽框选识别区域（同时保存相对比例，分辨率变化后自动换算）。
              窗口会移动时，可填「锚点模板」：先找图定位，再在偏移区域 OCR。
            </p>
            {onPickRegion && (
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium opacity-75 shrink-0 w-[4.75rem]">识别区域</span>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 flex-1"
                  onClick={async () => {
                    const res = await onPickRegion();
                    applyRegionPick('region', res);
                  }}
                >
                  拖拽框选
                </Button>
              </div>
            )}
          </div>
        )}

        {(schema.inputs || [])
          .filter((input: any) => {
            if (!isClick) return true;
            // Handled in the click panel above / nested object not edited as text
            if (input.name === 'capture_mode' || input.name === 'frida_ui') return false;
            const mode = resolveClickMode();
            if (mode === 'frida_ui' && (input.name === 'x' || input.name === 'y' || input.name === 'move_duration')) {
              return false;
            }
            return true;
          })
          .map((input: any) => {
          const value = selectedNode.config?.[input.name];
          const label = input.label || input.name;

          return (
            <Field key={input.name} label={label}>
              {input.type === 'select' ? (
                <Select
                  value={String(value ?? input.default ?? '')}
                  onValueChange={(v) => handleFieldChange(input.name, v)}
                >
                  <SelectTrigger className="h-8">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(input.options || []).map((opt: string) => (
                      <SelectItem key={opt} value={opt}>
                        {opt}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : input.type === 'number' ? (
                <>
                  <Input
                    type="number"
                    className="h-8 flex-1 min-w-0"
                    value={value ?? 0}
                    onChange={(e) => handleFieldChange(input.name, Number(e.target.value))}
                  />
                  {(input.name === 'x' || input.name === 'from_x' || input.name === 'to_x') &&
                    onPickPoint && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 shrink-0 px-2"
                        onClick={async () => {
                          const res = await onPickPoint();
                          applyPointPick(input.name, res);
                        }}
                      >
                        取点
                      </Button>
                    )}
                </>
              ) : input.type === 'color' ? (
                <>
                  <Input
                    type="color"
                    value={value || '#FF0000'}
                    onChange={(e) => handleFieldChange(input.name, e.target.value.toUpperCase())}
                    className="h-8 w-10 p-1 cursor-pointer shrink-0"
                  />
                  <Input
                    value={value || ''}
                    onChange={(e) => handleFieldChange(input.name, e.target.value)}
                    className="h-8 flex-1 min-w-0"
                  />
                </>
              ) : input.type === 'keys' ? (
                <Input
                  className="h-8"
                  value={Array.isArray(value) ? value.join('+') : value || ''}
                  placeholder="ctrl+c"
                  onChange={(e) =>
                    handleFieldChange(
                      input.name,
                      e.target.value
                        .split('+')
                        .map((s) => s.trim())
                        .filter(Boolean),
                    )
                  }
                />
              ) : input.type === 'cases' ? (
                <CasesEditor
                  value={Array.isArray(value) ? value : []}
                  onChange={(cases) => handleFieldChange(input.name, cases)}
                />
              ) : input.type === 'rect' ? (
                <>
                  <Input
                    className="h-8 flex-1 min-w-0 font-mono text-xs"
                    value={value ? JSON.stringify(value) : ''}
                    placeholder="[x1,y1,x2,y2]"
                    onChange={(e) => {
                      try {
                        handleFieldChange(input.name, JSON.parse(e.target.value));
                      } catch {
                        /* ignore */
                      }
                    }}
                  />
                  {onPickRegion && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 shrink-0 px-2"
                      onClick={async () => {
                        const res = await onPickRegion();
                        applyRegionPick(input.name, res);
                      }}
                    >
                      框选
                    </Button>
                  )}
                </>
              ) : input.name === 'template_image' ? (
                <>
                  <Input
                    value={value ?? ''}
                    onChange={(e) => handleFieldChange(input.name, e.target.value)}
                    placeholder="模板 PNG 路径"
                    className="h-8 flex-1 min-w-0 font-mono text-xs"
                  />
                  {onCaptureTemplate && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 shrink-0 px-2"
                      onClick={async () => {
                        const res = await onCaptureTemplate();
                        if (res?.ok && res.path) handleFieldChange(input.name, res.path);
                      }}
                    >
                      截模板
                    </Button>
                  )}
                </>
              ) : (
                <Input
                  className="h-8"
                  value={value ?? ''}
                  onChange={(e) => handleFieldChange(input.name, e.target.value)}
                />
              )}
            </Field>
          );
        })}

        {onSetEntry && (
          <Button type="button" variant="outline" size="sm" onClick={() => onSetEntry(selectedNode.id)}>
            设为入口节点
          </Button>
        )}
      </div>
    );
  };

  const renderParametersForm = () => {
    if (schemaMap[selectedNode.subType]) return renderNexuzSchemaForm();

    const { subType, config } = selectedNode;

    switch (subType) {
      case 'chatgpt':
        return (
          <div className="space-y-4">
            <Field label="AI Instruction">
              <Input
                value={config.systemInstruction || 'You are a helpful assistant.'}
                onChange={(e) => handleFieldChange('systemInstruction', e.target.value)}
              />
            </Field>
            <Field label="Prompt Template">
              <Textarea
                rows={4}
                value={config.prompt || ''}
                onChange={(e) => handleFieldChange('prompt', e.target.value)}
              />
            </Field>
            <Field label={`Temperature · ${config.temperature ?? 0.7}`}>
              <Input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={config.temperature ?? 0.7}
                onChange={(e) => handleFieldChange('temperature', parseFloat(e.target.value))}
                className="h-8 accent-blue-500"
              />
            </Field>
          </div>
        );

      case 'translator':
        return (
          <div className="space-y-4">
            <Field label="Target Language">
              <Select
                value={config.targetLanguage || 'Spanish'}
                onValueChange={(v) => handleFieldChange('targetLanguage', v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['Spanish', 'French', 'German', 'Japanese', 'Chinese', 'Arabic'].map((lang) => (
                    <SelectItem key={lang} value={lang}>
                      {lang}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Fallback Input Text">
              <Textarea
                rows={3}
                value={config.text || ''}
                onChange={(e) => handleFieldChange('text', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'summarizer':
        return (
          <div className="space-y-4">
            <Field label="Maximum Word Limit">
              <Input
                type="number"
                value={config.wordLimit || 30}
                onChange={(e) => handleFieldChange('wordLimit', parseInt(e.target.value) || 30)}
              />
            </Field>
            <Field label="Fallback Content">
              <Textarea
                rows={3}
                value={config.text || ''}
                onChange={(e) => handleFieldChange('text', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'kv-store':
        return (
          <div className="space-y-4">
            <Field label="Database Operation">
              <Select
                value={config.operation || 'write'}
                onValueChange={(v) => handleFieldChange('operation', v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="write">Write/Store Record</SelectItem>
                  <SelectItem value="read">Read Record</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Storage Key Name">
              <Input
                value={config.key || ''}
                onChange={(e) => handleFieldChange('key', e.target.value)}
                placeholder="e.g. summary_data_v1"
              />
            </Field>
            <Field label="Default Value">
              <Input
                value={config.value || ''}
                onChange={(e) => handleFieldChange('value', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'api-request':
        return (
          <div className="space-y-4">
            <Field label="REST Method">
              <Select
                value={config.method || 'GET'}
                onValueChange={(v) => handleFieldChange('method', v)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="GET">GET</SelectItem>
                  <SelectItem value="POST">POST</SelectItem>
                  <SelectItem value="PUT">PUT</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Target Endpoint URL">
              <Input
                value={config.url || 'https://api.example.com/feed'}
                onChange={(e) => handleFieldChange('url', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'if-else':
        return (
          <Field label="Branching Rule">
            <Select
              value={config.condition || 'true'}
              onValueChange={(v) => handleFieldChange('condition', v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">Condition IS Met (TRUE)</SelectItem>
                <SelectItem value="false">Condition NOT Met (FALSE)</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        );

      case 'user-input':
        return (
          <Field label="Custom Text Payload">
            <Textarea
              rows={5}
              value={config.value || ''}
              onChange={(e) => handleFieldChange('value', e.target.value)}
            />
          </Field>
        );

      default:
        return (
          <div className="text-center py-6 text-xs text-slate-400 border border-dashed border-black/10 dark:border-white/10 rounded-2xl">
            此节点无需额外参数
          </div>
        );
    }
  };

  const nodeLogs = logs.filter((l) => l.nodeId === selectedNode.id);
  const outputText = selectedNode.outputData
    ? typeof selectedNode.outputData === 'string'
      ? selectedNode.outputData
      : JSON.stringify(selectedNode.outputData, null, 2)
    : '';

  return (
    <aside
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      className="w-80 border-l flex flex-col h-full backdrop-blur-xl z-30 shrink-0"
    >
      <div className="px-3 py-2 border-b border-black/10 dark:border-white/10 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Settings className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <h3 className="font-semibold text-sm truncate">节点</h3>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onDeselect}>
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-3 space-y-4">
          <div className="bg-black/5 dark:bg-white/5 rounded-xl px-3 py-2 border border-black/10 dark:border-white/10">
            <div className="flex justify-between items-center gap-2">
              <span className="font-medium text-xs text-blue-500 truncate">
                {selectedNode.type}
              </span>
              <span className="text-xs opacity-50 font-mono shrink-0">
                {selectedNode.id.substring(0, 6)}
              </span>
            </div>
            <h4 className="font-semibold text-sm mt-0.5 truncate">{selectedNode.name}</h4>
          </div>

          <div className="space-y-3">
            <h4 className="font-medium text-sm opacity-70">
              参数
            </h4>
            {renderParametersForm()}
          </div>

          <Separator />

          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <h4 className="font-medium text-sm opacity-70">
                输出
              </h4>
              {outputText && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-blue-500"
                  onClick={() => copyToClipboard(outputText)}
                >
                  {copied ? (
                    <>
                      <Check className="w-3 h-3 text-emerald-500" />
                      Copied
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      Copy
                    </>
                  )}
                </Button>
              )}
            </div>

            <div
              style={{
                backgroundColor: themeMode === 'light' ? '#F1F5F9' : '#05070A',
                borderColor: colors.border,
              }}
              className="rounded-2xl p-3 border font-mono text-xs space-y-3"
            >
              <div className="text-slate-400 select-text break-all min-h-16 max-h-28 overflow-y-auto">
                {outputText ? (
                  <pre className="text-slate-800 dark:text-slate-300 whitespace-pre-wrap">
                    {outputText}
                  </pre>
                ) : (
                  <span className="italic">暂无输出，请先运行流程</span>
                )}
              </div>
              <Button
                variant="secondary"
                size="sm"
                className="w-full"
                onClick={() => onRunSingleNode(selectedNode.id)}
              >
                <Play className="w-3 h-3 fill-current text-blue-500" />
                Compute Node Solo
              </Button>
            </div>
          </div>

          {nodeLogs.length > 0 && (
            <div className="space-y-2">
              <h4 className="font-medium text-sm opacity-70">
                日志
              </h4>
              <div className="space-y-1.5 max-h-32 overflow-y-auto">
                {nodeLogs.map((log) => (
                  <div
                    key={log.id}
                    className={`text-xs font-mono leading-relaxed p-2 rounded-xl flex items-start gap-1.5 border ${
                      log.type === 'error'
                        ? 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                        : log.type === 'warning'
                          ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                          : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                    }`}
                  >
                    <ChevronRight className="w-3 h-3 shrink-0 mt-0.5" />
                    <span className="break-all">{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
      {logsPanel}
    </aside>
  );
}
