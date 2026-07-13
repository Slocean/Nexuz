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
import { formatNodeRef, formatVarRef, listFlowVariableNames } from '../bindValue';
import { inspectEmbeddedRefs } from '../bindValidate';
import VariableSelect from './VariableSelect';

const OPS = [
  { value: '==', label: '等于' },
  { value: '!=', label: '不等于' },
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: 'contains', label: '包含' },
];

function Labeled({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 min-w-0 w-full">
      <span className="text-[11px] font-medium opacity-60 shrink-0 w-[4.5rem] leading-8">
        {title}
      </span>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

/**
 * Lightweight expression builder → writes expression string for evaluate_expression.
 * Quick-fill card: each row is title + control on one line.
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

  const varOptions = useMemo(() => listFlowVariableNames(variables), [variables]);

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
    <div className="flex flex-col gap-2 w-full min-w-0">
      <Input
        className="h-8 font-mono text-xs w-full"
        value={String(value ?? '')}
        placeholder='例如 {{ocr1.text}} contains "成功"'
        onChange={(e) => onChange(e.target.value)}
      />

      <div className="rounded-lg border border-black/10 dark:border-white/10 p-2 space-y-2.5">
        <p className="text-[11px] opacity-50 leading-none">快速填入</p>

        <Labeled title="左值节点">
          <Select
            value={leftNode || undefined}
            onValueChange={(v) => {
              setLeftNode(v);
              const n = nodeOptions.find((x) => x.id === v);
              setLeftField(n?.outputs?.[0]?.name || '');
            }}
          >
            <SelectTrigger className="h-8 w-full text-xs">
              <SelectValue placeholder="选择节点" />
            </SelectTrigger>
            <SelectContent>
              {nodeOptions.map((n) => (
                <SelectItem key={n.id} value={n.id}>
                  {n.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Labeled>

        <Labeled title="左值字段">
          <Select value={leftField || undefined} onValueChange={setLeftField}>
            <SelectTrigger className="h-8 w-full text-xs">
              <SelectValue placeholder="选择字段" />
            </SelectTrigger>
            <SelectContent>
              {leftFields.map((f) => (
                <SelectItem key={f.name} value={f.name}>
                  {f.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Labeled>

        <Labeled title="比较方式">
          <Select value={op} onValueChange={setOp}>
            <SelectTrigger className="h-8 w-full text-xs">
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
        </Labeled>

        <Labeled title="右值类型">
          <Select
            value={rightKind}
            onValueChange={(v) => {
              const next = v as 'literal' | 'node' | 'variable';
              setRightKind(next);
              if (next === 'variable' && !rightVar && varOptions[0]) {
                setRightVar(varOptions[0]);
              }
            }}
          >
            <SelectTrigger className="h-8 w-full text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="literal">常量</SelectItem>
              <SelectItem value="node">上游</SelectItem>
              <SelectItem value="variable" disabled={varOptions.length === 0}>
                变量{varOptions.length === 0 ? '（未创建）' : ''}
              </SelectItem>
            </SelectContent>
          </Select>
        </Labeled>

        {rightKind === 'literal' ? (
          <Labeled title="右值">
            <Input
              className="h-8 w-full text-xs"
              value={rightLiteral}
              placeholder="输入常量"
              onChange={(e) => setRightLiteral(e.target.value)}
            />
          </Labeled>
        ) : rightKind === 'variable' ? (
          <Labeled title="右值变量">
            <VariableSelect
              value={rightVar ? `$${rightVar}` : ''}
              bare
              onChange={(name) => setRightVar(name)}
              placeholder="$变量"
              triggerClassName="h-8 w-full text-xs"
            />
          </Labeled>
        ) : (
          <>
            <Labeled title="右值节点">
              <Select
                value={rightNode || undefined}
                onValueChange={(v) => {
                  setRightNode(v);
                  const n = nodeOptions.find((x) => x.id === v);
                  setRightField(n?.outputs?.[0]?.name || '');
                }}
              >
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue placeholder="选择节点" />
                </SelectTrigger>
                <SelectContent>
                  {nodeOptions.map((n) => (
                    <SelectItem key={n.id} value={n.id}>
                      {n.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Labeled>
            <Labeled title="右值字段">
              <Select value={rightField || undefined} onValueChange={setRightField}>
                <SelectTrigger className="h-8 w-full text-xs">
                  <SelectValue placeholder="选择字段" />
                </SelectTrigger>
                <SelectContent>
                  {rightFields.map((f) => (
                    <SelectItem key={f.name} value={f.name}>
                      {f.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Labeled>
          </>
        )}

        <Button type="button" size="sm" className="h-8 w-full text-xs" onClick={apply}>
          填入表达式
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
