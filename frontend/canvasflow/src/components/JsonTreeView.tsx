import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { bridge } from '@/bridge';

type Props = {
  data: unknown;
  className?: string;
  style?: React.CSSProperties;
  /** Called after a successful clipboard write (selection or value click). */
  onCopied?: () => void;
};

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function previewOf(value: unknown): string {
  if (value === null) return 'null';
  if (value === undefined) return 'undefined';
  if (typeof value === 'string') {
    const s = value.length > 40 ? `${value.slice(0, 40)}…` : value;
    return `"${s}"`;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return `[${value.length}]`;
  if (isPlainObject(value)) {
    const n = Object.keys(value).length;
    return `{${n}}`;
  }
  return String(value);
}

async function writeClipboard(text: string): Promise<boolean> {
  const raw = String(text ?? '');
  if (!raw) return false;
  try {
    const res = await bridge.clipboardWrite?.(raw);
    if (res?.ok) return true;
  } catch {
    /* fall through */
  }
  try {
    await navigator.clipboard.writeText(raw);
    return true;
  } catch {
    try {
      const ta = document.createElement('textarea');
      ta.value = raw;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

function ValueText({ value }: { value: unknown }) {
  if (value === null) return <span className="text-slate-400">null</span>;
  if (value === undefined) return <span className="text-slate-400">undefined</span>;
  if (typeof value === 'string') {
    return (
      <span className="text-amber-600 dark:text-amber-400 break-all">
        &quot;{value}&quot;
      </span>
    );
  }
  if (typeof value === 'number') {
    return <span className="text-sky-600 dark:text-sky-400">{String(value)}</span>;
  }
  if (typeof value === 'boolean') {
    return <span className="text-violet-600 dark:text-violet-400">{String(value)}</span>;
  }
  return <span className="break-all">{String(value)}</span>;
}

function TreeNode({
  name,
  value,
  depth,
  defaultOpen,
}: {
  name?: string;
  value: unknown;
  depth: number;
  defaultOpen: boolean;
}) {
  const isArr = Array.isArray(value);
  const isObj = isPlainObject(value);
  const expandable = isArr || isObj;
  const [open, setOpen] = useState(defaultOpen);

  const entries = useMemo(() => {
    if (isArr) return (value as unknown[]).map((v, i) => [String(i), v] as const);
    if (isObj) return Object.entries(value as Record<string, unknown>);
    return [] as Array<readonly [string, unknown]>;
  }, [isArr, isObj, value]);

  if (!expandable) {
    return (
      <div className="flex items-start gap-1 leading-5 py-[1px] min-w-0">
        <span className="w-3.5 shrink-0" />
        {name != null ? (
          <>
            <span className="text-fuchsia-700 dark:text-fuchsia-300 shrink-0">{name}</span>
            <span className="opacity-40 shrink-0">: </span>
          </>
        ) : null}
        <ValueText value={value} />
      </div>
    );
  }

  const label = isArr ? `Array(${(value as unknown[]).length})` : 'Object';

  return (
    <div className="min-w-0">
      <div className="flex items-start gap-0.5 leading-5 py-[1px] min-w-0">
        <button
          type="button"
          className="w-3.5 h-5 flex items-center justify-center shrink-0 opacity-60 hover:opacity-100 rounded"
          onClick={() => setOpen(v => !v)}
          aria-expanded={open}
          title={open ? '折叠' : '展开'}
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
        {name != null ? (
          <>
            <span className="text-fuchsia-700 dark:text-fuchsia-300 shrink-0">{name}</span>
            <span className="opacity-40 shrink-0">: </span>
          </>
        ) : null}
        <span
          className="opacity-50 shrink-0 cursor-pointer hover:opacity-80"
          onClick={() => setOpen(v => !v)}
        >
          {label}
        </span>
        {!open ? (
          <span className="opacity-40 ml-1 truncate min-w-0">{previewOf(value)}</span>
        ) : null}
      </div>
      {open ? (
        <div className="ml-3 border-l border-black/10 dark:border-white/10 pl-2 min-w-0">
          {entries.length === 0 ? (
            <div className="opacity-40 leading-5 py-[1px]">{isArr ? '(empty)' : '{}'}</div>
          ) : (
            entries.map(([k, v]) => (
              <TreeNode
                key={k}
                name={k}
                value={v}
                depth={depth + 1}
                defaultOpen={depth + 1 < 2}
              />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

/**
 * DevTools-style JSON tree: expand/collapse + selectable text.
 * Ctrl/Cmd+C uses the native bridge so copy works inside pywebview.
 */
export default function JsonTreeView({ data, className = '', style, onCopied }: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  const selectionInside = useCallback(() => {
    const root = rootRef.current;
    if (!root) return false;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return false;
    try {
      const node = sel.getRangeAt(0).commonAncestorContainer;
      return root.contains(node.nodeType === 1 ? node : node.parentNode);
    } catch {
      return false;
    }
  }, []);

  const copySelectionOrAll = useCallback(async () => {
    const sel = window.getSelection()?.toString() ?? '';
    const text =
      sel.trim() ||
      (typeof data === 'string' ? data : JSON.stringify(data, null, 2));
    const ok = await writeClipboard(text);
    if (ok) onCopied?.();
    return ok;
  }, [data, onCopied]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || String(e.key).toLowerCase() !== 'c') return;
      if (!selectionInside() && document.activeElement !== rootRef.current) return;
      e.preventDefault();
      e.stopPropagation();
      void copySelectionOrAll();
    };
    const onCopy = (e: ClipboardEvent) => {
      if (!selectionInside()) return;
      const sel = window.getSelection()?.toString() ?? '';
      if (!sel) return;
      e.preventDefault();
      e.stopPropagation();
      void writeClipboard(sel).then(ok => {
        if (ok) onCopied?.();
      });
    };
    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('copy', onCopy, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      document.removeEventListener('copy', onCopy, true);
    };
  }, [copySelectionOrAll, onCopied, selectionInside]);

  return (
    <div
      ref={rootRef}
      role="tree"
      tabIndex={0}
      title="点击箭头折叠/展开；选中后 Ctrl+C 复制"
      style={{
        userSelect: 'text',
        WebkitUserSelect: 'text',
        ...style,
      }}
      className={`font-mono text-xs outline-none focus-visible:ring-1 focus-visible:ring-sky-500/40 rounded-xl ${className}`}
    >
      <TreeNode value={data} depth={0} defaultOpen />
    </div>
  );
}
