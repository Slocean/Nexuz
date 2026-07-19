import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Check,
  Copy,
  Flag,
  CircleDot,
  Pause,
  Play,
  Pencil,
  ChevronDown,
  ChevronRight,
  Trash2,
} from 'lucide-react';
import type { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';

export type NodeContextMenuState = {
  x: number;
  y: number;
  nodeId: string;
};

type Props = {
  open: NodeContextMenuState | null;
  onClose: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  /** Selected ids at menu open (includes context node). */
  selectedIds: string[];
  collapsed: boolean;
  isEntry: boolean;
  hasBreakpoint: boolean;
  isExecuting: boolean;
  onRunSingle: () => void;
  onRename: () => void;
  onToggleCollapse: () => void;
  onDuplicate: () => void;
  onSetEntry: () => void;
  onToggleBreakpoint: () => void;
  onDelete: () => void;
};

type ItemProps = {
  label: string;
  icon: React.ReactNode;
  shortcut?: string;
  disabled?: boolean;
  danger?: boolean;
  checked?: boolean;
  onClick: () => void;
};

function MenuItem({
  label,
  icon,
  shortcut,
  disabled,
  danger,
  checked,
  onClick,
}: ItemProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      className={`w-full flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm text-left outline-none transition-colors disabled:pointer-events-none disabled:opacity-40 ${
        danger
          ? 'text-rose-500 hover:bg-rose-500/10'
          : 'hover:bg-black/5 dark:hover:bg-white/5'
      }`}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (disabled) return;
        onClick();
      }}
    >
      <span className="w-4 h-4 shrink-0 flex items-center justify-center opacity-80">
        {icon}
      </span>
      <span className="flex-1 min-w-0 truncate">{label}</span>
      {checked ? <Check className="w-3.5 h-3.5 shrink-0 opacity-80" /> : null}
      {shortcut ? (
        <span className="ml-2 shrink-0 text-[10px] font-mono opacity-40">{shortcut}</span>
      ) : null}
    </button>
  );
}

function Separator() {
  return <div className="my-1 h-px bg-black/10 dark:bg-white/10" />;
}

/** Lightweight fixed-position node context menu (no new radix dependency). */
export default function NodeContextMenu({
  open,
  onClose,
  themeName,
  themeMode,
  selectedIds,
  collapsed,
  isEntry,
  hasBreakpoint,
  isExecuting,
  onRunSingle,
  onRename,
  onToggleCollapse,
  onDuplicate,
  onSetEntry,
  onToggleBreakpoint,
  onDelete,
}: Props) {
  const colors = getThemeColors(themeName, themeMode);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const multi = selectedIds.length > 1;

  useLayoutEffect(() => {
    if (!open) return;
    const el = ref.current;
    const w = el?.offsetWidth || 200;
    const h = el?.offsetHeight || 280;
    const pad = 8;
    let x = open.x;
    let y = open.y;
    if (x + w > window.innerWidth - pad) x = Math.max(pad, window.innerWidth - w - pad);
    if (y + h > window.innerHeight - pad) y = Math.max(pad, window.innerHeight - h - pad);
    if (x < pad) x = pad;
    if (y < pad) y = pad;
    setPos({ x, y });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    const onDown = (e: MouseEvent) => {
      if (!ref.current) return;
      if (ref.current.contains(e.target as Node)) return;
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
  }, [open, onClose]);

  if (!open) return null;

  const run = (fn: () => void) => {
    fn();
    onClose();
  };

  return (
    <div
      ref={ref}
      className="fixed z-[300] min-w-[11.5rem] overflow-hidden rounded-xl border p-1.5 shadow-2xl backdrop-blur-xl"
      style={{
        left: pos.x,
        top: pos.y,
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      <MenuItem
        label="仅运行此节点"
        icon={isExecuting ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
        disabled={multi || isExecuting}
        onClick={() => run(onRunSingle)}
      />
      <Separator />
      <MenuItem
        label="重命名"
        icon={<Pencil className="w-3.5 h-3.5" />}
        disabled={multi}
        onClick={() => run(onRename)}
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
        onClick={() => run(onToggleCollapse)}
      />
      <MenuItem
        label={multi ? `复制选中 ${selectedIds.length} 个节点` : '复制该节点'}
        icon={<Copy className="w-3.5 h-3.5" />}
        onClick={() => run(onDuplicate)}
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
        onClick={() => run(onToggleBreakpoint)}
      />
      <Separator />
      <MenuItem
        label={multi ? `删除 ${selectedIds.length} 个节点` : '删除'}
        icon={<Trash2 className="w-3.5 h-3.5" />}
        shortcut="Del"
        danger
        onClick={() => run(onDelete)}
      />
    </div>
  );
}
