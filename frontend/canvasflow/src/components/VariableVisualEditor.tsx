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
}: {
  value: unknown;
  fieldType: FieldType;
  onChange: (v: string | number | boolean) => void;
}) {
  if (fieldType === 'boolean') {
    return (
      <Select
        value={value ? 'true' : 'false'}
        onValueChange={(v) => onChange(v === 'true')}
      >
        <SelectTrigger className="h-7 text-xs min-w-[4.5rem]">
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
      className="h-7 text-xs font-mono"
      type={fieldType === 'number' ? 'number' : 'text'}
      value={value == null ? '' : String(value)}
      onChange={(e) => onChange(coerceScalar(e.target.value, fieldType))}
    />
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
    <div className="space-y-2">
      {keys.length === 0 ? (
        <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
          暂无字段，在下方添加
        </p>
      ) : (
        <div className="space-y-1.5">
          {keys.map((key) => {
            const ft = (fields[key] || 'string') as FieldType;
            return (
              <div key={key} className="flex items-center gap-1.5">
                <code className="text-[11px] font-mono w-[30%] truncate shrink-0" title={key}>
                  {key}
                </code>
                {onSchemaChange ? (
                  <Select value={ft} onValueChange={(v) => setFieldType(key, v as FieldType)}>
                    <SelectTrigger className="h-7 text-[10px] w-[4.75rem] shrink-0">
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
                ) : null}
                <div className="flex-1 min-w-0">
                  <ScalarCell
                    value={value[key]}
                    fieldType={ft}
                    onChange={(v) => setField(key, v)}
                  />
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-rose-400 shrink-0"
                  onClick={() => removeField(key)}
                >
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>
            );
          })}
        </div>
      )}
      <div className="flex items-center gap-1.5 pt-0.5">
        <Input
          className="h-7 text-xs flex-1"
          placeholder="新字段名"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addField();
          }}
        />
        <Select value={newFieldType} onValueChange={(v) => setNewFieldType(v as FieldType)}>
          <SelectTrigger className="h-7 text-[10px] w-[4.75rem] shrink-0">
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
        <Button type="button" size="sm" className="h-7 px-2" onClick={addField} disabled={!newKey.trim()}>
          <Plus className="w-3 h-3" />
        </Button>
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
    <div className="space-y-2">
      {onItemTypeChange ? (
        <div className="flex items-center gap-2">
          <span style={{ color: secondaryText }} className="text-[11px]">
            元素类型
          </span>
          <Select value={itemType} onValueChange={(v) => onItemTypeChange(v as FieldType)}>
            <SelectTrigger className="h-7 text-xs w-28">
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
                className="h-7 w-7 text-rose-400 shrink-0"
                onClick={() => removeAt(i)}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            </div>
          ))}
        </div>
      )}
      <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={add}>
        <Plus className="w-3 h-3" />
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
    <div className="space-y-2">
      {columns.length > 0 ? (
        <div className="overflow-x-auto -mx-0.5 px-0.5">
          <table className="w-full text-xs border-collapse min-w-[12rem]">
            <thead>
              <tr>
                <th className="text-left font-normal opacity-50 pr-1 py-1 w-6">#</th>
                {columns.map((col) => (
                  <th key={col} className="text-left font-normal py-1 pr-1 align-bottom">
                    <div className="flex flex-col gap-0.5 min-w-[4.5rem]">
                      <div className="flex items-center gap-0.5">
                        <code className="font-mono text-[10px] truncate" title={col}>
                          {col}
                        </code>
                        <button
                          type="button"
                          className="text-rose-400/80 hover:text-rose-400 p-0.5"
                          title="删除列"
                          onClick={() => removeColumn(col)}
                        >
                          <Trash2 className="w-2.5 h-2.5" />
                        </button>
                      </div>
                      {onSchemaChange ? (
                        <Select
                          value={(fields[col] || 'string') as FieldType}
                          onValueChange={(v) => setColType(col, v as FieldType)}
                        >
                          <SelectTrigger className="h-6 text-[10px]">
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
                      ) : null}
                    </div>
                  </th>
                ))}
                <th className="w-7" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td className="opacity-40 font-mono text-[10px] pr-1 align-middle">{i}</td>
                  {columns.map((col) => (
                    <td key={col} className="pr-1 py-0.5 align-middle">
                      <ScalarCell
                        value={row[col]}
                        fieldType={(fields[col] || 'string') as FieldType}
                        onChange={(v) => setCell(i, col, v)}
                      />
                    </td>
                  ))}
                  <td className="align-middle">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-rose-400"
                      onClick={() => removeRow(i)}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p style={{ color: secondaryText }} className="text-[11px] opacity-70">
          先添加列，再添加行
        </p>
      )}

      <div className="flex items-center gap-1.5 flex-wrap">
        <Input
          className="h-7 text-xs flex-1 min-w-[5rem]"
          placeholder="新列名"
          value={newCol}
          onChange={(e) => setNewCol(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') addColumn();
          }}
        />
        <Select value={newColType} onValueChange={(v) => setNewColType(v as FieldType)}>
          <SelectTrigger className="h-7 text-[10px] w-[4.75rem] shrink-0">
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
        <Button type="button" size="sm" className="h-7 px-2" onClick={addColumn} disabled={!newCol.trim()}>
          <Plus className="w-3 h-3" />
          列
        </Button>
        <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={addRow}>
          <Plus className="w-3 h-3" />
          行
        </Button>
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
    if (!parsed.ok) return { ok: false as const, error: parsed.error };
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
