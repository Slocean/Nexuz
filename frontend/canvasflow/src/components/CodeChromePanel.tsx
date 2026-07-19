import React from 'react';
import { Terminal } from 'lucide-react';

export type CodeChromePanelProps = {
  /** Header title, e.g. run.log / output.json */
  title?: string;
  /** Optional icon before title (defaults to Terminal). */
  icon?: React.ReactNode;
  /** Right-side meta in header, e.g. "12 lines". */
  meta?: React.ReactNode;
  /** Extra controls on the right of the header (before meta). */
  headerRight?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  bodyStyle?: React.CSSProperties;
  bodyRef?: React.Ref<HTMLDivElement>;
  /** Grow to fill parent flex column. */
  fill?: boolean;
  /**
   * Reserved height for the scrollable body (ignored when fill).
   * Applied as both height and maxHeight so the panel keeps its size
   * even when content is short.
   */
  maxHeight?: number | string;
  /** Empty-state hint when children is null/empty and emptyText is set. */
  emptyText?: string;
};

/**
 * Shared “code window” chrome: traffic-light title bar + dark body.
 * Outer frame matches Run Monitor logs; put JsonTreeView / log lines inside.
 */
export default function CodeChromePanel({
  title = 'code',
  icon,
  meta,
  headerRight,
  children,
  className = '',
  bodyClassName = '',
  bodyStyle,
  bodyRef,
  fill = false,
  maxHeight = 256,
  emptyText,
}: CodeChromePanelProps) {
  const hasChildren = children != null && children !== false;
  return (
    <div
      className={`flex flex-col overflow-hidden rounded-lg border min-w-0 w-full ${
        fill ? 'flex-1 min-h-0 h-full' : ''
      } ${className}`}
      style={{
        background: '#0d1117',
        borderColor: 'rgba(255,255,255,0.1)',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.04)',
      }}
    >
      <div
        className="shrink-0 flex items-center gap-2 px-2.5 py-1.5 border-b"
        style={{
          background: '#161b22',
          borderColor: 'rgba(255,255,255,0.08)',
        }}
      >
        <span className="inline-flex gap-1 shrink-0">
          <span className="w-2 h-2 rounded-full bg-[#ff5f56]" />
          <span className="w-2 h-2 rounded-full bg-[#ffbd2e]" />
          <span className="w-2 h-2 rounded-full bg-[#27c93f]" />
        </span>
        <span className="text-slate-400 shrink-0">
          {icon ?? <Terminal className="w-3 h-3" />}
        </span>
        <span className="text-[11px] font-mono text-slate-400 tracking-wide shrink-0">
          {title}
        </span>
        <div className="ml-auto flex items-center gap-1.5 shrink-0 min-w-0">
          {headerRight}
          {meta != null ? (
            <span className="text-[10px] font-mono text-slate-500 shrink-0">{meta}</span>
          ) : null}
        </div>
      </div>
      <div
        ref={bodyRef}
        className={`min-h-0 overflow-y-auto overflow-x-hidden px-2.5 py-2 select-text cursor-text ${
          fill ? 'flex-1' : ''
        } ${bodyClassName}`}
        style={{
          ...(fill
            ? {}
            : {
                height: maxHeight,
                maxHeight,
              }),
          ...bodyStyle,
        }}
      >
        {hasChildren ? (
          children
        ) : emptyText ? (
          <div className="text-[12px] font-mono text-slate-500 py-1">{emptyText}</div>
        ) : null}
      </div>
    </div>
  );
}
