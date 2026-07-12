/**
 * App settings page — behavior / window prefs (not buried in Inspector).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { EyeOff, Link2, Monitor, MousePointer2, RefreshCw, Settings2, Unplug } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useFlowStore } from '@/store/flowModelStore';
import { bridge } from '@/bridge';

type ProcRow = { pid: number; name: string };

export default function SettingsPage({
  themeName,
  themeMode,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const hideWindowOnRecord = useFlowStore((s) => s.hideWindowOnRecord);
  const setHideWindowOnRecord = useFlowStore((s) => s.setHideWindowOnRecord);
  const defaultCaptureMode = useFlowStore((s) => s.defaultCaptureMode);
  const setDefaultCaptureMode = useFlowStore((s) => s.setDefaultCaptureMode);

  const [processes, setProcesses] = useState<ProcRow[]>([]);
  const [processFilter, setProcessFilter] = useState('');
  const [selectedKey, setSelectedKey] = useState(''); // "pid|name"
  const [fridaStatus, setFridaStatus] = useState<{
    attached?: boolean;
    hooked?: boolean;
    process_name?: string | null;
    pid?: number | null;
    last_error?: string | null;
  }>({});
  const [fridaBusy, setFridaBusy] = useState(false);
  const [listBusy, setListBusy] = useState(false);
  const [fridaMsg, setFridaMsg] = useState('');

  const refreshFrida = useCallback(async () => {
    try {
      const st = await bridge.fridaStatus();
      setFridaStatus(st || {});
    } catch {
      setFridaStatus({});
    }
  }, []);

  const refreshProcesses = useCallback(async () => {
    setListBusy(true);
    try {
      const res = await bridge.fridaListProcesses(null);
      if (res?.ok && Array.isArray(res.processes)) {
        setProcesses(res.processes);
      } else {
        setProcesses([]);
        setFridaMsg(res?.error || res?.message || '无法枚举进程');
      }
    } catch (e: any) {
      setProcesses([]);
      setFridaMsg(String(e?.message || e || '枚举进程失败'));
    } finally {
      setListBusy(false);
    }
  }, []);

  useEffect(() => {
    refreshFrida();
    refreshProcesses();
    const t = setInterval(refreshFrida, 3000);
    return () => clearInterval(t);
  }, [refreshFrida, refreshProcesses]);

  const filtered = useMemo(() => {
    const q = processFilter.trim().toLowerCase();
    if (!q) return processes;
    return processes.filter(
      (p) => p.name.toLowerCase().includes(q) || String(p.pid).includes(q),
    );
  }, [processes, processFilter]);

  const selected = useMemo(() => {
    if (!selectedKey || selectedKey === '__empty') return null;
    const pid = Number(selectedKey.split('|')[0]);
    return processes.find((p) => p.pid === pid) || null;
  }, [selectedKey, processes]);

  const handleAttach = async () => {
    if (!selected) {
      setFridaMsg('请先从列表选择进程');
      return;
    }
    setFridaBusy(true);
    setFridaMsg('');
    try {
      const res = await bridge.fridaAttach(selected.name, selected.pid);
      if (res?.ok) {
        setFridaMsg(
          `已连接：${res.process_name || selected.name}${res.pid ? ` (PID ${res.pid})` : ''}`,
        );
      } else {
        setFridaMsg(res?.error || res?.message || '连接失败');
      }
      await refreshFrida();
    } finally {
      setFridaBusy(false);
    }
  };

  const handleDetach = async () => {
    setFridaBusy(true);
    setFridaMsg('');
    try {
      await bridge.fridaDetach();
      setFridaMsg('已断开');
      await refreshFrida();
    } finally {
      setFridaBusy(false);
    }
  };

  return (
    <div className="flex-1 min-w-0 h-full overflow-auto">
      <div className="max-w-xl mx-auto px-8 py-10 space-y-8">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <Settings2 style={{ color: colors.primary }} className="w-5 h-5" />
            <h1 className="font-display text-xl font-semibold" style={{ color: colors.text }}>
              设置
            </h1>
          </div>
          <p className="text-xs leading-relaxed" style={{ color: colors.secondaryText }}>
            全局偏好，保存在本机，与当前流程无关。
          </p>
        </div>

        <section
          className="rounded-2xl border p-5 space-y-4"
          style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        >
          <div className="flex items-center gap-2">
            <MousePointer2 className="w-4 h-4 opacity-70" style={{ color: colors.text }} />
            <h2 className="font-display text-sm font-semibold" style={{ color: colors.text }}>
              点击录入
            </h2>
          </div>
          <Separator />

          <div className="space-y-2">
            <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
              默认录入模式
            </Label>
            <Select
              value={defaultCaptureMode || 'coord'}
              onValueChange={(v) => setDefaultCaptureMode(v)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="coord">坐标（屏幕点击）</SelectItem>
                <SelectItem value="frida_ui">Frida UI（Unity 组件）</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed" style={{ color: colors.secondaryText }}>
              顶栏「录制」与新建点击节点默认使用此模式。单个节点可在右侧 Inspector 覆盖。
              Frida 模式需先连接游戏进程。
            </p>
          </div>
        </section>

        <section
          className="rounded-2xl border p-5 space-y-4"
          style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        >
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 opacity-70" style={{ color: colors.text }} />
            <h2 className="font-display text-sm font-semibold" style={{ color: colors.text }}>
              Frida 连接
            </h2>
          </div>
          <Separator />

          <div className="flex items-center gap-2 text-xs" style={{ color: colors.secondaryText }}>
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                fridaStatus.attached ? 'bg-emerald-500' : 'bg-zinc-400'
              }`}
            />
            {fridaStatus.attached
              ? `已连接${fridaStatus.process_name ? ` · ${fridaStatus.process_name}` : ''}${
                  fridaStatus.pid ? ` · PID ${fridaStatus.pid}` : ''
                }${fridaStatus.hooked ? ' · Hook 就绪' : ' · Hook 未就绪'}`
              : '未连接'}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
                选择进程
              </Label>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                disabled={listBusy}
                onClick={() => refreshProcesses()}
                title="刷新进程列表"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${listBusy ? 'animate-spin' : ''}`} />
                刷新
              </Button>
            </div>
            <Input
              value={processFilter}
              onChange={(e) => setProcessFilter(e.target.value)}
              placeholder="过滤：进程名或 PID"
              className="font-mono text-xs"
            />
            <Select
              value={selectedKey || undefined}
              onValueChange={(v) => {
                if (v !== '__empty') setSelectedKey(v);
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder={listBusy ? '加载中…' : '从列表选择游戏进程'} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {filtered.length === 0 ? (
                  <SelectItem value="__empty" disabled>
                    {listBusy ? '加载中…' : '无匹配进程，点刷新重试'}
                  </SelectItem>
                ) : (
                  filtered.slice(0, 400).map((p) => (
                    <SelectItem key={`${p.pid}|${p.name}`} value={`${p.pid}|${p.name}`}>
                      <span className="font-mono text-xs">
                        {p.name} <span className="opacity-50">PID {p.pid}</span>
                      </span>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            <p className="text-xs leading-relaxed" style={{ color: colors.secondaryText }}>
              按 PID 连接，同名多开也能选对。列表最多显示 400 条，可用过滤缩小范围。
            </p>
          </div>

          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={fridaBusy || !selected} onClick={handleAttach}>
              连接
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={fridaBusy || !fridaStatus.attached}
              onClick={handleDetach}
            >
              <Unplug className="w-3.5 h-3.5" />
              断开
            </Button>
          </div>
          {fridaMsg && (
            <p className="text-xs leading-relaxed" style={{ color: colors.secondaryText }}>
              {fridaMsg}
              {fridaStatus.last_error ? ` · ${fridaStatus.last_error}` : ''}
            </p>
          )}
        </section>

        <section
          className="rounded-2xl border p-5 space-y-4"
          style={{ borderColor: colors.border, backgroundColor: colors.surface }}
        >
          <div className="flex items-center gap-2">
            <Monitor className="w-4 h-4 opacity-70" style={{ color: colors.text }} />
            <h2 className="font-display text-sm font-semibold" style={{ color: colors.text }}>
              窗口与录制
            </h2>
          </div>
          <Separator />

          <div className="flex items-start gap-3">
            <Checkbox
              id="setting-hide-window"
              checked={hideWindowOnRecord}
              onCheckedChange={(v) => setHideWindowOnRecord(!!v)}
              className="mt-0.5"
            />
            <div className="space-y-1.5 min-w-0">
              <Label
                htmlFor="setting-hide-window"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer"
                style={{ color: colors.text }}
              >
                <span className="inline-flex items-center gap-1.5">
                  <EyeOff className="w-3.5 h-3.5 opacity-70" />
                  操作时隐藏主窗口
                </span>
              </Label>
              <p className="text-xs leading-relaxed" style={{ color: colors.secondaryText }}>
                开启后，录制、运行、取点、框选时会暂时隐藏 Nexuz，避免点到本程序。
                <br />
                录制隐藏时使用屏幕右上角外部「停止录制」浮窗；未隐藏时使用应用内浮层。快捷键均为{' '}
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-[10px]">
                  Ctrl+Shift+F10
                </kbd>
                。
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
