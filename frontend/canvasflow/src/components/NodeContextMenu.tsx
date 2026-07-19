import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Ban,
  Check,
  CircleDot,
  Copy,
  Flag,
  Hash,
  Link2Off,
  Pause,
  Pencil,
  Play,
  ChevronDown,
  ChevronRight,
  PlayCircle,
  Trash2,
  Eraser,
  Ellipsis,
} from 'lucide-react';
import type { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';

export type NodeContextMenuMode = 'flat' | 'grouped';

export type NodeContextMenuState = {
  x: number;
  y: number;
  nodeId: string;
};

type Props = {
  open: NodeContextMenuState | null;
  onClose: () => void;
  menuMode?: NodeContextMenuMode;
  themeName: ThemeName;
  themeMode: ThemeMode;
  selectedIds: string[];
  collapsed: boolean;
  isEntry: boolean;
  hasBreakpoint: boolean;
  isDisabled: boolean;
  isExecuting: boolean;
  onRunSingle: () => void;
  onRunFrom: () => void;
  onRename: () => void;
  onSetCollapsed: () => void;
  onDuplicate: () => void;
  onCopyId: () => void;
  onSetEntry: () => void;
  onSetBreakpoint: () => void;
  onSetDisabled: () => void;
  onDisconnect: () => void;
  onDeleteDownstream: () => void;
  onDeleteOthers: () => void;
  onDelete: () => void;
};

type ItemProps = {
  label: string;
  icon: React.ReactNode;
  shortcut?: string;
  disabled?: boolean;
  danger?: boolean;
  checked?: boolean;
  submenu?: boolean;
  active?: boolean;
  onClick?: () => void;
  onMouseEnter?: () => void;
};

function MenuItem({
  label,
  icon,
  shortcut,
  disabled,
  danger,
  checked,
  submenu,
  active,
  onClick,
  onMouseEnter,
}: ItemProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-left outline-none transition-colors disabled:pointer-events-none disabled:opacity-40 ${
        danger
          ? 'text-rose-500 hover:bg-rose-500/10'
          : active
            ? 'bg-black/5 dark:bg-white/5'
            : 'hover:bg-black/5 dark:hover:bg-white/5'
      }`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (disabled) return;
        onClick?.();
      }}
      onMouseEnter={onMouseEnter}
    >
      <span className="w-4 h-4 shrink-0 flex items-center justify-center opacity-80">
        {icon}
      </span>
      <span className="flex-1 min-w-0 truncate">{label}</span>
      {checked ? <Check className="w-3.5 h-3.5 shrink-0 opacity-80" /> : null}
      {shortcut ? (
        <span className="ml-2 shrink-0 text-[10px] font-mono opacity-40">{shortcut}</span>
      ) : null}
      {submenu ? <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-50" /> : null}
    </button>
  );
}

function Separator() {
  return <div className="my-1 h-px bg-black/10 dark:bg-white/10" />;
}

type SubKey = 'more' | 'delete' | null;

/** Lightweight fixed-position node context menu (flat or grouped). */
export default function NodeContextMenu({
  open,
  onClose,
  menuMode = 'grouped',
  themeName,
  themeMode,
  selectedIds,
  collapsed,
  isEntry,
  hasBreakpoint,
  isDisabled,
  isExecuting,
  onRunSingle,
  onRunFrom,
  onRename,
  onSetCollapsed,
  onDuplicate,
  onCopyId,
  onSetEntry,
  onSetBreakpoint,
  onSetDisabled,
  onDisconnect,
  onDeleteDownstream,
  onDeleteOthers,
  onDelete,
}: Props) {
  const colors = getThemeColors(themeName, themeMode);
  const ref = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const deleteRef = useRef<HTMLDivElement>(null);
  const subRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [subKey, setSubKey] = useState<SubKey>(null);
  const [subPos, setSubPos] = useState({ x: 0, y: 0 });
  const multi = selectedIds.length > 1;
  const grouped = menuMode === 'grouped';

  useLayoutEffect(() => {
    if (!open) {
      setSubKey(null);
      return;
    }
    const el = ref.current;
    const w = el?.offsetWidth || 220;
    const h = el?.offsetHeight || 280;
    const pad = 8;
    let x = open.x;
    let y = open.y;
    if (x + w > window.innerWidth - pad) x = Math.max(pad, window.innerWidth - w - pad);
    if (y + h > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - h - pad);
    if (x < pad) x = pad;
    if (y < pad) y = pad;
    setPos({ x, y });
  }, [open, menuMode]);

  useLayoutEffect(() => {
    if (!open || !subKey) return;
    const anchor = subKey === 'more' ? moreRef.current : deleteRef.current;
    const sub = subRef.current;
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    const sw = sub?.offsetWidth || 180;
    const sh = sub?.offsetHeight || 160;
    const pad = 8;
    let x = r.right + 4;
    let y = r.top;
    if (x + sw > window.innerWidth - pad) x = Math.max(pad, r.left - sw - 4);
    if (y + sh > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - sh - pad);
    if (y < pad) y = pad;
    setSubPos({ x, y });
  }, [open, subKey]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        if (subKey) setSubKey(null);
        else onClose();
      }
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (ref.current?.contains(t) || subRef.current?.contains(t)) return;
      onClose();
    };
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('mousedown', onDown, true);
    window.addEventListener('contextmenu', onDown, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('mousedown', onDown, true);
      window.removeEventListener('contextmenu', onDown, true);
    };
  }, [open, onClose, subKey]);

  if (!open) return null;

  const run = (fn: () => void) => {
    fn();
    onClose();
  };

  const shellStyle: React.CSSProperties = {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    color: colors.text,
  };

  const runItems = (
    <>
      <MenuItem
        label="仅运行此节点"
        icon={isExecuting ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        disabled={multi || isExecuting}
        onClick={() => run(onRunSingle)}
        onMouseEnter={() => setSubKey(null)}
      />
      <MenuItem
        label="从此节点开始运行"
        icon={<PlayCircle className="w-3.5 h-3.5" />}
        disabled={multi || isExecuting}
        onClick={() => run(onRunFrom)}
        onMouseEnter={() => setSubKey(null)}
      />
    </>
  );

  const editPrimary = (
    <>
      <MenuItem
        label="重命名"
        icon={<Pencil className="w-3.5 h-3.5" />}
        disabled={multi}
        onClick={() => run(onRename)}
        onMouseEnter={() => setSubKey(null)}
      />
      <MenuItem
        label={multi ? `复制选中 ${selectedIds.length} 个节点` : '复制该节点'}
        icon={<Copy className="w-3.5 h-3.5" />}
        onClick={() => run(onDuplicate)}
        onMouseEnter={() => setSubKey(null)}
      />
      <MenuItem
        label={collapsed ? '展开' : '折叠'}
        icon={
          collapsed ? (
            <ChevronRight className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" />
          )
        }
        onClick={() => run(onSetCollapsed)}
        onMouseEnter={() => setSubKey(null)}
      />
    </>
  );

  const moreItems = (
    <>
      <MenuItem
        label="复制节点 ID"
        icon={<Hash className="w-3.5 h-3.5" />}
        disabled={multi}
        onClick={() => run(onCopyId)}
      />
      <MenuItem
        label="设为入口"
        icon={<Flag className="w-3.5 h-3.5" />}
        disabled={multi || isEntry}
        checked={isEntry}
        onClick={() => run(onSetEntry)}
      />
      <MenuItem
        label={hasBreakpoint ? '取消断点' : '设置断点'}
        icon={<CircleDot className="w-3.5 h-3.5" />}
        onClick={() => run(onSetBreakpoint)}
      />
      <MenuItem
        label={isDisabled ? '启用节点' : '禁用节点'}
        icon={<Ban className="w-3.5 h-3.5" />}
        checked={isDisabled}
        onClick={() => run(onSetDisabled)}
      />
      <MenuItem
        label="断开全部连线"
        icon={<Link2Off className="w-3.5 h-3.5" />}
        onClick={() => run(onDisconnect)}
      />
    </>
  );

  const deleteItems = (
    <>
      <MenuItem
        label={multi ? `删除 ${selectedIds.length} 个节点` : '删除'}
        icon={<Trash2 className="w-3.5 h-3.5" />}
        shortcut="Del"
        danger
        onClick={() => run(onDelete)}
      />
      <MenuItem
        label="删除后续节点"
        icon={<Eraser className="w-3.5 h-3.5" />}
        disabled={multi}
        danger
        onClick={() => run(onDeleteDownstream)}
      />
      <MenuItem
        label="删除其他节点"
        icon={<Eraser className="w-3.5 h-3.5" />}
        disabled={multi}
        danger
        onClick={() => run(onDeleteOthers)}
      />
    </>
  );

  const flatBody = (
    <>
      {runItems}
      <Separator />
      {editPrimary}
      <Separator />
      {moreItems}
      <Separator />
      {deleteItems}
    </>
  );

  const groupedBody = (
    <>
      {runItems}
      <Separator />
      {editPrimary}
      <Separator />
      <div ref={moreRef}>
        <MenuItem
          label="更多"
          icon={<Ellipsis className="w-3.5 h-3.5" />}
          submenu
          active={subKey === 'more'}
          onMouseEnter={() => setSubKey('more')}
          onClick={() => setSubKey((k) => (k === 'more' ? null : 'more'))}
        />
      </div>
      <Separator />
      <div ref={deleteRef}>
        <MenuItem
          label="删除"
          icon={<Trash2 className="w-3.5 h-3.5" />}
          submenu
          danger
          active={subKey === 'delete'}
          onMouseEnter={() => setSubKey('delete')}
          onClick={() => setSubKey((k) => (k === 'delete' ? null : 'delete'))}
        />
      </div>
    </>
  );

  return (
    <>
      <div
        ref={ref}
        className="fixed z-[300] min-w-[12.5rem] max-h-[min(90vh,32rem)] overflow-y-auto overflow-x-hidden rounded-xl border p-1.5 shadow-2xl backdrop-blur-xl"
        style={{ left: pos.x, top: pos.y, ...shellStyle }}
        onMouseDown={(e) => e.stopPropagation()}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        {grouped ? groupedBody : flatBody}
      </div>
      {grouped && subKey ? (
        <div
          ref={subRef}
          className="fixed z-[310] min-w-[11.5rem] overflow-hidden rounded-xl border p-1.5 shadow-2xl backdrop-blur-xl"
          style={{ left: subPos.x, top: subPos.y, ...shellStyle }}
          onMouseDown={(e) => e.stopPropagation()}
          onContextMenu={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onMouseLeave={() => setSubKey(null)}
        >
          {subKey === 'more' ? moreItems : deleteItems}
        </div>
      ) : null}
    </>
  );
}
