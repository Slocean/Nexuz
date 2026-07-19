/**
 * Visual editors for object / array / object_array variables.
 */
import React, { useMemo, useState } from 'react';
import { Plus, Trash2, Code2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  COMPLEX_TYPES,
  FIELD_TYPE_LABELS,
  FieldType,
  VarType,
  VariableSchema,
  coerceScalar,
  defaultJsonText,
  isPlainObject,
  parseComplex,
  toJsonText,
} from '../varTypes';

function ScalarCell({
  value,
  fieldType,
  onChange,
  className = '',
}: {
  value: unknown;
  fieldType: FieldType;
  onChange: (v: string | number | boolean) => void;
  className?: string;
}) {
  if (fieldType === 'boolean') {
    return (
      <Select
        value={value ? 'true' : 'false'}
        onValueChange={(v) => onChange(v === 'true')}
      >
        <SelectTrigger className={`h-8 text-xs w-full ${className}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">true</SelectItem>
          <SelectItem value="false">false</SelectItem>
        </SelectContent>
      </Select>
    );
  }
  return (
    <Input
      className={`h-8 text-xs font-mono w-full ${className}`}
      type={fieldType === 'number' ? 'number' : 'text'}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(coerceScalar(e.target.value, fieldType))}
    />
  );
}

function TypeSelect({
  value,
  onChange,
  className = '',
}: {
  value: FieldType;
  onChange: (t: FieldType) => void;
  className?: string;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as FieldType)}>
      <SelectTrigger className={`h-8 text-xs ${className}`}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {(Object.keys(FIELD_TYPE_LABELS) as FieldType[]).map((t) => (
          <SelectItem key={t} value={t}>
            {FIELD_TYPE_LABELS[t]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Key-value row editor for plain objects. */
export function ObjectVisualEditor({
  value,
  schema,
  onChange,
  onSchemaChange,
  secondaryText,
}: {
  value: Record<string, unknown>;
  schema?: VariableSchema;
  onChange: (next: Record<string, unknown>) => void;
  onSchemaChange?: (next: VariableSchema) => void;
  secondaryText: string;
}) {
  const fields = schema?.fields || {};
  const keys = useMemo(() => {
    const fromVal = Object.keys(value || {});
    const fromSchema = Object.keys(fields);
    return Array.from(new Set([...fromSchema, ...fromVal]));
  }, [value, fields]);

  const [newKey, setNewKey] = useState('');
  const [newFieldType, setNewFieldType] = useState<FieldType>('string');

  const setField = (key: string, v: unknown) => {
    onChange({ ...value, [key]: v });
  };

  const removeField = (key: string) => {
    const next = { ...value };
    delete next[key];
    onChange(next);
    if (onSchemaChange && schema) {
      const nextFields = { ...(schema.fields || {}) };
      delete nextFields[key];
      onSchemaChange({ ...schema, type: 'object', fields: nextFields });
    }
  };

  const addField = () => {
    const k = newKey.trim();
    if (!k || k in value) return;
    const def =
      newFieldType === 'number' ? 0 : newFieldType === 'boolean' ? false : '';
    onChange({ ...value, [k]: def });
    if (onSchemaChange) {
      onSchemaChange({
        type: 'object',
        fields: { ...(schema?.fields || {}), [k]: newFieldType },
      });
    }
    setNewKey('');
  };

  const setFieldType = (key: string, ft: FieldType) => {
    if (!onSchemaChange) return;
    onSchemaChange({
      type: 'object',
      fields: { ...(schema?.fields || {}), [key]: ft },
    });
    const cur = value[key];
    if (ft === 'number' && typeof cur !== 'number') {
      setField(key, coerceScalar(String(cur ?? 0), 'number'));
    } else if (ft === 'boolean' && typeof cur !== 'boolean') {
      setField(key, Boolean(cur));
    } else if (ft === 'string' && typeof cur !== 'string') {
      setField(key, String(cur ?? ''));
    }
  };

  return (
    <div className="space-y-2.5">
      {keys.length === 0 ? (
        <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
          暂无字段，在下方添加
        </p>
      ) : (
        <div className="space-y-2">
          {keys.map((key) => {
            const ft = (fields[key] || 'string') as FieldType;
            return (
              <div
                key={key}
                className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-1.5"
              >
                <div className="flex items-center gap-1.5">
                  <code
                    className="text-xs font-mono font-semibold truncate flex-1 min-w-0"
                    title={key}
                  >
                    {key}
                  </code>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-rose-400 shrink-0"
                    onClick={() => removeField(key)}
                    title="删除字段"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
                <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-1.5 items-center">
                  {onSchemaChange ? (
                    <TypeSelect value={ft} onChange={(t) => setFieldType(key, t)} className="w-full" />
                  ) : (
                    <span className="text-[11px] opacity-60">{FIELD_TYPE_LABELS[ft]}</span>
                  )}
                  <ScalarCell
                    value={value[key]}
                    fieldType={ft}
                    onChange={(v) => setField(key, v)}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="rounded-lg border border-dashed border-black/15 dark:border-white/15 p-2 space-y-1.5">
        <Input
          className="h-8 text-xs w-full"
          placeholder="新字段名，如 name"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addField();
          }}
        />
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-1.5">
          <TypeSelect value={newFieldType} onChange={setNewFieldType} className="w-full" />
          <Button
            type="button"
            size="sm"
            className="h-8 w-full"
            onClick={addField}
            disabled={!newKey.trim()}
          >
            <Plus className="w-3.5 h-3.5" />
            添加字段
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Scalar array editor. */
export function ArrayVisualEditor({
  value,
  itemType = 'string',
  onChange,
  onItemTypeChange,
  secondaryText,
}: {
  value: unknown[];
  itemType?: FieldType;
  onChange: (next: unknown[]) => void;
  onItemTypeChange?: (t: FieldType) => void;
  secondaryText: string;
}) {
  const rows = Array.isArray(value) ? value : [];

  const setAt = (i: number, v: unknown) => {
    const next = [...rows];
    next[i] = v;
    onChange(next);
  };

  const removeAt = (i: number) => {
    onChange(rows.filter((_, idx) => idx !== i));
  };

  const add = () => {
    const def = itemType === 'number' ? 0 : itemType === 'boolean' ? false : '';
    onChange([...rows, def]);
  };

  return (
    <div className="space-y-2.5">
      {onItemTypeChange ? (
        <div className="flex items-center gap-2">
          <span style={{ color: secondaryText }} className="text-[11px] shrink-0">
            元素类型
          </span>
          <TypeSelect value={itemType} onChange={onItemTypeChange} className="w-28" />
        </div>
      ) : null}
      {rows.length === 0 ? (
        <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
          空数组，点下方添加元素
        </p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((item, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span className="text-[10px] font-mono opacity-50 w-5 shrink-0">{i}</span>
              <div className="flex-1 min-w-0">
                <ScalarCell
                  value={item}
                  fieldType={itemType}
                  onChange={(v) => setAt(i, v)}
                />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-rose-400 shrink-0"
                onClick={() => removeAt(i)}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
      <Button type="button" variant="ghost" size="sm" className="h-8 px-2 text-xs w-full" onClick={add}>
        <Plus className="w-3.5 h-3.5" />
        添加元素
      </Button>
    </div>
  );
}

/** Table editor for object arrays. */
export function ObjectArrayVisualEditor({
  value,
  schema,
  onChange,
  onSchemaChange,
  secondaryText,
}: {
  value: Record<string, unknown>[];
  schema?: VariableSchema;
  onChange: (next: Record<string, unknown>[]) => void;
  onSchemaChange?: (next: VariableSchema) => void;
  secondaryText: string;
}) {
  const rows = Array.isArray(value) ? value.filter(isPlainObject) : [];
  const fields = schema?.fields || {};
  const columns = useMemo(() => {
    const fromSchema = Object.keys(fields);
    const fromRows: string[] = [];
    for (const row of rows) {
      for (const k of Object.keys(row)) {
        if (!fromRows.includes(k)) fromRows.push(k);
      }
    }
    return Array.from(new Set([...fromSchema, ...fromRows]));
  }, [rows, fields]);

  const [newCol, setNewCol] = useState('');
  const [newColType, setNewColType] = useState<FieldType>('string');

  const setCell = (rowIdx: number, key: string, v: unknown) => {
    const next = rows.map((r, i) => (i === rowIdx ? { ...r, [key]: v } : r));
    onChange(next);
  };

  const removeRow = (rowIdx: number) => {
    onChange(rows.filter((_, i) => i !== rowIdx));
  };

  const addRow = () => {
    const blank: Record<string, unknown> = {};
    for (const col of columns) {
      const ft = (fields[col] || 'string') as FieldType;
      blank[col] = ft === 'number' ? 0 : ft === 'boolean' ? false : '';
    }
    onChange([...rows, blank]);
  };

  const addColumn = () => {
    const k = newCol.trim();
    if (!k || columns.includes(k)) return;
    const def = newColType === 'number' ? 0 : newColType === 'boolean' ? false : '';
    onChange(rows.map((r) => ({ ...r, [k]: r[k] ?? def })));
    if (onSchemaChange) {
      onSchemaChange({
        type: 'object_array',
        fields: { ...(schema?.fields || {}), [k]: newColType },
      });
    }
    setNewCol('');
  };

  const removeColumn = (key: string) => {
    onChange(
      rows.map((r) => {
        const next = { ...r };
        delete next[key];
        return next;
      }),
    );
    if (onSchemaChange && schema) {
      const nextFields = { ...(schema.fields || {}) };
      delete nextFields[key];
      onSchemaChange({ ...schema, type: 'object_array', fields: nextFields });
    }
  };

  const setColType = (key: string, ft: FieldType) => {
    if (!onSchemaChange) return;
    onSchemaChange({
      type: 'object_array',
      fields: { ...(schema?.fields || {}), [key]: ft },
    });
    onChange(
      rows.map((r) => {
        const cur = r[key];
        if (ft === 'number' && typeof cur !== 'number') {
          return { ...r, [key]: coerceScalar(String(cur ?? 0), 'number') };
        }
        if (ft === 'boolean' && typeof cur !== 'boolean') {
          return { ...r, [key]: Boolean(cur) };
        }
        if (ft === 'string' && typeof cur !== 'string') {
          return { ...r, [key]: String(cur ?? '') };
        }
        return r;
      }),
    );
  };

  return (
    <div className="space-y-2.5">
      {/* Column schema management */}
      <div className="space-y-1.5">
        <p style={{ color: secondaryText }} className="text-[11px] font-medium opacity-80">
          列定义
        </p>
        {columns.length === 0 ? (
          <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
            先添加列，再添加行
          </p>
        ) : (
          <div className="space-y-1.5">
            {columns.map((col) => {
              const ft = (fields[col] || 'string') as FieldType;
              return (
                <div
                  key={col}
                  className="flex items-center gap-1.5 rounded-md border border-black/8 dark:border-white/8 px-2 py-1.5"
                >
                  <code className="text-xs font-mono flex-1 min-w-0 truncate" title={col}>
                    {col}
                  </code>
                  {onSchemaChange ? (
                    <TypeSelect
                      value={ft}
                      onChange={(t) => setColType(col, t)}
                      className="w-[6.5rem] shrink-0"
                    />
                  ) : (
                    <span className="text-[11px] opacity-60 shrink-0">{FIELD_TYPE_LABELS[ft]}</span>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-rose-400 shrink-0"
                    title="删除列"
                    onClick={() => removeColumn(col)}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              );
            })}
          </div>
        )}
        <div className="rounded-lg border border-dashed border-black/15 dark:border-white/15 p-2 space-y-1.5">
          <Input
            className="h-8 text-xs w-full"
            placeholder="新列名，如 name"
            value={newCol}
            onChange={(e) => setNewCol(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addColumn();
            }}
          />
          <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-1.5">
            <TypeSelect value={newColType} onChange={setNewColType} className="w-full" />
            <Button
              type="button"
              size="sm"
              className="h-8 w-full"
              onClick={addColumn}
              disabled={!newCol.trim()}
            >
              <Plus className="w-3.5 h-3.5" />
              添加列
            </Button>
          </div>
        </div>
      </div>

      {/* Rows as stacked cards — each field gets full width */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <p style={{ color: secondaryText }} className="text-[11px] font-medium opacity-80">
            数据行（{rows.length}）
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={addRow}
            disabled={columns.length === 0}
          >
            <Plus className="w-3.5 h-3.5" />
            添加行
          </Button>
        </div>
        {rows.length === 0 ? (
          <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
            {columns.length === 0 ? '先添加列' : '暂无数据，点「添加行」'}
          </p>
        ) : (
          <div className="space-y-2">
            {rows.map((row, i) => (
              <div
                key={i}
                className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] font-mono opacity-50">#{i}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-rose-400"
                    onClick={() => removeRow(i)}
                    title="删除行"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
                {columns.map((col) => {
                  const ft = (fields[col] || 'string') as FieldType;
                  return (
                    <div key={col} className="space-y-0.5">
                      <label className="text-[10px] font-mono opacity-60">{col}</label>
                      <ScalarCell
                        value={row[col]}
                        fieldType={ft}
                        onChange={(v) => setCell(i, col, v)}
                      />
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function JsonFallback({
  value,
  type,
  onCommit,
  secondaryText,
}: {
  value: unknown;
  type: VarType;
  onCommit: (text: string) => { ok: boolean; error?: string };
  secondaryText: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(toJsonText(value));
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    setDraft(toJsonText(value));
    setError(null);
  }, [value]);

  if (!COMPLEX_TYPES.includes(type)) return null;

  return (
    <div className="space-y-1.5 pt-1 border-t border-black/5 dark:border-white/5">
      <button
        type="button"
        className="flex items-center gap-1 text-[11px] opacity-70 hover:opacity-100"
        onClick={() => setOpen((v) => !v)}
      >
        <Code2 className="w-3 h-3" />
        {open ? '收起 JSON' : '高级：编辑 JSON'}
      </button>
      {open ? (
        <>
          <Textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError(null);
            }}
            placeholder={defaultJsonText(type)}
            rows={5}
            className="text-xs font-mono leading-relaxed min-h-[5.5rem] resize-y"
          />
          <div className="flex items-center justify-between gap-2">
            <p className={`text-[11px] ${error ? 'text-rose-500' : 'opacity-0'}`}>{error || '·'}</p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => {
                const res = onCommit(draft);
                if (!res.ok) setError(res.error || '无效 JSON');
                else setError(null);
              }}
            >
              应用 JSON
            </Button>
          </div>
          <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
            与上方可视化编辑双向同步
          </p>
        </>
      ) : null}
    </div>
  );
}

/** Combined visual + optional JSON for complex variables. */
export function ComplexVariableEditor({
  type,
  value,
  schema,
  onChange,
  onSchemaChange,
  secondaryText,
}: {
  type: VarType;
  value: unknown;
  schema?: VariableSchema;
  onChange: (next: unknown) => void;
  onSchemaChange?: (next: VariableSchema) => void;
  secondaryText: string;
}) {
  const commitJson = (text: string) => {
    const parsed = parseComplex(text, type);
    if ('error' in parsed) return { ok: false as const, error: parsed.error };
    onChange(parsed.value);
    return { ok: true as const };
  };

  return (
    <div className="space-y-2">
      {type === 'object' ? (
        <ObjectVisualEditor
          value={isPlainObject(value) ? value : {}}
          schema={schema}
          onChange={onChange}
          onSchemaChange={onSchemaChange}
          secondaryText={secondaryText}
        />
      ) : null}
      {type === 'array' ? (
        <ArrayVisualEditor
          value={Array.isArray(value) ? value : []}
          itemType={schema?.itemType || 'string'}
          onChange={onChange}
          onItemTypeChange={
            onSchemaChange
              ? (itemType) => onSchemaChange({ type: 'array', itemType })
              : undefined
          }
          secondaryText={secondaryText}
        />
      ) : null}
      {type === 'object_array' ? (
        <ObjectArrayVisualEditor
          value={Array.isArray(value) ? (value as Record<string, unknown>[]) : []}
          schema={schema}
          onChange={onChange}
          onSchemaChange={onSchemaChange}
          secondaryText={secondaryText}
        />
      ) : null}
      <JsonFallback
        value={value}
        type={type}
        onCommit={commitJson}
        secondaryText={secondaryText}
      />
    </div>
  );
}
