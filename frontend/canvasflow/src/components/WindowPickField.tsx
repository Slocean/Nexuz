/**
 * Window target picker for window_* blocks — click a window or pick from list.
 * Writes title / process_name / class_name; user never needs to guess names.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Crosshair, RefreshCw } from 'lucide-react';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export type WindowMatch = {
  title?: string;
  process_name?: string;
  class_name?: string;
};

type WinItem = {
  title: string;
  process_name: string;
  class_name: string;
  pid?: number;
  label: string;
};

function keyOf(w: WindowMatch) {
  return `${w.process_name || ''}\0${w.title || ''}\0${w.class_name || ''}`;
}

export default function WindowPickField({
  value,
  onChange,
}: {
  value: WindowMatch;
  onChange: (next: WindowMatch) => void;
}) {
  const hideWindow = useFlowStore((s) => s.hideWindowOnRecord);
  const [windows, setWindows] = useState<WinItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await bridge.listWindows?.();
      if (res?.ok === false) {
        setError(res.error || '无法读取窗口列表');
        setWindows([]);
        return;
      }
      const list = Array.isArray(res?.windows) ? res.windows : [];
      setWindows(
        list.map((w: any) => ({
          title: String(w.title || ''),
          process_name: String(w.process_name || ''),
          class_name: String(w.class_name || ''),
          pid: w.pid,
          label: String(w.label || `${w.title || '(无标题)'}  ·  ${w.process_name || '?'}`),
        })),
      );
    } catch (e: any) {
      setError(String(e?.message || e));
      setWindows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const title = String(value?.title || '');
  const process = String(value?.process_name || '');
  const cls = String(value?.class_name || '');
  const hasSelection = !!(title || process || cls);
  const summary = hasSelection
    ? `${title || '(无标题)'}  ·  ${process || '?'}`
    : '';

  const matched = windows.find(
    (w) => keyOf(w) === keyOf({ title, process_name: process, class_name: cls }),
  );
  const selectValue = matched ? keyOf(matched) : undefined;

  const apply = (w: WindowMatch) => {
    onChange({
      title: String(w.title || ''),
      process_name: String(w.process_name || ''),
      class_name: String(w.class_name || ''),
    });
  };

  const handlePick = async () => {
    setPicking(true);
    setError('');
    try {
      const res = await bridge.pickWindow?.(!!hideWindow);
      if (res?.cancelled) return;
      if (res?.ok === false) {
        setError(res.error || res.message || '选取失败');
        return;
      }
      apply({
        title: res?.title || res?.window?.title || '',
        process_name: res?.process_name || res?.window?.process_name || '',
        class_name: res?.class_name || res?.window?.class_name || '',
      });
      await refresh();
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className="flex-1 min-w-0 space-y-2">
      <div className="flex gap-1.5">
        <Button
          type="button"
          variant="default"
          size="sm"
          className="h-8 flex-1 text-xs"
          disabled={picking}
          onClick={() => void handlePick()}
        >
          <Crosshair className="w-3.5 h-3.5 mr-1" />
          {picking ? '请点击目标窗口…' : '选取窗口'}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-8 w-8 shrink-0"
          disabled={loading}
          title="刷新列表"
          onClick={() => void refresh()}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <Select
        value={selectValue}
        onValueChange={(k) => {
          const w = windows.find((item) => keyOf(item) === k);
          if (w) apply(w);
        }}
      >
        <SelectTrigger className="h-8 text-xs w-full">
          <SelectValue placeholder={loading ? '加载窗口列表…' : '或从已打开窗口选择'} />
        </SelectTrigger>
        <SelectContent className="z-[200] max-h-72">
          {windows.length === 0 ? (
            <SelectItem value="__empty" disabled>
              暂无窗口，点刷新或「选取窗口」
            </SelectItem>
          ) : (
            windows.map((w) => (
              <SelectItem key={keyOf(w)} value={keyOf(w)}>
                {w.label}
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>

      {hasSelection ? (
        <div className="rounded-md border border-border/60 bg-muted/30 px-2.5 py-2 text-[11px] leading-relaxed">
          <div className="font-medium opacity-90">已选：{summary}</div>
          {cls ? <div className="opacity-50 mt-0.5 font-mono truncate">类名 {cls}</div> : null}
        </div>
      ) : (
        <p className="text-[10px] opacity-50 leading-relaxed">
          用法：点「选取窗口」，再点一下你要自动化的程序（如记事本、浏览器）。不必手填名字。
        </p>
      )}

      {error ? <p className="text-[10px] text-rose-400">{error}</p> : null}
    </div>
  );
}
