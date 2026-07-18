/**
 * Global flow variables panel — edits flow.variables + flow.variable_schemas.
 * Visual editors for object / array / object_array; schema-backed types.
 */
import React, { useMemo, useState } from 'react';
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
import { isSystemDefaultVariable, useFlowStore } from '@/store/flowModelStore';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';
import { ComplexVariableEditor } from './VariableVisualEditor';
import {
  COMPLEX_TYPES,
  TYPE_LABELS,
  VarType,
  VariableSchema,
  coerceScalar,
  convertValue,
  defaultSchemaFor,
  defaultValueFor,
  inferType,
  lookupVariableSchema,
  normalizeVarKey,
  parseComplex,
  typeHint,
} from '../varTypes';

interface VariablesPanelProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
}

export default function VariablesPanel({ themeName, themeMode }: VariablesPanelProps) {
  const flow = useFlowStore((s) => s.flow);
  const setVariable = useFlowStore((s) => s.setVariable);
  const setVariableSchema = useFlowStore((s) => s.setVariableSchema);
  const deleteVariable = useFlowStore((s) => s.deleteVariable);
  const colors = getThemeColors(themeName, themeMode);

  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<VarType>('string');
  const [newValue, setNewValue] = useState('');
  const [newComplex, setNewComplex] = useState<unknown>(defaultValueFor('object'));
  const [newSchema, setNewSchema] = useState<VariableSchema>(defaultSchemaFor('object'));
  const [addError, setAddError] = useState<string | null>(null);

  const schemas = (flow.variable_schemas || {}) as Record<string, VariableSchema>;

  const entries = useMemo(
    () =>
      Object.entries(flow.variables || {})
        .filter(([name]) => !isSystemDefaultVariable(name))
        .sort(([a], [b]) => a.localeCompare(b)),
    [flow.variables],
  );

  const onNewTypeChange = (t: VarType) => {
    setNewType(t);
    setAddError(null);
    if (COMPLEX_TYPES.includes(t)) {
      const v = defaultValueFor(t);
      setNewComplex(v);
      setNewSchema(defaultSchemaFor(t, v));
    } else if (t === 'boolean') {
      setNewValue('false');
    } else {
      setNewValue('');
    }
  };

  const handleAdd = () => {
    const name = normalizeVarKey(newName);
    if (!name) return;
    setAddError(null);
    if (isSystemDefaultVariable(name)) {
      setAddError('系统默认变量不可新增或覆盖（$true / $false / $empty / $zero）');
      return;
    }

    if (COMPLEX_TYPES.includes(newType)) {
      // Validate shape once more via JSON roundtrip rules
      const check = parseComplex(JSON.stringify(newComplex ?? defaultValueFor(newType)), newType);
      if (!check.ok) {
        setAddError(check.error);
        return;
      }
      setVariable(name, check.value, newSchema?.type === newType ? newSchema : defaultSchemaFor(newType, check.value));
    } else if (newType === 'boolean') {
      setVariable(name, newValue === 'true' || newValue === '1', { type: 'boolean' });
    } else {
      setVariable(name, coerceScalar(newValue, newType), { type: newType });
    }
    setNewName('');
    setNewValue('');
    setNewComplex(defaultValueFor(newType));
    setNewSchema(defaultSchemaFor(newType));
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="font-display font-semibold text-sm opacity-80 mb-1 flex items-center gap-1.5">
          <Variable className="w-4 h-4" />
          全局变量
        </h3>
        <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed">
          支持字符串、数字、布尔，以及对象 / 数组 / 对象数组（可视化编辑，类型写入 schema）。节点中可用{' '}
          <code className="font-mono">$name</code> 或路径{' '}
          <code className="font-mono">$name.0.field</code>。系统常量{' '}
          <code className="font-mono">$true</code> / <code className="font-mono">$false</code> /{' '}
          <code className="font-mono">$empty</code> / <code className="font-mono">$zero</code>{' '}
          可直接绑定，不在此列表中编辑。
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
            <ComplexVariableEditor
              type={newType}
              value={newComplex}
              schema={newSchema}
              onChange={setNewComplex}
              onSchemaChange={setNewSchema}
              secondaryText={colors.secondaryText}
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
            const schema = lookupVariableSchema(name, schemas);
            const t: VarType = schema?.type || inferType(value);
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
                    const nextType = nt as VarType;
                    const nextVal = convertValue(value, nextType);
                    const nextSchema = defaultSchemaFor(nextType, nextVal);
                    setVariable(name, nextVal, nextSchema);
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
                    onValueChange={(v) => setVariable(name, v === 'true', { type: 'boolean' })}
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
                  <ComplexVariableEditor
                    type={t}
                    value={value}
                    schema={schema?.type === t ? schema : defaultSchemaFor(t, value)}
                    onChange={(next) =>
                      setVariable(name, next, schema?.type === t ? schema : defaultSchemaFor(t, next))
                    }
                    onSchemaChange={(nextSchema) => setVariableSchema(name, nextSchema)}
                    secondaryText={colors.secondaryText}
                  />
                ) : (
                  <Input
                    className="h-8 text-xs w-full font-mono"
                    type={t === 'number' ? 'number' : 'text'}
                    value={value as any}
                    onChange={(e) =>
                      setVariable(name, coerceScalar(e.target.value, t), { type: t })
                    }
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
