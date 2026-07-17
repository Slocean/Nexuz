import React, { useCallback, useRef, useState } from 'react';
import { bridge } from '@/bridge';
import {
  ScreenshotPickDialog,
  type ScreenshotCapture,
  type ScreenshotPickMode,
  type ScreenshotPickResult,
} from '../components/ScreenshotPickDialog';

type Session = {
  mode: ScreenshotPickMode;
  capture: ScreenshotCapture;
  resolve: (result: any) => void;
};

/**
 * Unified screenshot pick for coord mode: capture desktop → zoom/pan dialog →
 * point / region / template. Results match pack_point / pack_region shape.
 */
export function useScreenshotPick({ hideWindow = true }: { hideWindow?: boolean } = {}) {
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const busyRef = useRef(false);

  const openSession = useCallback(
    async (mode: ScreenshotPickMode): Promise<any> => {
      if (busyRef.current) {
        return { ok: false, error: '已有取点会话进行中' };
      }
      busyRef.current = true;
      try {
        const cap = await bridge.captureDesktop(!!hideWindow);
        if (!cap?.ok || !cap.data_url) {
          busyRef.current = false;
          return cap?.ok === false
            ? cap
            : { ok: false, error: cap?.error || '截屏失败' };
        }
        const capture: ScreenshotCapture = {
          data_url: cap.data_url,
          width: Number(cap.width) || 0,
          height: Number(cap.height) || 0,
          left: Number(cap.left) || 0,
          top: Number(cap.top) || 0,
          coord_space: cap.coord_space,
        };
        return await new Promise((resolve) => {
          const next: Session = { mode, capture, resolve };
          sessionRef.current = next;
          setSession(next);
        });
      } catch (err: any) {
        busyRef.current = false;
        return { ok: false, error: String(err?.message || err) };
      }
    },
    [hideWindow],
  );

  const finish = useCallback(async (raw: ScreenshotPickResult) => {
    const current = sessionRef.current;
    sessionRef.current = null;
    setSession(null);
    busyRef.current = false;
    if (!current) return;

    if (!raw.ok) {
      current.resolve(raw);
      return;
    }

    try {
      if (raw.kind === 'point') {
        const packed = await bridge.packScreenPoint(raw.x, raw.y, raw.color);
        const space =
          current.capture.coord_space ||
          packed?.coord_space || {
            w: current.capture.width,
            h: current.capture.height,
            left: current.capture.left,
            top: current.capture.top,
          };
        const w = Number((space as any).w) || current.capture.width || 1;
        const h = Number((space as any).h) || current.capture.height || 1;
        const left = Number((space as any).left) ?? current.capture.left;
        const top = Number((space as any).top) ?? current.capture.top;
        const x = Math.round(raw.x);
        const y = Math.round(raw.y);
        const point_norm = [(x - left) / w, (y - top) / h];
        const color = raw.color ?? packed?.color;
        const coord = {
          x,
          y,
          coordinate_mode: 'screen_abs',
          point_norm,
          coord_space: space,
          window_target: packed?.window_target,
        };
        // Match pick_click(coord) shape so applyClickCapture / applyPointPick both work
        const params = {
          capture_mode: 'coord',
          coordinate_mode: 'screen_abs',
          button: 'left',
          click_type: 'single',
          move_duration: 0,
          coord,
          x,
          y,
          point_norm,
          coord_space: space,
          window_target: packed?.window_target,
        };
        current.resolve({
          ok: true,
          params,
          button: 'left',
          color,
          x,
          y,
          point_norm,
          coord_space: space,
        });
        return;
      }

      if (raw.kind === 'region') {
        const space = current.capture.coord_space || {
          w: current.capture.width,
          h: current.capture.height,
          left: current.capture.left,
          top: current.capture.top,
        };
        const w = Number((space as any).w) || current.capture.width || 1;
        const h = Number((space as any).h) || current.capture.height || 1;
        const left = Number((space as any).left) ?? current.capture.left;
        const top = Number((space as any).top) ?? current.capture.top;
        const [x1, y1, x2, y2] = raw.region;
        current.resolve({
          ok: true,
          region: raw.region.map(Math.round),
          region_norm: [
            (x1 - left) / w,
            (y1 - top) / h,
            (x2 - left) / w,
            (y2 - top) / h,
          ],
          coord_space: space,
        });
        return;
      }

      if (raw.kind === 'template') {
        const saved = await bridge.captureTemplateFromRegion(
          raw.region,
          null,
          current.capture.data_url,
          current.capture.left,
          current.capture.top,
        );
        current.resolve(saved);
        return;
      }

      current.resolve({ ok: false, error: '未知结果类型' });
    } catch (err: any) {
      current.resolve({ ok: false, error: String(err?.message || err) });
    }
  }, []);

  const pickPoint = useCallback(() => openSession('point'), [openSession]);
  const pickRegion = useCallback(() => openSession('region'), [openSession]);
  const captureTemplate = useCallback(() => openSession('template'), [openSession]);

  const dialog = (
    <ScreenshotPickDialog
      open={!!session}
      mode={session?.mode || 'point'}
      capture={session?.capture || null}
      onClose={(result) => {
        void finish(result);
      }}
    />
  );

  return { pickPoint, pickRegion, captureTemplate, dialog };
}

export default useScreenshotPick;
