import React from 'react';
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Settings,
  Terminal,
  X,
  Copy,
  Check,
  Download,
  Trash2,
  Keyboard
} from 'lucide-react';
import { WorkflowNode, ThemeName, ThemeMode, ExecutionLog } from '../types';
import { useFlowStore } from '@/store/flowModelStore';
import { getThemeColors } from '../theme';
import { logsToText } from '../nexuzAdapter';
import { isBindableInput } from '../bindValue';
import { type BindIssue } from '../bindValidate';
import BindableInput, { OutputRefChip } from './BindableInput';
import VariableSelect from './VariableSelect';
import ExpressionField from './ExpressionField';
import LogicTreeEditor, { normalizeLogicValue } from './LogicTreeEditor';
import { listFlowVariableNames } from '../bindValue';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAppDialog } from './AppDialogs';

interface InspectorProps {
  selectedNode: WorkflowNode | null;
  onUpdateNodeConfig: (nodeId: string, updatedConfig: any) => void;
  onUpdateNodeName?: (nodeId: string, name: string) => void;
  onRemoveNode?: (nodeId: string) => void;
  onDeselect: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  logs: ExecutionLog[];
  schemaMap?: Record<string, any>;
  onPickPoint?: (method?: string) => Promise<any>;
  onPickClick?: (mode: string, method?: string) => Promise<any>;
  onPickRegion?: (method?: string) => Promise<any>;
  onCaptureTemplate?: (method?: string) => Promise<any>;
  /** Delete selected node (Delete / Backspace when not typing) */
  onRemoveNode?: (nodeId: string) => void;
  onSetEntry?: (id: string) => void;
  defaultCaptureMode?: string;
  /** Global default: screenshot | live */
  defaultPickMethod?: string;
  /** Display-capped store logs */
  rawLogs?: { ts?: number; level?: string; message?: string; detail?: any }[];
  /** Full session archive for export */
  fullLogs?: { ts?: number; level?: string; message?: string; detail?: any }[];
  bindIssues?: BindIssue[];
}

/** Edit Record<string, string|number> as rows — keys from flow variables when keyMode=variable */
function KeyMapEditor({
  value,
  onChange,
  keyPlaceholder,
  valueMode,
  keyMode = 'text',
  currentNodeId,
  schemaMap,
  keySuggestions = [],
}: {
  value: Record<string, any>;
  onChange: (next: Record<string, any>) => void;
  keyPlaceholder: string;
  /** bindable = 父流程绑定；subflow_key = 子流程内键（支持 node.colors.0）；plain = 纯文本 */
  valueMode: 'bindable' | 'plain' | 'subflow_key';
  /** variable = 下拉选择已创建全局变量，禁止手输 */
  keyMode?: 'variable' | 'text';
  currentNodeId: string;
  schemaMap: Record<string, any>;
  /** 运行后的子流程可发现键（如 nodeId.colors） */
  keySuggestions?: string[];
}) {
  const variables = useFlowStore(s => s.flow.variables || {});
  const varNames = listFlowVariableNames(variables);
  const entries = Object.entries(value && typeof value === 'object' ? value : {});
  const usedKeys = entries.map(([k]) => String(k).replace(/^\$/, ''));

  const setEntry = (idx: number, key: string, val: any) => {
    const next: Record<string, any> = {};
    entries.forEach(([k, v], i) => {
      if (i === idx) next[key] = val;
      else next[k] = v;
    });
    onChange(next);
  };

  const removeAt = (idx: number) => {
    const next: Record<string, any> = {};
    entries.forEach(([k, v], i) => {
      if (i !== idx) next[k] = v;
    });
    onChange(next);
  };

  const addRow = () => {
    if (keyMode === 'variable') {
      const free = varNames.find(n => !usedKeys.includes(n));
      if (!free) return;
      onChange({ ...Object.fromEntries(entries), [free]: '' });
      return;
    }
    let i = 0;
    let key = `var${i}`;
    const existing = new Set(Object.keys(Object.fromEntries(entries)));
    while (existing.has(key)) {
      i += 1;
      key = `var${i}`;
    }
    onChange({ ...Object.fromEntries(entries), [key]: '' });
  };

  const pathHints = (root: string) => {
    // Common digs when user picks a known array/object root key
    if (root.endsWith('.colors') || root === 'colors') return [`${root}.0`, `${root}.1`];
    if (root.endsWith('.matches') || root === 'matches') {
      return [`${root}.0`, `${root}.0.text`, `${root}.0.x`, `${root}.0.y`];
    }
    if (root.endsWith('.boxes') || root === 'boxes') return [`${root}.0`, `${root}.0.text`];
    return [`${root}.0`];
  };

  return (
    <div className="space-y-2 w-full min-w-0">
      {keyMode === 'variable' && varNames.length === 0 && (
        <p className="text-[11px] text-amber-600 dark:text-amber-400 leading-snug">
          请先在侧栏「变量」页创建全局变量，再添加映射。
        </p>
      )}
      {valueMode === 'subflow_key' && (
        <p className="text-[11px] opacity-55 leading-snug">
          取回值填子流程内键，支持嵌套路径，如 <code className="font-mono">ocr1.matches.0.text</code>、
          <code className="font-mono">color1.colors.0</code>、<code className="font-mono">$result</code>
        </p>
      )}
      {entries.map(([k, v], idx) => (
        <div
          key={idx}
          className="flex flex-col gap-1 rounded-lg border border-black/10 dark:border-white/10 p-1.5 min-w-0">
          <div className="flex items-center gap-1 min-w-0">
            {keyMode === 'variable' ? (
              <VariableSelect
                value={k}
                bare
                exclude={usedKeys.filter(u => u !== String(k).replace(/^\$/, ''))}
                onChange={name => setEntry(idx, name, v)}
                placeholder={keyPlaceholder}
                triggerClassName="h-7 text-xs font-mono flex-1"
              />
            ) : (
              <Input
                className="h-7 text-xs font-mono flex-1 min-w-0"
                placeholder={keyPlaceholder}
                value={k}
                onChange={e => setEntry(idx, e.target.value, v)}
              />
            )}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-rose-400 shrink-0"
              onClick={() => removeAt(idx)}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
          {valueMode === 'bindable' ? (
            <BindableInput
              value={v}
              inputType="string"
              currentNodeId={currentNodeId}
              schemaMap={schemaMap}
              onChange={nv => setEntry(idx, k, nv)}
              placeholder="值"
              allowJson={keyMode === 'variable'}
            />
          ) : (
            <div className="space-y-1 min-w-0">
              <Input
                className="h-7 text-xs font-mono w-full min-w-0"
                placeholder={
                  valueMode === 'subflow_key'
                    ? 'nodeId.colors.0 或 $var'
                    : 'node1.text'
                }
                value={v == null ? '' : String(v)}
                onChange={e => setEntry(idx, k, e.target.value)}
                list={valueMode === 'subflow_key' ? `subflow-keys-${currentNodeId}` : undefined}
              />
              {valueMode === 'subflow_key' && keySuggestions.length > 0 ? (
                <>
                  <datalist id={`subflow-keys-${currentNodeId}`}>
                    {keySuggestions.map(s => (
                      <option key={s} value={s} />
                    ))}
                  </datalist>
                  <div className="flex flex-wrap gap-1">
                    {keySuggestions.slice(0, 16).map(s => (
                      <button
                        type="button"
                        key={s}
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded-md border border-black/10 dark:border-white/10 opacity-70 hover:opacity-100 max-w-full truncate"
                        title={s}
                        onClick={() => setEntry(idx, k, s)}>
                        {s}
                      </button>
                    ))}
                    {/* Quick dig chips for currently typed root */}
                    {typeof v === 'string' &&
                      v.trim() &&
                      !v.includes('.0') &&
                      pathHints(v.trim())
                        .slice(0, 4)
                        .map(p => (
                          <button
                            type="button"
                            key={p}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded-md border border-blue-500/30 text-blue-500 opacity-80 hover:opacity-100"
                            onClick={() => setEntry(idx, k, p)}>
                            {p.includes('.0') ? p.slice(v.trim().length) : `.${p}`}
                          </button>
                        ))}
                  </div>
                </>
              ) : valueMode === 'subflow_key' ? (
                <div className="flex flex-wrap gap-1">
                  {['.0', '.0.text', '.0.x', '.0.y'].map(suf => (
                    <button
                      type="button"
                      key={suf}
                      className="text-[10px] font-mono px-1.5 py-0.5 rounded-md border border-black/10 dark:border-white/10 opacity-70 hover:opacity-100"
                      disabled={!String(v || '').trim()}
                      onClick={() => {
                        const base = String(v || '').trim().replace(/\.(0|0\..*)$/, '');
                        if (!base) return;
                        setEntry(idx, k, `${base}${suf}`);
                      }}>
                      {suf}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        disabled={keyMode === 'variable' && (varNames.length === 0 || usedKeys.length >= varNames.length)}
        onClick={addRow}>
        添加映射
      </Button>
    </div>
  );
}

function PointListEditor({
  value,
  onChange,
  onPickPoint,
  onPickClick,
  captureMode = 'coord',
  showDelay = false,
  pickMethod
}: {
  value: {
    x?: number;
    y?: number;
    delay_ms?: number | string;
    frida_ui?: any;
    button?: string;
  }[];
  onChange: (next: any[]) => void;
  onPickPoint?: (method?: string) => Promise<any>;
  onPickClick?: (mode: string, method?: string) => Promise<any>;
  captureMode?: string;
  showDelay?: boolean;
  /** Resolved pick method for coord mode */
  pickMethod?: string;
}) {
  const { alert } = useAppDialog();
  const points = Array.isArray(value) ? value : [];
  const isFrida = captureMode === 'frida_ui';

  const normalize = (p: any) => {
    const out: any = {
      x: Number(p?.x) || 0,
      y: Number(p?.y) || 0
    };
    if (showDelay && p?.delay_ms != null && p.delay_ms !== '') {
      out.delay_ms = Number(p.delay_ms);
    }
    if (p?.frida_ui && typeof p.frida_ui === 'object') out.frida_ui = p.frida_ui;
    if (p?.button) out.button = p.button;
    if (p?.point_norm) out.point_norm = p.point_norm;
    if (p?.coord_space) out.coord_space = p.coord_space;
    return out;
  };

  const update = (idx: number, patch: Record<string, any>) => {
    onChange(points.map((p, i) => (i === idx ? normalize({ ...p, ...patch }) : normalize(p))));
  };

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= points.length) return;
    const next = [...points];
    const tmp = next[idx];
    next[idx] = next[j];
    next[j] = tmp;
    onChange(next.map(normalize));
  };

  const pickAt = async (idx: number) => {
    const res = onPickClick
      ? await onPickClick(isFrida ? 'frida_ui' : 'coord', pickMethod)
      : await onPickPoint?.(pickMethod);
    if (!res?.ok) {
      await alert({
        title: '录入失败',
        description: res?.error || res?.message || '已取消或超时'
      });
      return;
    }
    const params = res.params || {};
    const patch: any = {
      x: Number(params.x ?? res.x) || 0,
      y: Number(params.y ?? res.y) || 0
    };
    if (params.point_norm || res.point_norm) patch.point_norm = params.point_norm || res.point_norm;
    if (params.coord_space || res.coord_space) {
      patch.coord_space = params.coord_space || res.coord_space;
    }
    if (params.button || res.button) patch.button = params.button || res.button;
    if (params.frida_ui) patch.frida_ui = params.frida_ui;
    else if (isFrida && res.frida_ui) patch.frida_ui = res.frida_ui;
    update(idx, patch);
  };

  return (
    <div className="space-y-2 w-full">
      {points.map((p, idx) => (
        <div key={idx} className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-1.5">
          <div className="flex items-center gap-1">
            <span className="text-[11px] opacity-60 font-medium shrink-0 w-10">#{idx + 1}</span>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0"
              disabled={idx === 0}
              onClick={() => move(idx, -1)}
              title="上移">
              <ChevronUp className="w-3.5 h-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 shrink-0"
              disabled={idx >= points.length - 1}
              onClick={() => move(idx, 1)}
              title="下移">
              <ChevronDown className="w-3.5 h-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-rose-400 shrink-0 ml-auto"
              onClick={() => onChange(points.filter((_, i) => i !== idx).map(normalize))}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
          {isFrida ? (
            <div className="flex items-center gap-1">
              <span className="text-[11px] font-mono opacity-70 truncate flex-1 min-w-0">
                {p.frida_ui?.display_name || p.frida_ui?.hierarchy_path || '尚未录入 Frida UI'}
              </span>
              {(onPickClick || onPickPoint) && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 shrink-0 px-2"
                  onClick={() => pickAt(idx)}>
                  录入
                </Button>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <Input
                className="h-7 text-xs font-mono flex-1 min-w-0"
                placeholder="X"
                value={p.x ?? 0}
                onChange={e => update(idx, { x: Number(e.target.value) || 0 })}
              />
              <Input
                className="h-7 text-xs font-mono flex-1 min-w-0"
                placeholder="Y"
                value={p.y ?? 0}
                onChange={e => update(idx, { y: Number(e.target.value) || 0 })}
              />
              {(onPickClick || onPickPoint) && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 shrink-0 px-2"
                  onClick={() => pickAt(idx)}>
                  取点
                </Button>
              )}
            </div>
          )}
          {showDelay && (
            <Input
              className="h-7 text-xs font-mono w-full"
              placeholder="本点前延迟毫秒（空=用全局）"
              value={p.delay_ms ?? ''}
              onChange={e => {
                const v = e.target.value.trim();
                update(idx, { delay_ms: v === '' ? undefined : Number(v) || 0 });
              }}
            />
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        onClick={() => onChange([...points.map(normalize), { x: 0, y: 0 }])}>
        添加点
      </Button>
    </div>
  );
}

function eventToPyKey(e: KeyboardEvent): string | null {
  const k = e.key;
  if (k === 'Control') return 'ctrl';
  if (k === 'Shift') return 'shift';
  if (k === 'Alt') return 'alt';
  if (k === 'Meta') return 'win';
  if (k === 'Enter') return 'enter';
  if (k === 'Escape') return 'esc';
  if (k === ' ') return 'space';
  if (k === 'Tab') return 'tab';
  if (k === 'Backspace') return 'backspace';
  if (k === 'Delete') return 'delete';
  if (k === 'ArrowUp') return 'up';
  if (k === 'ArrowDown') return 'down';
  if (k === 'ArrowLeft') return 'left';
  if (k === 'ArrowRight') return 'right';
  if (k === 'Home') return 'home';
  if (k === 'End') return 'end';
  if (k === 'PageUp') return 'pageup';
  if (k === 'PageDown') return 'pagedown';
  if (k === 'Insert') return 'insert';
  if (/^F\d{1,2}$/i.test(k)) return k.toLowerCase();
  if (k.length === 1) return k.toLowerCase();
  // Digits on numpad etc.
  if (e.code?.startsWith('Digit')) return e.code.slice(5).toLowerCase();
  if (e.code?.startsWith('Key')) return e.code.slice(3).toLowerCase();
  return null;
}

/** Click to capture a key / hotkey combo (maps to pyautogui names). */
function KeyCaptureInput({ value, onChange }: { value: string[] | string; onChange: (keys: string[]) => void }) {
  const [listening, setListening] = React.useState(false);
  const heldRef = React.useRef<string[]>([]);

  const keysArr = Array.isArray(value)
    ? value.map(String)
    : String(value || '')
        .split('+')
        .map(s => s.trim())
        .filter(Boolean);
  const display = keysArr.length ? keysArr.join(' + ') : '';

  React.useEffect(() => {
    if (!listening) return;
    heldRef.current = [];

    const onDown = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const name = eventToPyKey(e);
      if (!name) return;
      if (!heldRef.current.includes(name)) {
        heldRef.current = [...heldRef.current, name];
      }
    };
    const onUp = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (heldRef.current.length) {
        // Order: modifiers first
        const mods = ['ctrl', 'alt', 'shift', 'win'];
        const ordered = [
          ...mods.filter(m => heldRef.current.includes(m)),
          ...heldRef.current.filter(k => !mods.includes(k))
        ];
        onChange(ordered);
      }
      setListening(false);
    };
    window.addEventListener('keydown', onDown, true);
    window.addEventListener('keyup', onUp, true);
    return () => {
      window.removeEventListener('keydown', onDown, true);
      window.removeEventListener('keyup', onUp, true);
    };
  }, [listening, onChange]);

  return (
    <div className="flex items-center gap-1.5 w-full">
      <div className="flex-1 min-w-0 h-8 px-2 rounded-md border border-black/10 dark:border-white/10 flex items-center font-mono text-xs truncate bg-black/5 dark:bg-white/5">
        {listening ? (
          <span className="text-amber-500 animate-pulse">按下组合键…</span>
        ) : display ? (
          <span title={display}>{display}</span>
        ) : (
          <span className="opacity-40">未录制</span>
        )}
      </div>
      <Button
        type="button"
        variant={listening ? 'default' : 'outline'}
        size="sm"
        className="h-8 shrink-0 px-2"
        onClick={() => setListening(v => !v)}
        title="点击后按下键盘按键进行录制">
        <Keyboard className="w-3.5 h-3.5" />
        {listening ? '取消' : '录制'}
      </Button>
      {keysArr.length > 0 && !listening ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 text-rose-400"
          onClick={() => onChange([])}
          title="清除">
          <X className="w-3.5 h-3.5" />
        </Button>
      ) : null}
    </div>
  );
}

function KeyStepsEditor({
  value,
  onChange
}: {
  value: { keys?: string; delay_ms?: number | string }[];
  onChange: (next: { keys: string; delay_ms?: number }[]) => void;
}) {
  const steps = Array.isArray(value) ? value : [];

  const update = (idx: number, patch: Partial<{ keys: string; delay_ms: number }>) => {
    const next = steps.map((s, i) => {
      if (i !== idx) {
        return {
          keys: typeof s.keys === 'string' ? s.keys : Array.isArray(s.keys) ? (s.keys as any).join('+') : '',
          delay_ms: s.delay_ms as any
        };
      }
      return {
        keys: patch.keys !== undefined ? patch.keys : typeof s.keys === 'string' ? s.keys : '',
        delay_ms:
          patch.delay_ms !== undefined
            ? patch.delay_ms
            : s.delay_ms === '' || s.delay_ms == null
              ? undefined
              : Number(s.delay_ms)
      };
    });
    onChange(next as any);
  };

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= steps.length) return;
    const next = [...steps];
    const tmp = next[idx];
    next[idx] = next[j];
    next[j] = tmp;
    onChange(
      next.map(s => ({
        keys: typeof s.keys === 'string' ? s.keys : Array.isArray(s.keys) ? (s.keys as any).join('+') : '',
        ...(s.delay_ms != null && s.delay_ms !== '' ? { delay_ms: Number(s.delay_ms) } : {})
      })) as any
    );
  };

  return (
    <div className="space-y-2 w-full">
      {steps.map((s, idx) => {
        const keysStr =
          typeof s.keys === 'string' ? s.keys : Array.isArray(s.keys) ? (s.keys as any).join('+') : '';
        return (
          <div key={idx} className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-1.5">
            <div className="flex items-center gap-1">
              <span className="text-[11px] opacity-60 font-medium shrink-0 w-10">#{idx + 1}</span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                disabled={idx === 0}
                onClick={() => move(idx, -1)}>
                <ChevronUp className="w-3.5 h-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 shrink-0"
                disabled={idx >= steps.length - 1}
                onClick={() => move(idx, 1)}>
                <ChevronDown className="w-3.5 h-3.5" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-rose-400 shrink-0 ml-auto"
                onClick={() => onChange(steps.filter((_, i) => i !== idx) as any)}>
                <X className="w-3.5 h-3.5" />
              </Button>
            </div>
            <KeyCaptureInput value={keysStr} onChange={keys => update(idx, { keys: keys.join('+') })} />
            <Input
              className="h-7 text-xs font-mono w-full"
              placeholder="本步前延迟毫秒（空=用全局）"
              value={s.delay_ms ?? ''}
              onChange={e => {
                const v = e.target.value.trim();
                update(idx, { delay_ms: v === '' ? (undefined as any) : Number(v) || 0 });
              }}
            />
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        onClick={() =>
          onChange([
            ...steps.map(s => ({
              keys: typeof s.keys === 'string' ? s.keys : Array.isArray(s.keys) ? (s.keys as any).join('+') : '',
              ...(s.delay_ms != null && s.delay_ms !== '' ? { delay_ms: Number(s.delay_ms) } : {})
            })),
            { keys: '' }
          ] as any)
        }>
        添加步骤
      </Button>
    </div>
  );
}

const CASE_OPS = [
  { value: '==', label: '等于' },
  { value: '!=', label: '不等于' },
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: 'contains', label: '包含' },
];

function caseOpLabel(op?: string): string {
  const o = String(op || '==').trim() || '==';
  return CASE_OPS.find(x => x.value === o)?.label || o;
}

function CasesEditor({
  value,
  onChange,
  currentNodeId,
  schemaMap = {},
}: {
  value: { name?: string; op?: string; value?: string; node_id?: string }[];
  onChange: (cases: { name: string; op: string; value: string; node_id: string }[]) => void;
  currentNodeId?: string;
  schemaMap?: Record<string, any>;
}) {
  const nodes = useFlowStore(s => s.flow.nodes || {});
  // 禁止连回自己：自环容易死循环，重试请用循环节点
  const nodeIds = Object.keys(nodes).filter(id => id !== currentNodeId);
  const cases = Array.isArray(value) ? value : [];
  const [collapsed, setCollapsed] = React.useState<Record<number, boolean>>({});

  const normalize = (
    c: any,
    patch?: Partial<{ name: string; op: string; value: string; node_id: string }>
  ) => ({
    name: typeof c?.name === 'string' ? c.name : '',
    op: typeof c?.op === 'string' && c.op ? c.op : '==',
    value: typeof c?.value === 'string' ? c.value : c?.value != null ? String(c.value) : '',
    node_id: typeof c?.node_id === 'string' ? c.node_id : '',
    ...patch
  });

  const update = (
    idx: number,
    patch: Partial<{ name: string; op: string; value: string; node_id: string }>
  ) => {
    const next = cases.map((c, i) => (i === idx ? normalize(c, patch) : normalize(c)));
    onChange(next);
  };

  return (
    <div className="space-y-2 min-w-0 w-full">
      {cases.map((c, idx) => {
        const closed = !!collapsed[idx];
        const title = (c.name || '').trim() || `分支${idx + 1}`;
        const op = c.op || '==';
        const summary = `${title} · ${caseOpLabel(op)} ${c.value || '（空）'} → ${c.node_id || '未选节点'}`;
        return (
          <div key={idx} className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-2 min-w-0">
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-black/5 dark:hover:bg-white/10 shrink-0"
                onClick={() => setCollapsed(p => ({ ...p, [idx]: !p[idx] }))}
                title={closed ? '展开' : '折叠'}>
                {closed ? (
                  <ChevronRight className="w-3.5 h-3.5 opacity-70" />
                ) : (
                  <ChevronDown className="w-3.5 h-3.5 opacity-70" />
                )}
              </button>
              <span className="text-[11px] opacity-60 font-medium shrink-0 truncate max-w-[7rem]">{title}</span>
              {closed && (
                <span className="text-[11px] opacity-50 truncate flex-1 min-w-0 font-mono">{summary}</span>
              )}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-rose-400 shrink-0 ml-auto"
                onClick={() => onChange(cases.filter((_, i) => i !== idx).map(x => normalize(x)))}>
                <X className="w-3.5 h-3.5" />
              </Button>
            </div>
            {!closed && (
              <>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[11px] opacity-60 shrink-0 w-[4.5rem]">名称</span>
                  <Input
                    className="h-8 text-xs flex-1 min-w-0"
                    placeholder={`分支${idx + 1}`}
                    value={c.name ?? ''}
                    onChange={e => update(idx, { name: e.target.value })}
                  />
                </div>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[11px] opacity-60 shrink-0 w-[4.5rem]">比较</span>
                  <Select
                    value={op}
                    onValueChange={v => update(idx, { op: v })}>
                    <SelectTrigger className="h-8 text-xs flex-1 min-w-0">
                      <SelectValue placeholder="比较方式" />
                    </SelectTrigger>
                    <SelectContent>
                      {CASE_OPS.map(o => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1 min-w-0">
                  {currentNodeId ? (
                    <BindableInput
                      value={c.value ?? ''}
                      inputType="string"
                      currentNodeId={currentNodeId}
                      schemaMap={schemaMap}
                      onChange={nv => update(idx, { value: nv == null ? '' : String(nv) })}
                      placeholder="常量或绑定上游（支持 colors.0）"
                      kindLabel="匹配值类型"
                      valueLabel="匹配值"
                    />
                  ) : (
                    <>
                      <span className="text-[11px] opacity-60">匹配值</span>
                      <Input
                        className="h-8 text-xs flex-1 min-w-0"
                        placeholder="比较值"
                        value={c.value ?? ''}
                        onChange={e => update(idx, { value: e.target.value })}
                      />
                    </>
                  )}
                </div>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[11px] opacity-60 shrink-0 w-[4.5rem]">跳转节点</span>
                  <Select
                    value={c.node_id && c.node_id !== currentNodeId ? c.node_id : undefined}
                    onValueChange={v => update(idx, { node_id: v })}>
                    <SelectTrigger className="h-8 text-xs flex-1 min-w-0">
                      <SelectValue placeholder="跳转 / 画布连线" />
                    </SelectTrigger>
                    <SelectContent>
                      {nodeIds.map(id => (
                        <SelectItem key={id} value={id}>
                          {id}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <p className="text-[10px] opacity-50 pl-[4.5rem]">也可从节点右侧出口拖线（不可连自己）</p>
              </>
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        onClick={() =>
          onChange([
            ...cases.map(c => normalize(c)),
            {
              name: `分支${cases.length + 1}`,
              op: '==',
              value: '',
              node_id: ''
            }
          ])
        }>
        添加分支
      </Button>
    </div>
  );
}

function Field({
  label,
  children,
  stacked = false
}: {
  label: string;
  children: React.ReactNode;
  /** Title above control — use for expression / multi-control editors */
  stacked?: boolean;
}) {
  if (stacked) {
    return (
      <div className="flex flex-col gap-1.5 min-w-0 w-full">
        <Label className="text-xs font-medium opacity-75 leading-none" title={label}>
          {label}
        </Label>
        <div className="w-full min-w-0">{children}</div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2 min-w-0">
      <Label className="text-xs font-medium opacity-75 shrink-0 w-[7.5rem] leading-8" title={label}>
        {label}
      </Label>
      <div className="flex-1 min-w-0 flex items-start gap-1.5 flex-wrap">{children}</div>
    </div>
  );
}

function RectField({
  value,
  onChange,
  onPickRegion,
  applyRegionPick,
  fieldName,
  pickMethod
}: {
  value: any;
  onChange: (v: any) => void;
  onPickRegion?: (method?: string) => Promise<any>;
  applyRegionPick: (name: string, res: any) => void;
  fieldName: string;
  pickMethod?: string;
}) {
  const [draft, setDraft] = React.useState(() => (value ? JSON.stringify(value) : ''));
  const [err, setErr] = React.useState('');

  React.useEffect(() => {
    setDraft(value ? JSON.stringify(value) : '');
    setErr('');
  }, [value]);

  return (
    <div className="flex-1 min-w-0 space-y-1">
      <div className="flex items-center gap-1.5">
        <Input
          className="h-8 flex-1 min-w-0 font-mono text-xs"
          value={draft}
          placeholder="[x1,y1,x2,y2]"
          onChange={e => {
            const text = e.target.value;
            setDraft(text);
            if (!text.trim()) {
              setErr('');
              onChange(null);
              return;
            }
            try {
              const parsed = JSON.parse(text);
              if (!Array.isArray(parsed) || parsed.length !== 4) {
                setErr('需要 [x1,y1,x2,y2] 四个数字');
                return;
              }
              setErr('');
              onChange(parsed);
            } catch {
              setErr('JSON 无效');
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
              const res = await onPickRegion(pickMethod);
              applyRegionPick(fieldName, res);
            }}>
            框选
          </Button>
        )}
      </div>
      {err ? <p className="text-[10px] text-rose-500">{err}</p> : null}
    </div>
  );
}

/** Schema show_when: { field: value | value[] } — all keys must match current config */
function inputVisible(input: any, config: Record<string, any> | undefined): boolean {
  const when = input?.show_when;
  if (!when || typeof when !== 'object') return true;
  const cfg = config || {};
  for (const [key, expect] of Object.entries(when)) {
    const actual = cfg[key];
    // Defaults: source_mode missing → screen (OCR) or capture (conditions)
    let cur = actual;
    if (cur === undefined || cur === null || cur === '') {
      if (key === 'source_mode') {
        // OCR uses screen|image; text/color conditions use capture|value|…
        // When unset: treat as "screen" only for rules that expect screen, else capture.
        cur = String(expect) === 'screen' ? 'screen' : 'capture';
      }
      else if (key === 'wait_type') cur = 'text';
      else if (key === 'click_mode') cur = 'single';
      else if (key === 'key_mode') cur = 'single';
      else if (key === 'sample_mode') cur = 'point';
      else if (key === 'hover_mode') cur = 'single';
      else if (key === 'trigger_type') cur = 'interval';
      else if (key === 'region_mode') cur = 'rect';
      else if (key === 'capture_shape') cur = 'point';
      else if (key === 'color_sample') cur = 'region';
      else return false;
    }
    // Legacy color_detect: sample_mode "single" → region if configured, else point
    if (key === 'sample_mode' && String(cur) === 'single') {
      const hasRegion = Array.isArray(cfg.region) && cfg.region.length === 4;
      cur = hasRegion ? 'region' : 'point';
    }
    if (Array.isArray(expect)) {
      if (!expect.map(String).includes(String(cur))) return false;
    } else if (String(cur) !== String(expect)) {
      return false;
    }
  }
  // wait_until: color + 单点时不显示 region
  if (
    input?.name === 'region' &&
    String(cfg.wait_type || 'text') === 'color' &&
    String(cfg.color_sample || 'region') === 'point'
  ) {
    return false;
  }
  return true;
}

export default function Inspector({
  selectedNode,
  onUpdateNodeConfig,
  onUpdateNodeName,
  onRemoveNode,
  onDeselect,
  themeName,
  themeMode,
  logs,
  schemaMap = {},
  onPickPoint,
  onPickClick,
  onPickRegion,
  onCaptureTemplate,
  onRemoveNode,
  onSetEntry,
  defaultCaptureMode = 'coord',
  defaultPickMethod = 'screenshot',
  rawLogs = [],
  fullLogs = [],
  bindIssues = []
}: InspectorProps) {
  const { alert } = useAppDialog();
  const [copied, setCopied] = React.useState(false);
  const [outputCopied, setOutputCopied] = React.useState(false);
  const [logCopyHint, setLogCopyHint] = React.useState<string | null>(null);
  const logCopyHintTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const logSelectionRef = React.useRef('');
  const logEndRef = React.useRef<HTMLDivElement | null>(null);
  const pickBusyRef = React.useRef(false);
  const clearLogs = useFlowStore(s => s.clearLogs);
  const colors = getThemeColors(themeName, themeMode);

  const showLogCopyHint = (msg: string) => {
    if (logCopyHintTimer.current) clearTimeout(logCopyHintTimer.current);
    setLogCopyHint(msg);
    setCopied(true);
    logCopyHintTimer.current = setTimeout(() => {
      setLogCopyHint(null);
      setCopied(false);
      logCopyHintTimer.current = null;
    }, 1600);
  };

  const nodeIssues = React.useMemo(
    () => (selectedNode ? bindIssues.filter(i => i.nodeId === selectedNode.id) : []),
    [bindIssues, selectedNode]
  );

  const copyText = async (text: string, mark: 'copied' | 'output' | 'silent' = 'copied') => {
    const raw = String(text ?? '');
    if (!raw) {
      if (mark !== 'silent') {
        await alert({ title: '复制', description: '没有可复制的内容' });
      }
      return false;
    }
    const markOk = () => {
      if (mark === 'silent') return;
      if (mark === 'output') {
        setOutputCopied(true);
        setTimeout(() => setOutputCopied(false), 2000);
      } else {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    };
    try {
      const res = await bridge.clipboardWrite(raw);
      if (res?.ok) {
        markOk();
        return true;
      }
    } catch {
      /* fall through */
    }
    try {
      await navigator.clipboard.writeText(raw);
      markOk();
      return true;
    } catch {
      if (mark !== 'silent') {
        await alert({ title: '复制失败', description: '无法写入剪贴板，请手动选中后 Ctrl+C' });
      }
      return false;
    }
  };

  const logsAsText = (source: 'display' | 'full' = 'full') => {
    const rows =
      source === 'full'
        ? fullLogs.length
          ? fullLogs
          : rawLogs
        : rawLogs.length
          ? rawLogs
          : null;
    if (rows && rows.length) {
      return logsToText(
        rows.map((l: any) => ({
          ts: l.ts,
          level: l.level,
          message: l.message,
          detail: l.detail
        }))
      );
    }
    return logsToText(
      logs.map(l => ({
        ts: Date.now(),
        level: l.type,
        message: l.message
      }))
    );
  };

  const exportLogs = async (source: 'display' | 'full' = 'full') => {
    const text = logsAsText(source);
    if (!text.trim()) {
      await alert({ title: '导出日志', description: '暂无日志可导出' });
      return;
    }
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const tag = source === 'full' ? 'full' : 'recent';
    const res = await bridge.exportText(text, `nexuz-logs-${tag}-${stamp}.txt`);
    if (res?.cancelled) return;
    if (!res?.ok) {
      await alert({ title: '导出失败', description: res?.error || '无法保存日志文件' });
      return;
    }
    const count =
      source === 'full'
        ? fullLogs.length || rawLogs.length || logs.length
        : rawLogs.length || logs.length;
    await alert({
      title: '已导出',
      description: res.path
        ? `已保存 ${count} 条（${source === 'full' ? '完整' : '当前显示'}）到\n${res.path}`
        : `已导出 ${count} 条`
    });
  };

  const captureLogSelection = () => {
    try {
      logSelectionRef.current = window.getSelection?.()?.toString?.() || '';
    } catch {
      logSelectionRef.current = '';
    }
  };

  const copySelectedOrAllLogs = async () => {
    const selected = (logSelectionRef.current || window.getSelection?.()?.toString?.() || '').trim();
    const text = selected || logsAsText('full');
    if (!text.trim()) {
      showLogCopyHint('暂无内容');
      return;
    }
    const ok = await copyText(text, 'silent');
    showLogCopyHint(ok ? (selected ? '已复制选中' : '已复制全部') : '复制失败');
  };

  const handleClearLogs = () => {
    clearLogs();
  };

  React.useEffect(() => {
    logEndRef.current?.scrollIntoView({ block: 'end' });
  }, [logs]);

  const logsPanel = (
    <div className="space-y-2 p-3 border-t border-black/10 dark:border-white/10 shrink-0 max-h-[40%] select-text min-w-0 max-w-full overflow-hidden">
      <div className="flex items-center justify-between gap-2 select-none min-w-0">
        <h4 className="font-medium text-sm opacity-70 flex items-center gap-1.5 shrink-0">
          <Terminal className="w-3.5 h-3.5" /> 运行日志
        </h4>
        <div className="flex items-center gap-0.5 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs gap-1 opacity-70 hover:opacity-100"
            onMouseDown={e => {
              captureLogSelection();
              // 避免按钮抢焦点清空选区
              e.preventDefault();
            }}
            onClick={copySelectedOrAllLogs}
            title="复制选中；无选中则复制全部">
            {copied || logCopyHint ? <Check className="w-3 h-3 text-emerald-500" /> : <Copy className="w-3 h-3" />}{' '}
            <span className={logCopyHint ? 'text-emerald-500' : undefined}>{logCopyHint || '复制选中'}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs gap-1 opacity-70 hover:opacity-100"
            onClick={handleClearLogs}
            title="清空运行日志">
            <Trash2 className="w-3 h-3" /> 清空
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs gap-1 opacity-70 hover:opacity-100"
                title="导出日志为 .txt">
                <Download className="w-3 h-3" /> 导出
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[11rem]">
              <DropdownMenuItem onClick={() => exportLogs('full')}>
                完整日志（{fullLogs.length || rawLogs.length || 0}）
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportLogs('display')}>
                当前显示（{rawLogs.length || logs.length}）
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      <div className="h-36 min-w-0 max-w-full overflow-y-auto overflow-x-hidden">
        <div className="space-y-0.5 font-mono text-sm pr-2 select-text cursor-text leading-relaxed min-w-0 w-full max-w-full">
          {logs.length === 0 && (
            <p style={{ color: colors.secondaryText }} className="opacity-60 py-2">
              尚无日志
            </p>
          )}
          {logs.slice(-80).map(log => (
            <div
              key={log.id}
              className={`select-text break-all whitespace-pre-wrap py-0.5 min-w-0 w-full max-w-full ${
                log.type === 'error'
                  ? 'text-rose-500'
                  : log.type === 'success'
                    ? 'text-emerald-500'
                    : log.type === 'warning'
                      ? 'text-amber-500'
                      : ''
              }`}
              style={{
                overflowWrap: 'anywhere',
                wordBreak: 'break-word',
                ...(log.type === 'error' || log.type === 'success' || log.type === 'warning'
                  ? {}
                  : { color: colors.secondaryText }),
              }}>
              <span className="opacity-50 mr-2">{log.timestamp}</span>
              {log.nodeId ? <span className="opacity-60 mr-1 font-medium">[{log.nodeId}]</span> : null}
              {log.message}
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );

  if (!selectedNode) {
    const errN = bindIssues.filter(i => i.level === 'error').length;
    const warnN = bindIssues.filter(i => i.level === 'warn').length;
    return (
      <aside
        style={{
          backgroundColor: colors.surface,
          borderColor: colors.border,
          color: colors.text
        }}
        className="w-[21.8rem] max-w-[21.8rem] min-w-0 overflow-hidden border-l flex flex-col h-full backdrop-blur-xl z-30 shrink-0">
        <div className="flex-1 flex flex-col items-center justify-center text-center p-6 opacity-60 min-w-0">
          <div className="w-12 h-12 mx-auto flex items-center justify-center">
            <img
              src={`${import.meta.env.BASE_URL}logo.png`}
              alt="Nexuz"
              className="max-h-full max-w-full object-contain select-none"
              draggable={false}
            />
          </div>
          <h3 className="font-semibold text-sm mt-2">未选中</h3>
          <p
            style={{ color: colors.secondaryText }}
            className="text-sm leading-relaxed max-w-[180px] mx-auto mt-1">
            点击节点编辑参数
          </p>
          {(errN > 0 || warnN > 0) && (
            <p className="text-xs mt-3 text-rose-500">
              流程绑定：{errN} 错误{warnN ? ` / ${warnN} 警告` : ''}
            </p>
          )}
        </div>
        {logsPanel}
      </aside>
    );
  }

  const handleFieldChange = (key: string, value: any) => {
    const patch: any = {
      ...selectedNode.config,
      [key]: value
    };
    if (key === 'pick_method' && (value == null || value === 'inherit')) {
      delete patch.pick_method;
    }
    // 取色：单点 / 区域 / 多点互斥，切换时清空另一侧残留
    if (key === 'sample_mode' && selectedNode.subType === 'color_detect') {
      const mode = String(value) === 'single' ? 'point' : String(value);
      patch.sample_mode = mode;
      if (mode === 'point') {
        patch.region = null;
        patch.region_norm = undefined;
        patch.points = [];
      } else if (mode === 'region') {
        patch.x = undefined;
        patch.y = undefined;
        patch.point_norm = undefined;
        patch.points = [];
      } else if (mode === 'multi') {
        patch.region = null;
        patch.region_norm = undefined;
        patch.x = undefined;
        patch.y = undefined;
        patch.point_norm = undefined;
      }
    }
    onUpdateNodeConfig(selectedNode.id, patch);
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
    if (selectedNode.subType === 'color_detect') {
      patch.sample_mode = 'region';
      patch.x = undefined;
      patch.y = undefined;
      patch.point_norm = undefined;
      patch.points = [];
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
    if (selectedNode.subType === 'color_detect' && xKey === 'x') {
      patch.sample_mode = 'point';
      patch.region = null;
      patch.region_norm = undefined;
      patch.points = [];
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

  /** Node override or global default. */
  const resolvePickMethod = () => {
    const m = selectedNode?.config?.pick_method;
    if (m === 'live' || m === 'screenshot') return m;
    return defaultPickMethod === 'live' ? 'live' : 'screenshot';
  };

  /** Enter/Space 快捷取点：仅坐标取点（不含 Frida / 框选 / 截模板） */
  const nodeSupportsHotkeyPickPoint = React.useCallback((): boolean => {
    if (!selectedNode || (!onPickPoint && !onPickClick)) return false;
    if (selectedNode.subType === 'click') {
      if (String(selectedNode.config?.click_mode || 'single') !== 'single') return false;
      return resolveClickMode() === 'coord';
    }
    const schema = schemaMap[selectedNode.subType];
    const inputs = schema?.inputs || [];
    return inputs.some(
      (i: any) =>
        (i.name === 'x' || i.name === 'from_x') && inputVisible(i, selectedNode.config),
    );
  }, [selectedNode, onPickPoint, onPickClick, schemaMap, defaultCaptureMode]);

  React.useEffect(() => {
    if (!selectedNode) return;

    const isTypingTarget = (t: EventTarget | null) => {
      if (!t || !(t instanceof HTMLElement)) return false;
      const tag = t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
      if (t.isContentEditable) return true;
      if (t.closest('[role="dialog"]')) return true;
      return false;
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;

      if (e.key === 'Enter' || e.key === ' ') {
        if (!nodeSupportsHotkeyPickPoint()) return;
        e.preventDefault();
        e.stopPropagation();
        void (async () => {
          const pickMethod = resolvePickMethod();
          try {
            if (selectedNode.subType === 'click') {
              const res = onPickClick
                ? await onPickClick('coord', pickMethod)
                : await onPickPoint?.(pickMethod);
              if (!res?.ok) {
                if (res && res.cancelled !== true) {
                  await alert({
                    title: '取点失败',
                    description: res?.error || res?.message || '已取消或超时',
                  });
                }
                return;
              }
              applyClickCapture(res);
              return;
            }
            const schema = schemaMap[selectedNode.subType];
            const inputs = schema?.inputs || [];
            const xInput = inputs.find(
              (i: any) =>
                (i.name === 'x' || i.name === 'from_x') &&
                inputVisible(i, selectedNode.config),
            );
            if (!xInput || !onPickPoint) return;
            const res = await onPickPoint(pickMethod);
            if (!res?.ok) {
              if (res && res.cancelled !== true) {
                await alert({
                  title: '取点失败',
                  description: res?.error || res?.message || '已取消或超时',
                });
              }
              return;
            }
            applyPointPick(xInput.name, res);
          } catch (err: any) {
            await alert({
              title: '取点失败',
              description: String(err?.message || err),
            });
          }
        })();
      }
    };

    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [
    selectedNode,
    onPickPoint,
    onPickClick,
    nodeSupportsHotkeyPickPoint,
    schemaMap,
    alert,
  ]);

  const renderNexuzSchemaForm = () => {
    const schema = schemaMap[selectedNode.subType];
    if (!schema) return null;
    const switchNodeIds =
      selectedNode.subType === 'switch' ? Object.keys(useFlowStore.getState().flow.nodes || {}) : [];
    const isClick = selectedNode.subType === 'click';
    const clickMode = String(selectedNode.config?.click_mode || 'single');
    const isOcr = selectedNode.subType === 'ocr_recognize' || selectedNode.subType === 'if_text_contains';
    const pickMethod = resolvePickMethod();
    const schemaInputs = schema.inputs || [];
    const needsScreenPick =
      isClick ||
      isOcr ||
      schemaInputs.some((i: any) => {
        const n = String(i?.name || '');
        return (
          i?.type === 'rect' ||
          i?.type === 'point_list' ||
          n === 'template_image' ||
          n === 'anchor_template' ||
          n === 'x' ||
          n === 'from_x' ||
          n === 'to_x' ||
          n === 'region' ||
          n === 'search_region'
        );
      });
    const showPickMethodUi =
      needsScreenPick &&
      !!(onPickPoint || onPickRegion || onCaptureTemplate) &&
      !(isClick && resolveClickMode() === 'frida_ui');

    return (
      <div className="space-y-3">
        {showPickMethodUi && (
          <Field label="取点方式">
            <Select
              value={pickMethod}
              onValueChange={v =>
                handleFieldChange('pick_method', v === 'live' ? 'live' : 'screenshot')
              }>
              <SelectTrigger className="h-8 flex-1 min-w-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="screenshot">截图取点</SelectItem>
                <SelectItem value="live">实地取点</SelectItem>
              </SelectContent>
            </Select>
          </Field>
        )}
        {isClick && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 space-y-2">
            <Field label="录入模式">
              <Select
                value={
                  selectedNode.config?.capture_mode === 'frida_ui' || selectedNode.config?.capture_mode === 'coord'
                    ? selectedNode.config.capture_mode
                    : defaultCaptureMode === 'frida_ui'
                      ? 'frida_ui'
                      : 'coord'
                }
                onValueChange={v => handleFieldChange('capture_mode', v)}>
                <SelectTrigger className="h-8 flex-1 min-w-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="coord">坐标</SelectItem>
                  <SelectItem value="frida_ui">Frida UI</SelectItem>
                </SelectContent>
              </Select>
              {clickMode === 'single' && (onPickClick || onPickPoint) && (
                <Button
                  type="button"
                  size="sm"
                  className="h-8 shrink-0 px-2"
                  onClick={async () => {
                    const mode = resolveClickMode();
                    const res = onPickClick
                      ? await onPickClick(mode, pickMethod)
                      : await onPickPoint?.(pickMethod);
                    if (!res?.ok) {
                      await alert({
                        title: '录入失败',
                        description: res?.error || res?.message || '已取消或超时'
                      });
                      return;
                    }
                    applyClickCapture(res);
                  }}>
                  重新录入
                </Button>
              )}
            </Field>
            {clickMode === 'single' &&
            (selectedNode.config?.x != null ||
              selectedNode.config?.frida_ui?.hierarchy_path ||
              selectedNode.config?.button) ? (
              <p className="text-xs font-mono opacity-70 break-all">
                {selectedNode.config?.frida_ui?.display_name ||
                  selectedNode.config?.frida_ui?.hierarchy_path ||
                  (selectedNode.config?.x != null
                    ? `(${selectedNode.config.x}, ${selectedNode.config.y})`
                    : '尚未录入目标')}
                {selectedNode.config?.button ? ` · ${selectedNode.config.button}` : ''}
              </p>
            ) : null}
          </div>
        )}
        {isOcr && (
          <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 space-y-2">
            <p className="text-xs leading-relaxed opacity-90">
              多字结果：<code className="font-mono">{'{{ocr.matches.0.x}}'}</code>
              ；多点取色：<code className="font-mono">{'{{取色.colors.0}}'}</code>
              ；或「文字定位」复用 <code className="font-mono">boxes</code>
            </p>
            {onPickRegion && (
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium opacity-75 shrink-0 w-[7.5rem]">识别区域</span>
                <Button
                  type="button"
                  size="sm"
                  className="h-8 flex-1"
                  onClick={async () => {
                    const res = await onPickRegion(pickMethod);
                    applyRegionPick('region', res);
                  }}>
                  拖拽框选
                </Button>
              </div>
            )}
          </div>
        )}

        {(schema.inputs || [])
          .filter((input: any) => {
            if (input.name === 'pick_method') return false;
            if (!inputVisible(input, selectedNode.config)) return false;
            if (!isClick) return true;
            // Handled in the click panel above / nested object not edited as text
            if (input.name === 'capture_mode' || input.name === 'frida_ui') return false;
            const mode = resolveClickMode();
            if (
              clickMode === 'single' &&
              mode === 'frida_ui' &&
              (input.name === 'x' || input.name === 'y' || input.name === 'move_duration')
            ) {
              return false;
            }
            return true;
          })
          .map((input: any) => {
            const value = selectedNode.config?.[input.name];
            const label = input.label || input.name;
            const optionLabels = input.option_labels || {};
            const stacked =
              input.type === 'keymap' ||
              input.ui === 'input_map' ||
              input.ui === 'output_map' ||
              input.type === 'condition_list' ||
              input.type === 'logic_tree' ||
              input.type === 'cases' ||
              input.type === 'point_list' ||
              input.type === 'key_steps' ||
              input.ui === 'expression' ||
              input.name === 'expression' ||
              input.name === 'exit_condition';
            const placeholder =
              input.placeholder ||
              (typeof input.label === 'string' && !String(input.label).includes('(') ? input.label : input.name);

            return (
              <Field key={input.name} label={label} stacked={stacked}>
                {input.type === 'select' ? (
                  <Select
                    value={
                      input.name === 'sample_mode'
                        ? (() => {
                            const raw = String(value ?? input.default ?? 'point');
                            if (raw === 'single') {
                              const hasRegion =
                                Array.isArray(selectedNode.config?.region) &&
                                selectedNode.config.region.length === 4;
                              return hasRegion ? 'region' : 'point';
                            }
                            return raw;
                          })()
                        : String(value ?? input.default ?? '')
                    }
                    onValueChange={v => handleFieldChange(input.name, v)}>
                    <SelectTrigger className="h-8 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(input.options || []).map((opt: string) => (
                        <SelectItem key={opt} value={opt}>
                          {optionLabels[opt] || opt}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : input.type === 'point_list' ? (
                  <PointListEditor
                    value={Array.isArray(value) ? value : []}
                    onChange={next => handleFieldChange(input.name, next)}
                    onPickPoint={onPickPoint}
                    onPickClick={selectedNode.subType === 'click' ? onPickClick : undefined}
                    captureMode={selectedNode.subType === 'click' ? resolveClickMode() : 'coord'}
                    showDelay={selectedNode.subType === 'click' || selectedNode.subType === 'mouse_hover'}
                    pickMethod={pickMethod}
                  />
                ) : input.type === 'key_steps' ? (
                  <KeyStepsEditor
                    value={Array.isArray(value) ? value : []}
                    onChange={next => handleFieldChange(input.name, next)}
                  />
                ) : input.type === 'color' ? (
                  <>
                    <Input
                      type="color"
                      value={typeof value === 'string' && value.startsWith('#') ? value : '#FF0000'}
                      onChange={e => handleFieldChange(input.name, e.target.value.toUpperCase())}
                      className="h-8 w-10 p-1 cursor-pointer shrink-0"
                    />
                    <BindableInput
                      value={value}
                      inputType="string"
                      currentNodeId={selectedNode.id}
                      schemaMap={schemaMap}
                      onChange={v => handleFieldChange(input.name, v)}
                      placeholder="#RRGGBB"
                    />
                  </>
                ) : input.type === 'keys' ? (
                  <KeyCaptureInput
                    value={Array.isArray(value) ? value : value || []}
                    onChange={keys => handleFieldChange(input.name, keys)}
                  />
                ) : input.type === 'cases' ? (
                  <CasesEditor
                    value={Array.isArray(value) ? value : []}
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                    onChange={cases => handleFieldChange(input.name, cases)}
                  />
                ) : input.type === 'logic_tree' || input.type === 'condition_list' ? (
                  <LogicTreeEditor
                    value={
                      input.type === 'logic_tree'
                        ? (value ??
                          normalizeLogicValue(selectedNode.config?.conditions, selectedNode.config?.mode))
                        : value
                    }
                    legacyMode={selectedNode.config?.mode}
                    onChange={logic => {
                      // Prefer new tree; drop flat legacy fields when present.
                      onUpdateNodeConfig(selectedNode.id, {
                        ...selectedNode.config,
                        logic,
                        mode: undefined,
                        conditions: undefined
                      });
                    }}
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                  />
                ) : input.ui === 'flow_path' || input.name === 'subflow_path' ? (
                  <div className="flex-1 min-w-0 flex items-center gap-1.5">
                    <BindableInput
                      value={value ?? ''}
                      inputType="string"
                      currentNodeId={selectedNode.id}
                      schemaMap={schemaMap}
                      onChange={v => handleFieldChange(input.name, v)}
                      placeholder={input.placeholder || '子流程 .flow.json 路径'}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 shrink-0 px-2"
                      onClick={async () => {
                        const picked = await bridge.pickFlowFile?.();
                        if (picked?.ok && picked.path) {
                          handleFieldChange(input.name, picked.path);
                          return;
                        }
                        if (picked?.cancelled) return;
                        await alert({
                          title: '选择失败',
                          description: picked?.error || '无法打开文件对话框，请手动填写路径'
                        });
                      }}>
                      浏览
                    </Button>
                  </div>
                ) : input.ui === 'collection' ||
                  (selectedNode.subType === 'loop_foreach' && input.name === 'collection') ? (
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <BindableInput
                      value={value ?? ''}
                      inputType="string"
                      currentNodeId={selectedNode.id}
                      schemaMap={schemaMap}
                      onChange={v => handleFieldChange(input.name, v)}
                      placeholder={input.placeholder || '$items 或 {{节点.字段}}'}
                    />
                    <div className="flex flex-col gap-1 min-w-0 w-full">
                      <span className="text-[11px] font-medium opacity-60 leading-none">变量</span>
                      <VariableSelect
                        value={value ?? ''}
                        onChange={v => handleFieldChange(input.name, v)}
                        allowPath
                        placeholder="选择数组变量"
                        triggerClassName="h-8 text-xs w-full"
                      />
                    </div>
                  </div>
                ) : input.type === 'keymap' || input.ui === 'input_map' || input.ui === 'output_map' ? (
                  <KeyMapEditor
                    value={value && typeof value === 'object' && !Array.isArray(value) ? value : {}}
                    onChange={next => handleFieldChange(input.name, next)}
                    keyPlaceholder="变量名"
                    keyMode={input.ui === 'output_map' || input.name === 'mappings' ? 'variable' : 'text'}
                    valueMode={
                      input.ui === 'output_map'
                        ? 'subflow_key'
                        : 'bindable'
                    }
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                    keySuggestions={
                      input.ui === 'output_map' &&
                      Array.isArray((selectedNode.outputData as any)?.keys)
                        ? ((selectedNode.outputData as any).keys as string[])
                        : []
                    }
                  />
                ) : input.type === 'rect' ? (
                  <RectField
                    value={value}
                    onChange={v => handleFieldChange(input.name, v)}
                    onPickRegion={onPickRegion}
                    applyRegionPick={applyRegionPick}
                    fieldName={input.name}
                    pickMethod={pickMethod}
                  />
                ) : input.ui === 'expression' || input.name === 'expression' || input.name === 'exit_condition' ? (
                  <ExpressionField
                    value={value ?? ''}
                    onChange={v => handleFieldChange(input.name, v)}
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                  />
                ) : input.name === 'template_image' || input.name === 'anchor_template' ? (
                  <>
                    <BindableInput
                      value={value}
                      inputType="string"
                      currentNodeId={selectedNode.id}
                      schemaMap={schemaMap}
                      onChange={v => handleFieldChange(input.name, v)}
                      placeholder="模板 PNG 路径"
                    />
                    {onCaptureTemplate && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 shrink-0 px-2"
                        onClick={async () => {
                          const res = await onCaptureTemplate(pickMethod);
                          if (res?.ok && res.path) handleFieldChange(input.name, res.path);
                        }}>
                        截模板
                      </Button>
                    )}
                  </>
                ) : input.ui === 'textarea' || input.type === 'textarea' ? (
                  <BindableInput
                    value={value ?? input.default ?? ''}
                    inputType="string"
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                    onChange={v => handleFieldChange(input.name, v)}
                    placeholder={input.placeholder || placeholder || ''}
                    allowJson
                  />
                ) : selectedNode.subType === 'switch' && input.name === 'default' ? (
                  <div className="flex-1 min-w-0 space-y-1">
                    <Select
                      value={value && value !== selectedNode.id ? String(value) : undefined}
                      onValueChange={v => handleFieldChange('default', v)}>
                      <SelectTrigger className="h-8 text-xs w-full">
                        <SelectValue placeholder="默认分支目标 / 画布「默认」口" />
                      </SelectTrigger>
                      <SelectContent>
                        {switchNodeIds
                          .filter(id => id !== selectedNode.id)
                          .map(id => (
                            <SelectItem key={id} value={id}>
                              {id}
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    <p className="text-[10px] opacity-50">也可从节点右侧「默认」口拖线（不可连自己）</p>
                  </div>
                ) : isBindableInput(input) ? (
                  <BindableInput
                    value={value ?? input.default ?? (input.type === 'number' ? 0 : '')}
                    inputType={input.type === 'number' ? 'number' : 'string'}
                    currentNodeId={selectedNode.id}
                    schemaMap={schemaMap}
                    onChange={v => handleFieldChange(input.name, v)}
                    placeholder={placeholder}
                    allowJson={
                      input.type === 'object' ||
                      input.type === 'array' ||
                      input.type === 'any' ||
                      input.type === 'textarea'
                    }
                    trailing={
                      (input.name === 'x' || input.name === 'from_x' || input.name === 'to_x') && onPickPoint ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 shrink-0 px-2"
                          onClick={async () => {
                            const res = await onPickPoint(pickMethod);
                            applyPointPick(input.name, res);
                          }}>
                          取点
                        </Button>
                      ) : undefined
                    }
                  />
                ) : (
                  <Input
                    className="h-8 w-full"
                    value={value ?? ''}
                    placeholder={placeholder}
                    onChange={e => handleFieldChange(input.name, e.target.value)}
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
                onChange={e => handleFieldChange('systemInstruction', e.target.value)}
              />
            </Field>
            <Field label="Prompt Template">
              <Textarea
                rows={4}
                value={config.prompt || ''}
                onChange={e => handleFieldChange('prompt', e.target.value)}
              />
            </Field>
            <Field label={`Temperature · ${config.temperature ?? 0.7}`}>
              <Input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={config.temperature ?? 0.7}
                onChange={e => handleFieldChange('temperature', parseFloat(e.target.value))}
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
                onValueChange={v => handleFieldChange('targetLanguage', v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['Spanish', 'French', 'German', 'Japanese', 'Chinese', 'Arabic'].map(lang => (
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
                onChange={e => handleFieldChange('text', e.target.value)}
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
                onChange={e => handleFieldChange('wordLimit', parseInt(e.target.value) || 30)}
              />
            </Field>
            <Field label="Fallback Content">
              <Textarea
                rows={3}
                value={config.text || ''}
                onChange={e => handleFieldChange('text', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'kv-store':
        return (
          <div className="space-y-4">
            <Field label="Database Operation">
              <Select value={config.operation || 'write'} onValueChange={v => handleFieldChange('operation', v)}>
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
                onChange={e => handleFieldChange('key', e.target.value)}
                placeholder="e.g. summary_data_v1"
              />
            </Field>
            <Field label="Default Value">
              <Input value={config.value || ''} onChange={e => handleFieldChange('value', e.target.value)} />
            </Field>
          </div>
        );

      case 'api-request':
        return (
          <div className="space-y-4">
            <Field label="REST Method">
              <Select value={config.method || 'GET'} onValueChange={v => handleFieldChange('method', v)}>
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
                onChange={e => handleFieldChange('url', e.target.value)}
              />
            </Field>
          </div>
        );

      case 'if-else':
        return (
          <Field label="Branching Rule">
            <Select value={config.condition || 'true'} onValueChange={v => handleFieldChange('condition', v)}>
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
              onChange={e => handleFieldChange('value', e.target.value)}
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

  const nodeLogs = logs.filter(l => l.nodeId === selectedNode.id);
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
        color: colors.text
      }}
      className="w-[24rem] max-w-[24rem] min-w-0 overflow-hidden border-l flex flex-col h-full backdrop-blur-xl z-30 shrink-0">
      <div className="px-3 py-2 border-b border-black/10 dark:border-white/10 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Settings className="w-3.5 h-3.5 text-slate-400 shrink-0" />
          <h3 className="font-semibold text-sm truncate">节点</h3>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onDeselect}>
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>

      <ScrollArea className="flex-1 min-w-0">
        <div className="p-3 space-y-4 min-w-0 max-w-full overflow-x-hidden">
          <div className="bg-black/5 dark:bg-white/5 rounded-xl px-3 py-2 border border-black/10 dark:border-white/10 space-y-2">
            <div className="flex justify-between items-center gap-2">
              <span className="font-medium text-xs text-blue-500 truncate">
                {selectedNode.subType || selectedNode.type}
              </span>
              <span className="text-xs opacity-50 font-mono shrink-0">{selectedNode.id.substring(0, 6)}</span>
            </div>
            <div className="flex items-center gap-2 min-w-0">
              <Label className="text-xs font-medium opacity-75 shrink-0 w-[7.5rem] leading-8">名称</Label>
              <Input
                className="h-8 flex-1 min-w-0 max-w-[9.8rem]"
                value={selectedNode.name || ''}
                placeholder="节点显示名称"
                onChange={e => onUpdateNodeName?.(selectedNode.id, e.target.value)}
              />
            </div>
          </div>

          {schemaMap[selectedNode.subType]?.description ? (
            <p className="text-[11px] leading-relaxed opacity-60 px-0.5">
              {schemaMap[selectedNode.subType].description}
            </p>
          ) : null}

          <div className="space-y-3">
            <h4 className="font-medium text-sm opacity-70">参数</h4>
            {nodeIssues.length > 0 && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2.5 py-2 space-y-1">
                <p className="text-xs font-medium text-rose-600 dark:text-rose-400">
                  绑定问题 ({nodeIssues.filter(i => i.level === 'error').length} 错误
                  {nodeIssues.some(i => i.level === 'warn')
                    ? ` / ${nodeIssues.filter(i => i.level === 'warn').length} 警告`
                    : ''}
                  )
                </p>
                {nodeIssues.slice(0, 6).map((iss, idx) => (
                  <p
                    key={idx}
                    className={`text-[11px] leading-snug ${
                      iss.level === 'error'
                        ? 'text-rose-600 dark:text-rose-400'
                        : 'text-amber-700 dark:text-amber-400'
                    }`}>
                    {iss.message}
                  </p>
                ))}
              </div>
            )}
            {renderParametersForm()}
          </div>

          <Separator />

          <div className="space-y-3 min-w-0 w-full">
            <div className="flex justify-between items-center">
              <h4 className="font-medium text-sm opacity-70">输出</h4>
              {outputText ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-blue-500 gap-1"
                  onClick={() => copyText(outputText, 'output')}
                  title="复制全部输出">
                  {outputCopied ? (
                    <>
                      <Check className="w-3 h-3 text-emerald-500" />
                      已复制
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      复制
                    </>
                  )}
                </Button>
              ) : null}
            </div>

            {(() => {
              const outs = (schemaMap[selectedNode.subType]?.outputs as { name: string; type?: string }[]) || [];
              const live =
                selectedNode.outputData && typeof selectedNode.outputData === 'object'
                  ? selectedNode.outputData
                  : {};
              if (outs.length === 0) {
                return <p className="text-xs opacity-50 py-2">此节点无声明输出字段</p>;
              }
              return (
                <div
                  style={{ borderColor: colors.border }}
                  className="rounded-xl border divide-y divide-black/5 dark:divide-white/5 min-w-0 w-full">
                  <p className="text-xs opacity-60 px-2 py-1.5 bg-black/[0.03] dark:bg-white/[0.03]">
                    点击字段名复制引用；图片路径悬停预览，点击放大
                  </p>
                  {outs.map(o => (
                    <OutputRefChip
                      key={o.name}
                      nodeId={selectedNode.id}
                      field={o.name}
                      value={(live as any)[o.name]}
                      onCopied={() => {
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      }}
                    />
                  ))}
                </div>
              );
            })()}

            {outputText ? (
              <pre
                style={{
                  backgroundColor: themeMode === 'light' ? '#F1F5F9' : '#05070A',
                  borderColor: colors.border,
                  overflowWrap: 'anywhere',
                  wordBreak: 'break-word',
                }}
                className="rounded-xl p-2 border font-mono text-xs max-h-40 overflow-y-auto overflow-x-hidden whitespace-pre-wrap break-all select-text cursor-text min-w-0 w-full max-w-full"
                tabIndex={0}
                title="可选中后 Ctrl+C 复制">
                {outputText}
              </pre>
            ) : (
              <p className="text-xs opacity-50 py-1">运行后将显示此节点输出</p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h4 className="font-medium text-sm opacity-70">节点运行日志</h4>
              {nodeLogs.length > 0 ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs gap-1 opacity-70 hover:opacity-100"
                  onClick={() => copyText(nodeLogs.map(l => `${l.timestamp || ''} ${l.message}`).join('\n'))}
                  title="复制此节点日志">
                  <Copy className="w-3 h-3" /> 复制
                </Button>
              ) : null}
            </div>
            <div className="space-y-0.5 max-h-36 overflow-y-auto overflow-x-hidden font-mono text-sm leading-relaxed select-text cursor-text rounded-lg border border-black/5 dark:border-white/5 px-2 py-1.5 min-w-0 w-full max-w-full">
              {nodeLogs.length === 0 ? (
                <p className="text-xs opacity-50 py-2">此节点尚无运行日志</p>
              ) : (
                nodeLogs.map(log => (
                  <div
                    key={log.id}
                    className={`break-all whitespace-pre-wrap py-0.5 select-text min-w-0 w-full max-w-full ${
                      log.type === 'error'
                        ? 'text-rose-500'
                        : log.type === 'warning'
                          ? 'text-amber-500'
                          : log.type === 'success'
                            ? 'text-emerald-500'
                            : ''
                    }`}
                    style={{
                      overflowWrap: 'anywhere',
                      wordBreak: 'break-word',
                      ...(log.type === 'error' || log.type === 'warning' || log.type === 'success'
                        ? {}
                        : { color: colors.secondaryText }),
                    }}>
                    <span className="opacity-50 mr-2">{log.timestamp}</span>
                    {log.message}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </ScrollArea>
      {logsPanel}
    </aside>
  );
}
