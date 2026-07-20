import React from 'react';

type Orientation = 'horizontal' | 'vertical';

type Props = {
  orientation: Orientation;
  /** Current size being resized (height for horizontal, width for vertical). */
  value: number;
  onChange: (next: number) => void;
  onCommit?: (next: number) => void;
  onReset?: () => void;
  min: number;
  max: number;
  /**
   * When true, pointer moving in the positive axis shrinks `value`
   * (e.g. right inspector: drag handle right → narrower panel).
   */
  invert?: boolean;
  label: string;
  gripColor: string;
  className?: string;
};

/**
 * Thin split grip — same visual language for log height and side panel width.
 * No full divider line; only a short centered bar.
 */
export default function SplitHandle({
  orientation,
  value,
  onChange,
  onCommit,
  onReset,
  min,
  max,
  invert = false,
  label,
  gripColor,
  className = '',
}: Props) {
  const dragRef = React.useRef<{ start: number; startValue: number } | null>(null);
  const valueRef = React.useRef(value);
  valueRef.current = value;

  const horizontal = orientation === 'horizontal';

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = {
      start: horizontal ? e.clientY : e.clientX,
      startValue: value,
    };
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const cur = horizontal ? e.clientY : e.clientX;
    const raw = cur - drag.start;
    const delta = invert ? -raw : raw;
    // horizontal: drag up (negative Y) grows bottom panel → invert Y for height
    const adjusted = horizontal ? -delta : delta;
    const next = Math.min(max, Math.max(min, drag.startValue + adjusted));
    onChange(next);
  };

  const endDrag = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    onCommit?.(valueRef.current);
  };

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-label={label}
      title={label}
      className={[
        'group shrink-0 touch-none select-none flex items-center justify-center',
        'hover:bg-black/4 dark:hover:bg-white/4 active:bg-black/6 dark:active:bg-white/6',
        horizontal ? 'h-2 w-full cursor-row-resize' : 'w-2 h-full cursor-col-resize',
        className,
      ].join(' ')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={() => onReset?.()}
    >
      <div
        className={[
          'rounded-full opacity-35 group-hover:opacity-70 transition-opacity',
          horizontal ? 'h-1 w-10' : 'w-1 h-10',
        ].join(' ')}
        style={{ backgroundColor: gripColor }}
      />
    </div>
  );
}
