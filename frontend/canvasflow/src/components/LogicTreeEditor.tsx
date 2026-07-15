/**
 * Nested boolean condition tree editor for if_logic.
 * Supports AND/OR groups, NOT, nesting — like writing boolean code.
 */
import React, { useCallback, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, FolderPlus, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import ExpressionField from './ExpressionField';

export type LogicExpr = {
  kind: 'expr';
  id: string;
  expression: string;
  not?: boolean;
  label?: string;
};

export type LogicGroup = {
  kind: 'group';
  id: string;
  op: 'and' | 'or';
  not?: boolean;
  children: LogicNode[];
};

export type LogicNode = LogicExpr | LogicGroup;

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
}

export function emptyLogicTree(): LogicGroup {
  return {
    kind: 'group',
    id: 'root',
    op: 'and',
    not: false,
    children: [{ kind: 'expr', id: uid('c'), expression: '', not: false, label: '' }],
  };
}

/** Migrate legacy conditions[] / logic payload into a group tree. */
export function normalizeLogicValue(value: unknown, legacyMode?: string): LogicGroup {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const v = value as any;
    const kind = v.kind || v.type;
    if (kind === 'group') {
      return {
        kind: 'group',
        id: String(v.id || 'root'),
        op: v.op === 'or' ? 'or' : 'and',
        not: !!v.not,
        children: Array.isArray(v.children) && v.children.length
          ? v.children.map((c: any, i: number) => normalizeChild(c, i))
          : emptyLogicTree().children,
      };
    }
    if (kind === 'expr' || kind === 'leaf') {
      return {
        kind: 'group',
        id: 'root',
        op: 'and',
        not: false,
        children: [normalizeChild(v, 0)],
      };
    }
  }
  if (Array.isArray(value)) {
    const op = legacyMode === 'or' ? 'or' : 'and';
    return {
      kind: 'group',
      id: 'root',
      op,
      not: false,
      children: value.length
        ? value.map((c, i) => normalizeChild(c, i))
        : emptyLogicTree().children,
    };
  }
  return emptyLogicTree();
}

function normalizeChild(c: any, i: number): LogicNode {
  if (typeof c === 'string') {
    return { kind: 'expr', id: uid('c'), expression: c, not: false, label: '' };
  }
  if (c && typeof c === 'object') {
    const kind = c.kind || c.type;
    if (kind === 'group') {
      return {
        kind: 'group',
        id: String(c.id || uid('g')),
        op: c.op === 'or' ? 'or' : 'and',
        not: !!c.not,
        children: Array.isArray(c.children) && c.children.length
          ? c.children.map((ch: any, j: number) => normalizeChild(ch, j))
          : [{ kind: 'expr', id: uid('c'), expression: '', not: false, label: '' }],
      };
    }
    return {
      kind: 'expr',
      id: String(c.id || uid('c')),
      expression: String(c.expression || ''),
      not: !!c.not,
      label: String(c.label || ''),
    };
  }
  return { kind: 'expr', id: uid('c'), expression: '', not: false, label: `条件 ${i + 1}` };
}

function summarizeNode(node: LogicNode): string {
  if (node.kind === 'expr') {
    const e = (node.expression || '').trim();
    const base = e || '（空条件）';
    return node.not ? `NOT ${base}` : base;
  }
  const n = node.children?.length || 0;
  const join = node.op === 'or' ? 'OR' : 'AND';
  const base = `组(${join}) · ${n} 项`;
  return node.not ? `NOT ${base}` : base;
}

function updateAt(root: LogicGroup, path: number[], updater: (n: LogicNode) => LogicNode): LogicGroup {
  if (path.length === 0) {
    const next = updater(root);
    return next.kind === 'group' ? next : root;
  }
  const walk = (node: LogicGroup, idxPath: number[]): LogicGroup => {
    const [head, ...rest] = idxPath;
    const children = node.children.map((ch, i) => {
      if (i !== head) return ch;
      if (rest.length === 0) return updater(ch);
      if (ch.kind !== 'group') return ch;
      return walk(ch, rest);
    });
    return { ...node, children };
  };
  return walk(root, path);
}

function removeAt(root: LogicGroup, path: number[]): LogicGroup {
  if (path.length === 0) return root;
  const parentPath = path.slice(0, -1);
  const index = path[path.length - 1];
  return updateAt(root, parentPath, (n) => {
    if (n.kind !== 'group') return n;
    const children = n.children.filter((_, i) => i !== index);
    if (!children.length) {
      children.push({ kind: 'expr', id: uid('c'), expression: '', not: false, label: '' });
    }
    return { ...n, children };
  });
}

function insertChild(root: LogicGroup, path: number[], child: LogicNode): LogicGroup {
  return updateAt(root, path, (n) => {
    if (n.kind !== 'group') return n;
    return { ...n, children: [...n.children, child] };
  });
}

type Props = {
  value: unknown;
  legacyMode?: string;
  onChange: (next: LogicGroup) => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
};

export default function LogicTreeEditor({
  value,
  legacyMode,
  onChange,
  currentNodeId,
  schemaMap,
}: Props) {
  const tree = useMemo(() => normalizeLogicValue(value, legacyMode), [value, legacyMode]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const setTree = useCallback(
    (next: LogicGroup) => {
      onChange(next);
    },
    [onChange],
  );

  const toggleCollapse = (id: string) => {
    setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const isCollapsed = (id: string, depth: number) => {
    if (collapsed[id] != null) return collapsed[id];
    // Default: nested groups start collapsed for less noise; root stays open.
    return depth > 0 && false;
  };

  return (
    <div className="space-y-2 w-full min-w-0">
      <p className="text-[11px] leading-relaxed opacity-60">
        用「组」嵌套自由组合：例如 (A 且 B) 或 (C 且 D)。每项可取反（NOT）。
      </p>
      <GroupBlock
        group={tree}
        path={[]}
        depth={0}
        isRoot
        isCollapsed={isCollapsed}
        toggleCollapse={toggleCollapse}
        currentNodeId={currentNodeId}
        schemaMap={schemaMap}
        onPatch={(path, updater) => setTree(updateAt(tree, path, updater))}
        onRemove={(path) => setTree(removeAt(tree, path))}
        onAddExpr={(path) =>
          setTree(
            insertChild(tree, path, {
              kind: 'expr',
              id: uid('c'),
              expression: '',
              not: false,
              label: '',
            }),
          )
        }
        onAddGroup={(path) =>
          setTree(
            insertChild(tree, path, {
              kind: 'group',
              id: uid('g'),
              op: 'and',
              not: false,
              children: [{ kind: 'expr', id: uid('c'), expression: '', not: false, label: '' }],
            }),
          )
        }
      />
    </div>
  );
}

function GroupBlock({
  group,
  path,
  depth,
  isRoot,
  isCollapsed,
  toggleCollapse,
  currentNodeId,
  schemaMap,
  onPatch,
  onRemove,
  onAddExpr,
  onAddGroup,
}: {
  group: LogicGroup;
  path: number[];
  depth: number;
  isRoot?: boolean;
  isCollapsed: (id: string, depth: number) => boolean;
  toggleCollapse: (id: string) => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
  onPatch: (path: number[], updater: (n: LogicNode) => LogicNode) => void;
  onRemove: (path: number[]) => void;
  onAddExpr: (path: number[]) => void;
  onAddGroup: (path: number[]) => void;
}) {
  const closed = !isRoot && isCollapsed(group.id, depth);

  return (
    <div
      className={`rounded-lg border w-full min-w-0 ${
        depth === 0
          ? 'border-black/10 dark:border-white/10'
          : 'border-blue-500/25 bg-blue-500/[0.04]'
      }`}
    >
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-black/5 dark:border-white/5">
        {!isRoot && (
          <button
            type="button"
            className="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-black/5 dark:hover:bg-white/10 shrink-0"
            onClick={() => toggleCollapse(group.id)}
            title={closed ? '展开' : '折叠'}
          >
            {closed ? (
              <ChevronRight className="w-3.5 h-3.5 opacity-70" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 opacity-70" />
            )}
          </button>
        )}
        <span className="text-[11px] font-medium opacity-70 shrink-0">
          {isRoot ? '根组' : '条件组'}
        </span>
        <Select
          value={group.op}
          onValueChange={(v) =>
            onPatch(path, (n) =>
              n.kind === 'group' ? { ...n, op: v === 'or' ? 'or' : 'and' } : n,
            )
          }
        >
          <SelectTrigger className="h-7 w-[11rem] text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="and">全部 AND</SelectItem>
            <SelectItem value="or">任一 OR</SelectItem>
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant={group.not ? 'default' : 'outline'}
          size="sm"
          className="h-7 px-2 text-[11px]"
          onClick={() =>
            onPatch(path, (n) => (n.kind === 'group' ? { ...n, not: !n.not } : n))
          }
          title="对整组取反"
        >
          NOT
        </Button>
        {closed && (
          <span className="text-[11px] opacity-50 truncate flex-1 min-w-0 font-mono">
            {summarizeNode(group)}
          </span>
        )}
        <div className="flex-1" />
        {!isRoot && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-rose-400 shrink-0"
            onClick={() => onRemove(path)}
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        )}
      </div>

      {!closed && (
        <div className="p-2 space-y-2">
          {group.children.map((child, idx) => {
            const childPath = [...path, idx];
            if (child.kind === 'group') {
              return (
                <GroupBlock
                  key={child.id}
                  group={child}
                  path={childPath}
                  depth={depth + 1}
                  isCollapsed={isCollapsed}
                  toggleCollapse={toggleCollapse}
                  currentNodeId={currentNodeId}
                  schemaMap={schemaMap}
                  onPatch={onPatch}
                  onRemove={onRemove}
                  onAddExpr={onAddExpr}
                  onAddGroup={onAddGroup}
                />
              );
            }
            return (
              <ExprBlock
                key={child.id}
                node={child}
                path={childPath}
                index={idx}
                collapsed={isCollapsed(child.id, depth + 1)}
                onToggle={() => toggleCollapse(child.id)}
                currentNodeId={currentNodeId}
                schemaMap={schemaMap}
                onPatch={onPatch}
                onRemove={onRemove}
                canRemove={group.children.length > 1 || !isRoot}
              />
            );
          })}
          <div className="flex gap-1.5 pt-0.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 flex-1 text-xs"
              onClick={() => onAddExpr(path)}
            >
              <Plus className="w-3.5 h-3.5" />
              添加条件
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 flex-1 text-xs"
              onClick={() => onAddGroup(path)}
            >
              <FolderPlus className="w-3.5 h-3.5" />
              添加分组
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ExprBlock({
  node,
  path,
  index,
  collapsed,
  onToggle,
  currentNodeId,
  schemaMap,
  onPatch,
  onRemove,
  canRemove,
}: {
  node: LogicExpr;
  path: number[];
  index: number;
  collapsed: boolean;
  onToggle: () => void;
  currentNodeId: string;
  schemaMap: Record<string, any>;
  onPatch: (path: number[], updater: (n: LogicNode) => LogicNode) => void;
  onRemove: (path: number[]) => void;
  canRemove: boolean;
}) {
  const title = node.label?.trim() || `条件 ${index + 1}`;

  return (
    <div className="rounded-lg border border-black/10 dark:border-white/10 w-full min-w-0">
      <div className="flex items-center gap-1 px-2 py-1.5">
        <button
          type="button"
          className="h-6 w-6 inline-flex items-center justify-center rounded hover:bg-black/5 dark:hover:bg-white/10 shrink-0"
          onClick={onToggle}
          title={collapsed ? '展开' : '折叠'}
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5 opacity-70" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 opacity-70" />
          )}
        </button>
        <Input
          className="h-7 text-xs flex-1 min-w-0"
          value={node.label || ''}
          placeholder={title}
          onChange={(e) =>
            onPatch(path, (n) =>
              n.kind === 'expr' ? { ...n, label: e.target.value } : n,
            )
          }
        />
        <Button
          type="button"
          variant={node.not ? 'default' : 'outline'}
          size="sm"
          className="h-7 px-2 text-[11px] shrink-0"
          onClick={() =>
            onPatch(path, (n) => (n.kind === 'expr' ? { ...n, not: !n.not } : n))
          }
        >
          NOT
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-rose-400 shrink-0"
          disabled={!canRemove}
          onClick={() => onRemove(path)}
        >
          <X className="w-3.5 h-3.5" />
        </Button>
      </div>
      {collapsed ? (
        <p className="px-2 pb-2 text-[11px] font-mono opacity-50 truncate">
          {summarizeNode(node)}
        </p>
      ) : (
        <div className="px-2 pb-2">
          <ExpressionField
            value={node.expression}
            onChange={(v) =>
              onPatch(path, (n) => (n.kind === 'expr' ? { ...n, expression: v } : n))
            }
            currentNodeId={currentNodeId}
            schemaMap={schemaMap}
          />
        </div>
      )}
    </div>
  );
}
