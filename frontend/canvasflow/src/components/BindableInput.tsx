import React, { useMemo } from 'react';
import { Link2, Hash } from 'lucide-react';
import { useFlowStore } from '@/store/flowModelStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  BindKind,
  coerceLiteral,
  detectBindKind,
  formatNodeRef,
  formatVarRef,
  isRefValue,
  literalToDisplay,
  parseNodeRef,
  parseVarRef,
} from '../bindValue';
import { inspectBindValue } from '../bindValidate';

type SchemaMap = Record<string, { label?: string; outputs?: { name: string; type?: string }[] }>;

interface BindableInputProps {
  value: unknown;
  inputType?: string; // number | string | color
  placeholder?: string;
  currentNodeId: string;
  schemaMap: SchemaMap;
  onChange: (value: string | number) => void;
  /** Extra trailing controls (e.g. 取点) */
  trailing?: React.ReactNode;
  className?: string;
}

export default function BindableInput({
  value,
  inputType = 'string',
  placeholder,
  currentNodeId,
  schemaMap,
  onChange,
  trailing,
  className,
}: BindableInputProps) {
  const flowNodes = useFlowStore((s) => s.flow.nodes || {});
  const variables = useFlowStore((s) => s.flow.variables || {});

  const kind = detectBindKind(value);
  const nodeRef = kind === 'node' && typeof value === 'string' ? parseNodeRef(value) : null;
  const varName = kind === 'variable' && typeof value === 'string' ? parseVarRef(value) : null;

  const status = useMemo(
    () =>
      inspectBindValue(value, inputType, currentNodeId, flowNodes, schemaMap, variables),
    [value, inputType, currentNodeId, flowNodes, schemaMap, variables],
  );

  const nodeOptions = useMemo(() => {
    return Object.entries(flowNodes)
      .filter(([id]) => id !== currentNodeId)
      .map(([id, node]: [string, any]) => {
        const schema = schemaMap[node?.type] || {};
        const outputs = Array.isArray(schema.outputs) ? schema.outputs : [];
        const label = node?.name || schema.label || node?.type || id;
        return { id, label, type: node?.type, outputs };
      })
      .filter((n) => n.outputs.length > 0);
  }, [flowNodes, schemaMap, currentNodeId]);

  const varOptions = useMemo(() => {
    const keys = new Set<string>();
    for (const k of Object.keys(variables || {})) {
      keys.add(String(k).replace(/^\$/, ''));
    }
    return Array.from(keys).filter(Boolean).sort();
  }, [variables]);

  const selectedNode = nodeOptions.find((n) => n.id === nodeRef?.nodeId);
  const fields = selectedNode?.outputs || [];

  const setKind = (next: BindKind) => {
    if (next === 'literal') {
      onChange(inputType === 'number' ? 0 : '');
      return;
    }
    if (next === 'variable') {
      const first = varOptions[0];
      onChange(first ? formatVarRef(first) : '$');
      return;
    }
    // node
    const first = nodeOptions[0];
    const field = first?.outputs?.[0]?.name;
    if (first && field) onChange(formatNodeRef(first.id, field));
    else onChange('{{node.field}}');
  };

  return (
    <div className={`flex flex-col gap-0.5 min-w-0 flex-1 ${className || ''}`}>
      <div
        className={`flex items-center gap-1 min-w-0 ${
          status.broken
            ? 'rounded-md ring-1 ring-rose-500/60'
            : status.typeWarn
              ? 'rounded-md ring-1 ring-amber-500/50'
              : ''
        }`}
        title={status.message || undefined}
      >
      <Select value={kind} onValueChange={(v) => setKind(v as BindKind)}>
        <SelectTrigger className="h-8 w-[4.5rem] shrink-0 px-1.5 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="literal">常量</SelectItem>
          <SelectItem value="node">上游</SelectItem>
          <SelectItem value="variable">变量</SelectItem>
        </SelectContent>
      </Select>

      {kind === 'literal' ? (
        <Input
          type="text"
          inputMode={inputType === 'number' ? 'decimal' : undefined}
          className="h-8 flex-1 min-w-0"
          value={literalToDisplay(value, inputType)}
          placeholder={placeholder || (inputType === 'number' ? '数值' : '文本')}
          onChange={(e) => onChange(coerceLiteral(e.target.value, inputType))}
        />
      ) : kind === 'variable' ? (
        <Select
          value={varName || undefined}
          onValueChange={(v) => onChange(formatVarRef(v))}
        >
          <SelectTrigger className="h-8 flex-1 min-w-0">
            <SelectValue placeholder={varOptions.length ? '选择变量' : '暂无变量'} />
          </SelectTrigger>
          <SelectContent>
            {varOptions.length === 0 ? (
              <SelectItem value="__none" disabled>
                请先在「变量」页添加
              </SelectItem>
            ) : (
              varOptions.map((v) => (
                <SelectItem key={v} value={v}>
                  ${v}
                </SelectItem>
              ))
            )}
          </SelectContent>
        </Select>
      ) : (
        <>
          <Select
            value={nodeRef?.nodeId || undefined}
            onValueChange={(nid) => {
              const n = nodeOptions.find((x) => x.id === nid);
              const field = n?.outputs?.[0]?.name || 'value';
              onChange(formatNodeRef(nid, field));
            }}
          >
            <SelectTrigger className="h-8 flex-1 min-w-0 max-w-[7rem]">
              <SelectValue placeholder={nodeOptions.length ? '节点' : '无上游输出'} />
            </SelectTrigger>
            <SelectContent>
              {nodeOptions.length === 0 ? (
                <SelectItem value="__none" disabled>
                  无带输出的节点
                </SelectItem>
              ) : (
                nodeOptions.map((n) => (
                  <SelectItem key={n.id} value={n.id}>
                    {n.label}
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
          <Select
            value={nodeRef?.field || undefined}
            onValueChange={(field) => {
              const nid = nodeRef?.nodeId || nodeOptions[0]?.id;
              if (!nid) return;
              onChange(formatNodeRef(nid, field));
            }}
          >
            <SelectTrigger className="h-8 w-[5.5rem] shrink-0">
              <SelectValue placeholder="字段" />
            </SelectTrigger>
            <SelectContent>
              {fields.length === 0 ? (
                <SelectItem value="__none" disabled>
                  —
                </SelectItem>
              ) : (
                fields.map((f) => (
                  <SelectItem key={f.name} value={f.name}>
                    {f.name}
                  </SelectItem>
                ))
              )}
            </SelectContent>
          </Select>
        </>
      )}

      {kind !== 'literal' && (
        <span
          className="hidden xl:inline text-[10px] font-mono opacity-50 truncate max-w-[4.5rem]"
          title={typeof value === 'string' ? value : ''}
        >
          {typeof value === 'string' && isRefValue(value) ? value : ''}
        </span>
      )}

      {trailing}
      </div>
      {status.message && (status.broken || status.typeWarn) && (
        <p
          className={`text-[11px] leading-tight pl-0.5 ${
            status.broken ? 'text-rose-500' : 'text-amber-600 dark:text-amber-400'
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  );
}

/** Compact chip showing a copyable output ref */
export function OutputRefChip({
  nodeId,
  field,
  value,
  onCopied,
}: {
  nodeId: string;
  field: string;
  value?: unknown;
  onCopied?: () => void;
}) {
  const ref = formatNodeRef(nodeId, field);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(ref);
      onCopied?.();
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={`点击复制 ${ref}`}
      className="flex items-center gap-1.5 w-full text-left rounded-lg px-2 py-1.5 hover:bg-black/5 dark:hover:bg-white/5 transition-colors group"
    >
      <Hash className="w-3 h-3 opacity-40 shrink-0" />
      <span className="font-mono text-xs font-medium shrink-0">{field}</span>
      <span className="font-mono text-xs opacity-50 truncate flex-1 min-w-0">
        {value === undefined ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}
      </span>
      <Link2 className="w-3 h-3 opacity-0 group-hover:opacity-60 shrink-0" />
    </button>
  );
}
