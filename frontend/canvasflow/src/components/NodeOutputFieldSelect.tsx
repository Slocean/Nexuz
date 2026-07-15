/**
 * Pick a node output field, with optional nested path (e.g. colors.0 / matches.0.x).
 */
import React, { useMemo } from 'react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { listValuePaths, splitVarPath } from '../bindValue';

export type OutputMeta = { name: string; type?: string; label?: string };

const ROOT_PATH = '__root__';

function normalizeOutType(t?: string): string {
  const s = String(t || 'any').toLowerCase();
  if (s === 'object_array' || s === 'list') return 'array';
  return s || 'any';
}

/** Fields that commonly hold arrays/objects and need index/path picking. */
export function outputSupportsPath(out: OutputMeta | undefined, runtimeVal?: unknown): boolean {
  if (!out) return false;
  const t = normalizeOutType(out.type);
  if (t === 'any' || t === 'array' || t === 'object') return true;
  if (runtimeVal != null && (Array.isArray(runtimeVal) || typeof runtimeVal === 'object')) {
    return true;
  }
  return false;
}

type Props = {
  /** Full field path: `colors` or `colors.0` or `matches.0.x` */
  value: string;
  outputs: OutputMeta[];
  /** Runtime value of the selected root field (for path suggestions) */
  runtimeRootValue?: unknown;
  onChange: (fieldPath: string) => void;
  disabled?: boolean;
  placeholder?: string;
  triggerClassName?: string;
};

export default function NodeOutputFieldSelect({
  value,
  outputs,
  runtimeRootValue,
  onChange,
  disabled,
  placeholder = '选择字段',
  triggerClassName,
}: Props) {
  const { root, path } = splitVarPath(String(value || ''));

  const selected = outputs.find((o) => o.name === root);
  const showPath = !!root && outputSupportsPath(selected, runtimeRootValue);

  const pathSuggestions = useMemo(() => {
    if (!showPath) return [];
    if (runtimeRootValue != null && (Array.isArray(runtimeRootValue) || typeof runtimeRootValue === 'object')) {
      return listValuePaths(runtimeRootValue, 3).filter(Boolean);
    }
    const t = normalizeOutType(selected?.type);
    if (t === 'array' || t === 'any' || selected?.name === 'colors' || selected?.name === 'matches') {
      return Array.from({ length: 8 }, (_, i) => String(i));
    }
    return [];
  }, [showPath, runtimeRootValue, selected]);

  const emit = (nextRoot: string, nextPath: string) => {
    const r = String(nextRoot || '').trim();
    if (!r) {
      onChange('');
      return;
    }
    const p = String(nextPath || '')
      .replace(/^\./, '')
      .trim();
    onChange(p ? `${r}.${p}` : r);
  };

  const pathSelectValue = path || ROOT_PATH;
  const pathOptions = useMemo(() => {
    const set = new Set(pathSuggestions);
    if (path && !set.has(path)) set.add(path);
    return Array.from(set);
  }, [pathSuggestions, path]);

  return (
    <div className="flex flex-col gap-1 min-w-0 w-full">
      <Select
        value={root || undefined}
        disabled={disabled || outputs.length === 0}
        onValueChange={(v) => emit(v, '')}
      >
        <SelectTrigger className={triggerClassName || 'h-8 w-full text-xs'}>
          <SelectValue placeholder={outputs.length ? placeholder : '—'} />
        </SelectTrigger>
        <SelectContent>
          {outputs.length === 0 ? (
            <SelectItem value="__none" disabled>
              —
            </SelectItem>
          ) : (
            outputs.map((f) => (
              <SelectItem key={f.name} value={f.name}>
                <span className="flex items-center gap-2">
                  <span>{f.label || f.name}</span>
                  {outputSupportsPath(f) ? (
                    <span className="text-[10px] opacity-50">可下标</span>
                  ) : null}
                </span>
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>

      {showPath ? (
        <Select
          value={pathSelectValue}
          disabled={disabled}
          onValueChange={(v) => emit(root, v === ROOT_PATH ? '' : v)}
        >
          <SelectTrigger className="h-8 w-full text-xs font-mono">
            <SelectValue placeholder="选择下标 / 路径" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ROOT_PATH}>整字段（{root}）</SelectItem>
            {pathOptions.map((p) => (
              <SelectItem key={p} value={p}>
                <span className="font-mono">.{p}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
