/**
 * Dropdown of flow.variables — always synced from the Variables panel.
 * Optional nested path (e.g. users.0.name → $users.0.name).
 */
import React, { useMemo, useState, useEffect } from 'react';
import { useFlowStore } from '@/store/flowModelStore';
import { Input } from '@/components/ui/input';
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

  const [pathDraft, setPathDraft] = useState(currentPath);
  useEffect(() => {
    setPathDraft(currentPath);
  }, [currentPath, currentRoot]);

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

  return (
    <div className={`flex flex-col gap-1 min-w-0 w-full ${className || ''}`}>
      <Select
        value={currentRoot || undefined}
        disabled={disabled || options.length === 0}
        onValueChange={(v) => {
          setPathDraft('');
          emit(v, '');
        }}
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
        <div className="space-y-1">
          <Input
            list={`var-paths-${currentRoot}`}
            className="h-7 text-xs font-mono"
            placeholder="嵌套路径，如 0.name（可空=整变量）"
            value={pathDraft}
            disabled={disabled}
            onChange={(e) => setPathDraft(e.target.value.replace(/^\./, ''))}
            onBlur={() => emit(currentRoot, pathDraft)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                emit(currentRoot, pathDraft);
              }
            }}
          />
          <datalist id={`var-paths-${currentRoot}`}>
            {pathSuggestions.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
          {pathSuggestions.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              <button
                type="button"
                className="text-[10px] px-1.5 py-0.5 rounded-md border border-black/10 dark:border-white/10 opacity-70 hover:opacity-100"
                onClick={() => {
                  setPathDraft('');
                  emit(currentRoot, '');
                }}
              >
                整变量
              </button>
              {pathSuggestions.slice(0, 10).map((p) => (
                <button
                  type="button"
                  key={p}
                  className="text-[10px] font-mono px-1.5 py-0.5 rounded-md border border-black/10 dark:border-white/10 opacity-70 hover:opacity-100"
                  onClick={() => {
                    setPathDraft(p);
                    emit(currentRoot, p);
                  }}
                >
                  .{p}
                </button>
              ))}
            </div>
          ) : null}
          <p className="text-[10px] font-mono opacity-50 truncate">
            {formatVarRef(currentRoot, pathDraft)}
          </p>
        </div>
      ) : null}
    </div>
  );
}
