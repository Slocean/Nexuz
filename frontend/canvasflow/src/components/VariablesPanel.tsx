/**
 * Global flow variables panel — edits flow.variables ($name / {{name}}).
 */
import React, { useState } from 'react';
import { Plus, Trash2, Variable } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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

function inferType(value: unknown): 'string' | 'number' | 'boolean' {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  return 'string';
}

function coerce(raw: string, type: 'string' | 'number' | 'boolean'): string | number | boolean {
  if (type === 'number') {
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  }
  if (type === 'boolean') {
    return raw === 'true' || raw === '1';
  }
  return raw;
}

export default function VariablesPanel({ themeName, themeMode }: VariablesPanelProps) {
  const flow = useFlowStore((s) => s.flow);
  const setVariable = useFlowStore((s) => s.setVariable);
  const deleteVariable = useFlowStore((s) => s.deleteVariable);
  const colors = getThemeColors(themeName, themeMode);

  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<'string' | 'number' | 'boolean'>('string');
  const [newValue, setNewValue] = useState('');

  const entries = Object.entries(flow.variables || {}).sort(([a], [b]) => a.localeCompare(b));

  const handleAdd = () => {
    let name = newName.trim().replace(/^\{\{|\}\}$/g, '').trim();
    if (!name) return;
    if (!name.startsWith('$')) name = `$${name.replace(/^\$/, '')}`;
    const value =
      newType === 'boolean'
        ? newValue === 'true' || newValue === '1' || newValue === ''
        : coerce(newValue, newType);
    setVariable(name, newType === 'boolean' && newValue === '' ? false : value);
    setNewName('');
    setNewValue('');
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="font-display font-semibold text-sm opacity-80 mb-1 flex items-center gap-1.5">
          <Variable className="w-4 h-4" />
          全局变量
        </h3>
        <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed">
          在节点参数中用 <code className="font-mono">$name</code> 或{' '}
          <code className="font-mono">{`{{$name}}`}</code> 引用。运行时会注入执行上下文。
        </p>
      </div>

      <div
        style={{ borderColor: colors.border }}
        className="rounded-2xl border p-3 space-y-2.5"
      >
        <Label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
          新增变量
        </Label>
        <Input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="名称，如 target_text"
          className="h-8 text-xs"
        />
        <div className="flex gap-2">
          <Select value={newType} onValueChange={(v: any) => setNewType(v)}>
            <SelectTrigger className="h-8 text-xs w-[110px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="string">字符串</SelectItem>
              <SelectItem value="number">数字</SelectItem>
              <SelectItem value="boolean">布尔</SelectItem>
            </SelectContent>
          </Select>
          {newType === 'boolean' ? (
            <Select value={newValue || 'false'} onValueChange={setNewValue}>
              <SelectTrigger className="h-8 text-xs flex-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">true</SelectItem>
                <SelectItem value="false">false</SelectItem>
              </SelectContent>
            </Select>
          ) : (
            <Input
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder="初始值"
              type={newType === 'number' ? 'number' : 'text'}
              className="h-8 text-xs flex-1"
            />
          )}
        </div>
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
                    themeMode === 'light'
                      ? 'rgba(255,255,255,0.4)'
                      : 'rgba(255,255,255,0.02)',
                  borderColor: colors.border,
                }}
                className="rounded-2xl border p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <code className="text-xs font-mono font-semibold truncate">{name}</code>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-rose-400"
                    onClick={() => deleteVariable(name)}
                    title="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
                <div className="flex gap-2">
                  <Select
                    value={t}
                    onValueChange={(nt: any) => {
                      const raw = String(value ?? '');
                      setVariable(name, coerce(raw === 'true' || raw === 'false' ? raw : raw, nt));
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs w-[100px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="string">字符串</SelectItem>
                      <SelectItem value="number">数字</SelectItem>
                      <SelectItem value="boolean">布尔</SelectItem>
                    </SelectContent>
                  </Select>
                  {t === 'boolean' ? (
                    <Select
                      value={value ? 'true' : 'false'}
                      onValueChange={(v) => setVariable(name, v === 'true')}
                    >
                      <SelectTrigger className="h-8 text-xs flex-1">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true">true</SelectItem>
                        <SelectItem value="false">false</SelectItem>
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      className="h-8 text-xs flex-1 font-mono"
                      type={t === 'number' ? 'number' : 'text'}
                      value={value as any}
                      onChange={(e) => setVariable(name, coerce(e.target.value, t))}
                    />
                  )}
                </div>
                <p style={{ color: colors.secondaryText }} className="text-[10px] font-mono">
                  引用: {name.startsWith('$') ? name : `$${name}`}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
