import React, { useMemo, useState } from 'react';
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
import { formatNodeRef, formatVarRef } from '../bindValue';
import { inspectEmbeddedRefs } from '../bindValidate';

const OPS = [
  { value: '==', label: '等于' },
  { value: '!=', label: '不等于' },
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: 'contains', label: '包含' },
];

/**
 * Lightweight expression builder → writes expression string for evaluate_expression.
 */
export default function ExpressionField({
  value,
  onChange,
  currentNodeId,
  schemaMap,
}: {
  value: unknown;
  onChange: (v: string) => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
}) {
  const flowNodes = useFlowStore((s) => s.flow.nodes || {});
  const variables = useFlowStore((s) => s.flow.variables || {});
  const [leftNode, setLeftNode] = useState('');
  const [leftField, setLeftField] = useState('');
  const [op, setOp] = useState('contains');
  const [rightKind, setRightKind] = useState<'literal' | 'node' | 'variable'>('literal');
  const [rightLiteral, setRightLiteral] = useState('');
  const [rightNode, setRightNode] = useState('');
  const [rightField, setRightField] = useState('');
  const [rightVar, setRightVar] = useState('');

  const nodeOptions = useMemo(() => {
    return Object.entries(flowNodes)
      .filter(([id]) => id !== currentNodeId)
      .map(([id, node]: [string, any]) => {
        const schema = schemaMap[node?.type] || {};
        const outputs = Array.isArray(schema.outputs) ? schema.outputs : [];
        return {
          id,
          label: node?.name || schema.label || node?.type || id,
          outputs,
        };
      })
      .filter((n) => n.outputs.length > 0);
  }, [flowNodes, schemaMap, currentNodeId]);

  const varOptions = useMemo(() => {
    const keys = new Set<string>();
    for (const k of Object.keys(variables || {})) keys.add(String(k).replace(/^\$/, ''));
    return Array.from(keys).filter(Boolean).sort();
  }, [variables]);

  const leftFields = nodeOptions.find((n) => n.id === leftNode)?.outputs || [];
  const rightFields = nodeOptions.find((n) => n.id === rightNode)?.outputs || [];

  const exprIssues = useMemo(
    () =>
      inspectEmbeddedRefs(String(value ?? ''), currentNodeId, flowNodes, schemaMap, variables),
    [value, currentNodeId, flowNodes, schemaMap, variables],
  );

  const apply = () => {
    if (!leftNode || !leftField) return;
    const left = formatNodeRef(leftNode, leftField);
    let right = '';
    if (rightKind === 'literal') {
      const lit = rightLiteral;
      right = /^-?\d+(\.\d+)?$/.test(lit.trim()) ? lit.trim() : JSON.stringify(lit);
    } else if (rightKind === 'variable' && rightVar) {
      right = formatVarRef(rightVar);
    } else if (rightKind === 'node' && rightNode && rightField) {
      right = formatNodeRef(rightNode, rightField);
    } else {
      return;
    }
    onChange(`${left} ${op} ${right}`);
  };

  return (
    <div className="flex flex-col gap-1.5 w-full min-w-0">
      <Input
        className="h-8 font-mono text-xs"
        value={String(value ?? '')}
        placeholder='例如 {{ocr1.text}} contains "成功"'
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-1">
        <Select
          value={leftNode || undefined}
          onValueChange={(v) => {
            setLeftNode(v);
            const n = nodeOptions.find((x) => x.id === v);
            setLeftField(n?.outputs?.[0]?.name || '');
          }}
        >
          <SelectTrigger className="h-7 w-[6.5rem] text-xs">
            <SelectValue placeholder="左：节点" />
          </SelectTrigger>
          <SelectContent>
            {nodeOptions.map((n) => (
              <SelectItem key={n.id} value={n.id}>
                {n.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={leftField || undefined} onValueChange={setLeftField}>
          <SelectTrigger className="h-7 w-[5rem] text-xs">
            <SelectValue placeholder="字段" />
          </SelectTrigger>
          <SelectContent>
            {leftFields.map((f) => (
              <SelectItem key={f.name} value={f.name}>
                {f.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={op} onValueChange={setOp}>
          <SelectTrigger className="h-7 w-[5.5rem] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OPS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={rightKind} onValueChange={(v) => setRightKind(v as any)}>
          <SelectTrigger className="h-7 w-[4.5rem] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="literal">常量</SelectItem>
            <SelectItem value="node">上游</SelectItem>
            <SelectItem value="variable">变量</SelectItem>
          </SelectContent>
        </Select>
        {rightKind === 'literal' ? (
          <Input
            className="h-7 w-[6rem] text-xs"
            value={rightLiteral}
            placeholder="右值"
            onChange={(e) => setRightLiteral(e.target.value)}
          />
        ) : rightKind === 'variable' ? (
          <Select value={rightVar || undefined} onValueChange={setRightVar}>
            <SelectTrigger className="h-7 w-[6rem] text-xs">
              <SelectValue placeholder="$变量" />
            </SelectTrigger>
            <SelectContent>
              {varOptions.map((v) => (
                <SelectItem key={v} value={v}>
                  ${v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <>
            <Select
              value={rightNode || undefined}
              onValueChange={(v) => {
                setRightNode(v);
                const n = nodeOptions.find((x) => x.id === v);
                setRightField(n?.outputs?.[0]?.name || '');
              }}
            >
              <SelectTrigger className="h-7 w-[6rem] text-xs">
                <SelectValue placeholder="节点" />
              </SelectTrigger>
              <SelectContent>
                {nodeOptions.map((n) => (
                  <SelectItem key={n.id} value={n.id}>
                    {n.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={rightField || undefined} onValueChange={setRightField}>
              <SelectTrigger className="h-7 w-[5rem] text-xs">
                <SelectValue placeholder="字段" />
              </SelectTrigger>
              <SelectContent>
                {rightFields.map((f) => (
                  <SelectItem key={f.name} value={f.name}>
                    {f.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        )}
        <Button type="button" size="sm" className="h-7 px-2 text-xs" onClick={apply}>
          填入
        </Button>
      </div>
      {exprIssues.length > 0 && (
        <div className="space-y-0.5">
          {exprIssues.slice(0, 4).map((iss, i) => (
            <p key={i} className="text-[11px] text-rose-500 leading-snug">
              {iss.message}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
