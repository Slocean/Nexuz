import React from 'react';
import { Settings, Play, Terminal, X, Copy, Check, ChevronRight } from 'lucide-react';
import { WorkflowNode, ThemeName, ThemeMode, ExecutionLog } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface InspectorProps {
  selectedNode: WorkflowNode | null;
  onUpdateNodeConfig: (nodeId: string, updatedConfig: any) => void;
  onRunSingleNode: (nodeId: string) => void;
  onDeselect: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  logs: ExecutionLog[];
  schemaMap?: Record<string, any>;
  hideWindowOnRecord?: boolean;
  setHideWindowOnRecord?: (v: boolean) => void;
  onPickPoint?: () => Promise<any>;
  onPickRegion?: () => Promise<any>;
  onSetEntry?: (id: string) => void;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-[11px] font-bold uppercase tracking-wider opacity-75">{label}</Label>
      {children}
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
  hideWindowOnRecord = true,
  setHideWindowOnRecord,
  onPickPoint,
  onPickRegion,
  onSetEntry,
}: InspectorProps) {
  const [copied, setCopied] = React.useState(false);
  const colors = getThemeColors(themeName, themeMode);

  const logsPanel = (
    <div className="space-y-2 p-4 border-t border-black/5 dark:border-white/5 shrink-0 max-h-[40%]">
      <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60 flex items-center gap-1.5">
        <Terminal className="w-3.5 h-3.5" /> Execution Log
      </h4>
      <ScrollArea className="h-36">
        <div className="space-y-1.5 font-mono text-[10px] pr-2">
          {logs.length === 0 && (
            <p style={{ color: colors.secondaryText }} className="opacity-60 py-2">
              尚无日志
            </p>
          )}
          {logs.slice(0, 40).map((log) => (
            <div
              key={log.id}
              className={`rounded-xl px-2 py-1.5 border border-white/5 ${
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
            className="w-12 h-12 rounded-2xl mx-auto flex items-center justify-center"
          >
            <Settings style={{ color: colors.primary }} className="w-6 h-6" />
          </div>
          <h3 className="font-display font-semibold text-sm mt-3">No node selected</h3>
          <p
            style={{ color: colors.secondaryText }}
            className="text-xs leading-relaxed max-w-[200px] mx-auto mt-2"
          >
            点击画布节点以编辑参数
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

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderNexuzSchemaForm = () => {
    const schema = schemaMap[selectedNode.subType];
    if (!schema) return null;
    const showCapture = ['click', 'drag', 'color_detect', 'if_color_match'].includes(
      selectedNode.subType,
    );

    return (
      <div className="space-y-3">
        {(schema.inputs || []).map((input: any) => {
          const value = selectedNode.config?.[input.name];
          const label = input.label || input.name;

          return (
            <Field key={input.name} label={label}>
              {input.type === 'select' ? (
                <Select
                  value={String(value ?? input.default ?? '')}
                  onValueChange={(v) => handleFieldChange(input.name, v)}
                >
                  <SelectTrigger>
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
                <Input
                  type="number"
                  value={value ?? 0}
                  onChange={(e) => handleFieldChange(input.name, Number(e.target.value))}
                />
              ) : input.type === 'color' ? (
                <div className="flex gap-2">
                  <Input
                    type="color"
                    value={value || '#FF0000'}
                    onChange={(e) => handleFieldChange(input.name, e.target.value.toUpperCase())}
                    className="h-9 w-12 p-1 cursor-pointer"
                  />
                  <Input
                    value={value || ''}
                    onChange={(e) => handleFieldChange(input.name, e.target.value)}
                  />
                </div>
              ) : input.type === 'keys' ? (
                <Input
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
              ) : input.type === 'rect' ? (
                <div className="space-y-2">
                  <Input
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
                      onClick={async () => {
                        const res = await onPickRegion();
                        if (res?.ok) handleFieldChange(input.name, res.region);
                      }}
                    >
                      框选区域
                    </Button>
                  )}
                </div>
              ) : (
                <Input
                  value={value ?? ''}
                  onChange={(e) => handleFieldChange(input.name, e.target.value)}
                />
              )}

              {(input.name === 'x' || input.name === 'from_x') && onPickPoint && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={async () => {
                    const res = await onPickPoint();
                    if (!res?.ok) return;
                    const patch: any = { ...selectedNode.config };
                    patch[input.name] = res.x;
                    patch[input.name === 'from_x' ? 'from_y' : 'y'] = res.y;
                    if (selectedNode.subType.includes('color') && res.color) {
                      patch.target_color = res.color;
                    }
                    onUpdateNodeConfig(selectedNode.id, patch);
                  }}
                >
                  点击选取坐标
                </Button>
              )}
            </Field>
          );
        })}

        {showCapture && setHideWindowOnRecord && (
          <div className="flex items-start gap-2 pt-2 border-t border-white/5">
            <Checkbox
              id="hide-window"
              checked={hideWindowOnRecord}
              onCheckedChange={(v) => setHideWindowOnRecord(!!v)}
              className="mt-0.5"
            />
            <Label htmlFor="hide-window" className="text-xs font-normal cursor-pointer leading-snug">
              录制或点击选取时隐藏程序窗口
            </Label>
          </div>
        )}

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
          <div className="text-center py-6 text-xs text-slate-400 border border-dashed border-white/10 rounded-2xl">
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
      <div className="p-4 border-b border-black/5 dark:border-white/5 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Settings className="w-4 h-4 text-slate-400" />
          <h3 className="font-display font-semibold text-sm">Node Settings</h3>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onDeselect}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-5">
          <div className="bg-black/5 dark:bg-white/5 rounded-2xl p-3.5 border border-white/5">
            <div className="flex justify-between items-center mb-1.5">
              <span className="font-bold text-xs uppercase tracking-wide text-blue-400">
                {selectedNode.type}
              </span>
              <span className="text-[10px] opacity-50 font-mono">
                ID: {selectedNode.id.substring(0, 6)}
              </span>
            </div>
            <h4 className="font-display font-semibold text-sm mb-1">{selectedNode.name}</h4>
            <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed">
              配置下方参数，运行时将传递给下游节点。
            </p>
          </div>

          <div className="space-y-4">
            <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
              Node Parameters
            </h4>
            {renderParametersForm()}
          </div>

          <Separator />

          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
                Terminal Output
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
              className="rounded-2xl p-3 border font-mono text-[11px] space-y-3"
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
              <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
                Debug Console
              </h4>
              <div className="space-y-1.5 max-h-32 overflow-y-auto">
                {nodeLogs.map((log) => (
                  <div
                    key={log.id}
                    className={`text-[10px] font-mono leading-relaxed p-2 rounded-xl flex items-start gap-1.5 border ${
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
