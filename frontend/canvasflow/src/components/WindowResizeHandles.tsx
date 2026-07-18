import React, { useCallback, useEffect, useRef, useState } from 'react';
import { bridge } from '@/bridge';

const EDGE = 6;

type Edge =
  | 'left'
  | 'right'
  | 'top'
  | 'bottom'
  | 'topleft'
  | 'topright'
  | 'bottomleft'
  | 'bottomright';

const CURSOR: Record<Edge, string> = {
  left: 'ew-resize',
  right: 'ew-resize',
  top: 'ns-resize',
  bottom: 'ns-resize',
  topleft: 'nwse-resize',
  bottomright: 'nwse-resize',
  topright: 'nesw-resize',
  bottomleft: 'nesw-resize',
};

/**
 * Frameless pywebview windows have no OS resize borders.
 * Edge hit zones start a native Win32 drag loop via the bridge.
 */
export default function WindowResizeHandles() {
  const [maximized, setMaximized] = useState(false);
  const dragging = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      bridge
        .windowIsMaximized?.()
        .then((res: any) => {
          if (!cancelled && res?.maximized != null) setMaximized(!!res.maximized);
        })
        .catch(() => {});
    };
    refresh();
    const t = window.setInterval(refresh, 800);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  const begin = useCallback(
    (edge: Edge) => (e: React.MouseEvent) => {
      if (maximized || dragging.current) return;
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      dragging.current = true;
      // Fire immediately while LMB is still down (bridge is async).
      void Promise.resolve(bridge.windowBeginResize?.(edge))
        .catch(() => {})
        .finally(() => {
          dragging.current = false;
        });
    },
    [maximized],
  );

  if (maximized) return null;

  const base = 'fixed z-[9999] pointer-events-auto select-none';
  const styleFor = (edge: Edge): React.CSSProperties => ({
    cursor: CURSOR[edge],
    // Keep hit target above chrome; transparent fill still receives events.
    background: 'transparent',
  });

  return (
    <>
      <div
        className={`${base} top-0 bottom-0 left-0`}
        style={{ ...styleFor('left'), width: EDGE }}
        onMouseDown={begin('left')}
      />
      <div
        className={`${base} top-0 bottom-0 right-0`}
        style={{ ...styleFor('right'), width: EDGE }}
        onMouseDown={begin('right')}
      />
      <div
        className={`${base} left-0 right-0 top-0`}
        style={{ ...styleFor('top'), height: EDGE }}
        onMouseDown={begin('top')}
      />
      <div
        className={`${base} left-0 right-0 bottom-0`}
        style={{ ...styleFor('bottom'), height: EDGE }}
        onMouseDown={begin('bottom')}
      />
      <div
        className={`${base} left-0 top-0`}
        style={{ ...styleFor('topleft'), width: EDGE + 6, height: EDGE + 6 }}
        onMouseDown={begin('topleft')}
      />
      <div
        className={`${base} right-0 top-0`}
        style={{ ...styleFor('topright'), width: EDGE + 6, height: EDGE + 6 }}
        onMouseDown={begin('topright')}
      />
      <div
        className={`${base} left-0 bottom-0`}
        style={{ ...styleFor('bottomleft'), width: EDGE + 6, height: EDGE + 6 }}
        onMouseDown={begin('bottomleft')}
      />
      <div
        className={`${base} right-0 bottom-0`}
        style={{ ...styleFor('bottomright'), width: EDGE + 6, height: EDGE + 6 }}
        onMouseDown={begin('bottomright')}
      />
    </>
  );
}
