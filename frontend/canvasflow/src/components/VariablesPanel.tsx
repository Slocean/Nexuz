/**
 * Global flow variables panel — edits flow.variables ($name / {{name}}).
 * Supports string / number / boolean / object / array / object[].
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, Variable } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useFlowStore } from '@/store/flowModelStore';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';

interface VariablesPanelProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
}

type VarType = 'string' | 'number' | 'boolean' | 'object' | 'array' | 'object_array';

const TYPE_LABELS: Record<VarType, string> = {
  string: '字符串',
  number: '数字',
  boolean: '布尔',
  object: '对象',
  array: '数组',
  object_array: '对象数组',
};

const COMPLEX_TYPES: VarType[] = ['object', 'array', 'object_array'];

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

function inferType(value: unknown): VarType {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value)) {
    if (value.length === 0) return 'array';
    if (value.every((item) => isPlainObject(item))) return 'object_array';
    return 'array';
  }
  if (isPlainObject(value)) return 'object';
  return 'string';
}

function defaultValueFor(type: VarType): unknown {
  switch (type) {
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'object':
      return {};
    case 'array':
      return [];
    case 'object_array':
      return [{}];
    default:
      return '';
  }
}

function defaultJsonText(type: VarType): string {
  switch (type) {
    case 'object':
      return '{\n  \n}';
    case 'array':
      return '[\n  \n]';
    case 'object_array':
      return '[\n  {\n    \n  }\n]';
    default:
      return '';
  }
}

function toJsonText(value: unknown): string {
  try {
    return JSON.stringify(value ?? null, null, 2);
  } catch {
    return String(value ?? '');
  }
}

/** Parse JSON text for complex types; returns { ok, value, error }. */
function parseComplex(raw: string, type: VarType): { ok: true; value: unknown } | { ok: false; error: string } {
  const text = raw.trim() || (type === 'object' ? '{}' : '[]');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e: any) {
    return { ok: false, error: e?.message || 'JSON 格式错误' };
  }
  if (type === 'object') {
    if (!isPlainObject(parsed)) return { ok: false, error: '对象类型需要 { ... }' };
    return { ok: true, value: parsed };
  }
  if (!Array.isArray(parsed)) return { ok: false, error: '数组类型需要 [ ... ]' };
  if (type === 'object_array') {
    if (!parsed.every((item) => isPlainObject(item))) {
      return { ok: false, error: '对象数组的每一项都必须是对象 { ... }' };
    }
  }
  return { ok: true, value: parsed };
}

function coerceScalar(raw: string, type: 'string' | 'number' | 'boolean'): string | number | boolean {
  if (type === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  }
  if (type === 'boolean') return raw === 'true' || raw === '1';
  return raw;
}

function convertValue(value: unknown, to: VarType): unknown {
  if (to === inferType(value)) return value;
  if (COMPLEX_TYPES.includes(to)) {
    if (to === 'object' && isPlainObject(value)) return value;
    if (to === 'array' && Array.isArray(value)) return value;
    if (to === 'object_array' && Array.isArray(value) && value.every(isPlainObject)) return value;
    // Try parse if was stringified JSON
    if (typeof value === 'string') {
      const parsed = parseComplex(value, to);
      if (parsed.ok) return parsed.value;
    }
    return defaultValueFor(to);
  }
  if (to === 'boolean') return Boolean(value);
  if (to === 'number') {
    const n = Number(value as any);
    return Number.isFinite(n) ? n : 0;
  }
  if (COMPLEX_TYPES.includes(inferType(value))) return toJsonText(value);
  return String(value ?? '');
}

function typeHint(type: VarType, name: string): string {
  const ref = name.startsWith('$') ? name : `$${name}`;
  if (type === 'object') return `引用整对象 ${ref}，或字段 ${ref}.field`;
  if (type === 'array') return `引用整数组 ${ref}，或元素 ${ref}.0`;
  if (type === 'object_array') return `引用整表 ${ref}，或 ${ref}.0.name`;
  return `引用: ${ref}`;
}

function JsonEditor({
  valueText,
  onCommit,
  placeholder,
  secondaryText,
}: {
  valueText: string;
  onCommit: (text: string) => { ok: boolean; error?: string };
  placeholder?: string;
  secondaryText: string;
}) {
  const [draft, setDraft] = useState(valueText);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(valueText);
    setError(null);
  }, [valueText]);

  const apply = () => {
    const res = onCommit(draft);
    if (!res.ok) setError(res.error || '无效 JSON');
    else setError(null);
  };

  return (
    <div className="space-y-1.5 w-full">
      <Textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
        onBlur={apply}
        placeholder={placeholder}
        rows={5}
        className="text-xs font-mono leading-relaxed min-h-[5.5rem] resize-y"
      />
      <div className="flex items-center justify-between gap-2">
        <p className={`text-[11px] ${error ? 'text-rose-500' : 'opacity-0'}`}>{error || '·'}</p>
        <Button type="button" variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={apply}>
          应用 JSON
        </Button>
      </div>
      <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
        合法 JSON；失焦或点「应用」后写入
      </p>
    </div>
  );
}

export default function VariablesPanel({ themeName, themeMode }: VariablesPanelProps) {
  const flow = useFlowStore((s) => s.flow);
  const setVariable = useFlowStore((s) => s.setVariable);
  const deleteVariable = useFlowStore((s) => s.deleteVariable);
  const colors = getThemeColors(themeName, themeMode);

  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<VarType>('string');
  const [newValue, setNewValue] = useState('');
  const [newJson, setNewJson] = useState(defaultJsonText('object'));
  const [addError, setAddError] = useState<string | null>(null);

  const entries = useMemo(
    () => Object.entries(flow.variables || {}).sort(([a], [b]) => a.localeCompare(b)),
    [flow.variables],
  );

  const onNewTypeChange = (t: VarType) => {
    setNewType(t);
    setAddError(null);
    if (COMPLEX_TYPES.includes(t)) setNewJson(defaultJsonText(t));
    else if (t === 'boolean') setNewValue('false');
    else setNewValue('');
  };

  const handleAdd = () => {
    let name = newName.trim().replace(/^\{\{|\}\}$/g, '').trim();
    if (!name) return;
    if (!name.startsWith('$')) name = `$${name.replace(/^\$/, '')}`;
    setAddError(null);

    if (COMPLEX_TYPES.includes(newType)) {
      const parsed = parseComplex(newJson, newType);
      if (!parsed.ok) {
        setAddError(parsed.error);
        return;
      }
      setVariable(name, parsed.value);
    } else if (newType === 'boolean') {
      setVariable(name, newValue === 'true' || newValue === '1');
    } else {
      setVariable(name, coerceScalar(newValue, newType));
    }
    setNewName('');
    setNewValue('');
    setNewJson(defaultJsonText(newType));
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="font-display font-semibold text-sm opacity-80 mb-1 flex items-center gap-1.5">
          <Variable className="w-4 h-4" />
          全局变量
        </h3>
        <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed">
          支持字符串、数字、布尔，以及对象 / 数组 / 对象数组（JSON）。节点中可用{' '}
          <code className="font-mono">$name</code> 或路径{' '}
          <code className="font-mono">$name.0.field</code>。
        </p>
      </div>

      <div style={{ borderColor: colors.border }} className="rounded-2xl border p-3 space-y-2.5">
        <Label className="text-xs font-bold uppercase tracking-wider opacity-75">新增变量</Label>
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="名称，如 users / config"
          className="h-8 text-xs"
        />
        <Select value={newType} onValueChange={(v) => onNewTypeChange(v as VarType)}>
          <SelectTrigger className="h-8 text-xs w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(TYPE_LABELS) as VarType[]).map((t) => (
              <SelectItem key={t} value={t}>
                {TYPE_LABELS[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {newType === 'boolean' ? (
          <Select value={newValue || 'false'} onValueChange={setNewValue}>
            <SelectTrigger className="h-8 text-xs w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="true">true</SelectItem>
              <SelectItem value="false">false</SelectItem>
            </SelectContent>
          </Select>
        ) : COMPLEX_TYPES.includes(newType) ? (
          <div className="space-y-1">
            <Textarea
              value={newJson}
              onChange={(e) => {
                setNewJson(e.target.value);
                setAddError(null);
              }}
              placeholder={defaultJsonText(newType)}
              rows={5}
              className="text-xs font-mono leading-relaxed min-h-[5.5rem] resize-y"
            />
            {addError ? <p className="text-[11px] text-rose-500">{addError}</p> : null}
          </div>
        ) : (
          <Input
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            placeholder={newType === 'number' ? '初始数字' : '初始值'}
            type={newType === 'number' ? 'number' : 'text'}
            className="h-8 text-xs"
          />
        )}

        <Button size="sm" className="w-full" onClick={handleAdd} disabled={!newName.trim()}>
          <Plus className="w-3.5 h-3.5" />
          添加
        </Button>
      </div>

      {entries.length === 0 ? (
        <div
          style={{ color: colors.secondaryText }}
          className="text-center py-10 text-xs border border-dashed rounded-2xl"
        >
          暂无全局变量
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map(([name, value]) => {
            const t = inferType(value);
            return (
              <div
                key={name}
                style={{
                  backgroundColor:
                    themeMode === 'light' ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.02)',
                  borderColor: colors.border,
                }}
                className="rounded-2xl border p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex items-center gap-1.5">
                    <code className="text-xs font-mono font-semibold truncate">{name}</code>
                    <span
                      style={{
                        backgroundColor: colors.primary + '22',
                        color: colors.primary,
                      }}
                      className="text-[10px] px-1.5 py-0.5 rounded-md shrink-0"
                    >
                      {TYPE_LABELS[t]}
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-rose-400 shrink-0"
                    onClick={() => deleteVariable(name)}
                    title="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>

                <Select
                  value={t}
                  onValueChange={(nt) => {
                    setVariable(name, convertValue(value, nt as VarType));
                  }}
                >
                  <SelectTrigger className="h-8 text-xs w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(TYPE_LABELS) as VarType[]).map((key) => (
                      <SelectItem key={key} value={key}>
                        {TYPE_LABELS[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {t === 'boolean' ? (
                  <Select
                    value={value ? 'true' : 'false'}
                    onValueChange={(v) => setVariable(name, v === 'true')}
                  >
                    <SelectTrigger className="h-8 text-xs w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">true</SelectItem>
                      <SelectItem value="false">false</SelectItem>
                    </SelectContent>
                  </Select>
                ) : COMPLEX_TYPES.includes(t) ? (
                  <JsonEditor
                    valueText={toJsonText(value)}
                    secondaryText={colors.secondaryText}
                    placeholder={defaultJsonText(t)}
                    onCommit={(text) => {
                      const parsed = parseComplex(text, t);
                      if (!parsed.ok) return { ok: false, error: parsed.error };
                      setVariable(name, parsed.value);
                      return { ok: true };
                    }}
                  />
                ) : (
                  <Input
                    className="h-8 text-xs w-full font-mono"
                    type={t === 'number' ? 'number' : 'text'}
                    value={value as any}
                    onChange={(e) => setVariable(name, coerceScalar(e.target.value, t))}
                  />
                )}

                <p style={{ color: colors.secondaryText }} className="text-xs font-mono">
                  {typeHint(t, name)}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
