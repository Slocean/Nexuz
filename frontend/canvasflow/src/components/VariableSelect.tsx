/**
 * Dropdown of flow.variables — always synced from the Variables panel.
 * Optional nested path (e.g. users.0.name → $users.0.name).
 */
import React, { useMemo } from 'react';
import { useFlowStore } from '@/store/flowModelStore';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  formatVarRef,
  listFlowVariableNames,
  listValuePaths,
  lookupFlowVariable,
  parseVarRef,
  splitVarPath,
} from '../bindValue';

type Props = {
  /** Current value: `$name`, `$name.0.x`, bare name, or empty */
  value: unknown;
  onChange: (varRef: string) => void;
  /** emit bare name instead of `$name` (no path; path ignored) */
  bare?: boolean;
  /** Allow picking nested path under the root variable */
  allowPath?: boolean;
  placeholder?: string;
  className?: string;
  triggerClassName?: string;
  /** Exclude these bare names (e.g. already used in a keymap) */
  exclude?: string[];
  disabled?: boolean;
};

const ROOT_PATH = '__root__';

function typeTag(value: unknown): string {
  if (typeof value === 'boolean') return '布尔';
  if (typeof value === 'number') return '数字';
  if (Array.isArray(value)) {
    if (value.length && value.every((x) => x && typeof x === 'object' && !Array.isArray(x))) {
      return '对象数组';
    }
    return '数组';
  }
  if (value && typeof value === 'object') return '对象';
  return '字符串';
}

function isComplex(value: unknown): boolean {
  return Array.isArray(value) || (!!value && typeof value === 'object');
}

export default function VariableSelect({
  value,
  onChange,
  bare = false,
  allowPath = true,
  placeholder = '选择变量',
  className,
  triggerClassName,
  exclude = [],
  disabled,
}: Props) {
  const variables = useFlowStore((s) => s.flow.variables || {});
  const names = useMemo(() => {
    const all = listFlowVariableNames(variables);
    if (!exclude.length) return all;
    const ex = new Set(exclude.map((n) => String(n).replace(/^\$/, '')));
    return all.filter((n) => !ex.has(n));
  }, [variables, exclude]);

  const parsed = typeof value === 'string' ? parseVarRef(value) : null;
  const { root: currentRoot, path: currentPath } = splitVarPath(
    parsed || (typeof value === 'string' ? String(value).replace(/^\$/, '') : ''),
  );

  const options = useMemo(() => {
    if (currentRoot && !names.includes(currentRoot) && listFlowVariableNames(variables).includes(currentRoot)) {
      return [currentRoot, ...names];
    }
    return names;
  }, [names, currentRoot, variables]);

  const rootValue = currentRoot ? lookupFlowVariable(variables, currentRoot) : undefined;
  const pathSuggestions = useMemo(() => {
    if (!allowPath || bare || !isComplex(rootValue)) return [];
    return listValuePaths(rootValue, 3).filter(Boolean);
  }, [allowPath, bare, rootValue]);

  const emit = (root: string, path: string) => {
    const r = root.replace(/^\$/, '').trim();
    if (!r) {
      onChange('');
      return;
    }
    if (bare) {
      onChange(r);
      return;
    }
    onChange(formatVarRef(r, path));
  };

  const showPath = allowPath && !bare && !!currentRoot && isComplex(rootValue);
  const pathSelectValue = currentPath || ROOT_PATH;
  const pathOptions = useMemo(() => {
    const set = new Set(pathSuggestions);
    if (currentPath && !set.has(currentPath)) set.add(currentPath);
    return Array.from(set);
  }, [pathSuggestions, currentPath]);

  return (
    <div className={`flex flex-col gap-1 min-w-0 w-full ${className || ''}`}>
      <Select
        value={currentRoot || undefined}
        disabled={disabled || options.length === 0}
        onValueChange={(v) => emit(v, '')}
      >
        <SelectTrigger className={triggerClassName || 'h-8 flex-1 min-w-0 w-full'}>
          <SelectValue
            placeholder={options.length ? placeholder : '暂无变量，请先在「变量」页添加'}
          />
        </SelectTrigger>
        <SelectContent>
          {options.length === 0 ? (
            <SelectItem value="__none" disabled>
              请先在侧栏「变量」页创建
            </SelectItem>
          ) : (
            options.map((v) => (
              <SelectItem key={v} value={v}>
                <span className="flex items-center gap-2">
                  <span>${v}</span>
                  <span className="text-[10px] opacity-50">
                    {typeTag(lookupFlowVariable(variables, v))}
                  </span>
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
          onValueChange={(v) => emit(currentRoot, v === ROOT_PATH ? '' : v)}
        >
          <SelectTrigger className="h-8 w-full text-xs font-mono">
            <SelectValue placeholder="选择下标 / 路径" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ROOT_PATH}>整变量（${currentRoot}）</SelectItem>
            {pathOptions.map((p) => (
              <SelectItem key={p} value={p}>
                <span className="font-mono">.${currentRoot}.{p}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
