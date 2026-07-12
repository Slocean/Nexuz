/**
 * Dropdown of flow.variables — always synced from the Variables panel.
 * No free-text variable name entry.
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
import { formatVarRef, listFlowVariableNames, parseVarRef } from '../bindValue';

type Props = {
  /** Current value: `$name`, bare name, or empty */
  value: unknown;
  onChange: (varRef: string) => void;
  /** emit bare name instead of `$name` */
  bare?: boolean;
  placeholder?: string;
  className?: string;
  triggerClassName?: string;
  /** Exclude these bare names (e.g. already used in a keymap) */
  exclude?: string[];
  disabled?: boolean;
};

export default function VariableSelect({
  value,
  onChange,
  bare = false,
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

  const current =
    typeof value === 'string'
      ? parseVarRef(value) || String(value).replace(/^\$/, '').trim() || undefined
      : undefined;

  // Keep current selection visible even if temporarily excluded elsewhere
  const options = useMemo(() => {
    if (current && !names.includes(current) && listFlowVariableNames(variables).includes(current)) {
      return [current, ...names];
    }
    return names;
  }, [names, current, variables]);

  return (
    <Select
      value={current || undefined}
      disabled={disabled || options.length === 0}
      onValueChange={(v) => onChange(bare ? v : formatVarRef(v))}
    >
      <SelectTrigger className={triggerClassName || `h-8 flex-1 min-w-0 ${className || ''}`}>
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
              ${v}
            </SelectItem>
          ))
        )}
      </SelectContent>
    </Select>
  );
}
