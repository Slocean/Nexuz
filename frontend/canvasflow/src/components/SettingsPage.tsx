/**
 * App settings page — behavior / window prefs (not buried in Inspector).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { useAppDialog } from './AppDialogs';

type ProcRow = {
  pid: number;
  name: string;
  window_title?: string;
  exe?: string;
  exe_base?: string;
  has_window?: boolean;
  display?: string;
};

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`${label}超时（${Math.round(ms / 1000)}s）`)), ms);
    promise.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}

export default function SettingsPage({
  themeName,
  themeMode,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const { confirm } = useAppDialog();
  const hideWindowOnRecord = useFlowStore((s) => s.hideWindowOnRecord);
  const setHideWindowOnRecord = useFlowStore((s) => s.setHideWindowOnRecord);
  const defaultCaptureMode = useFlowStore((s) => s.defaultCaptureMode);
  const setDefaultCaptureMode = useFlowStore((s) => s.setDefaultCaptureMode);
  const syncAllClickCaptureModes = useFlowStore((s) => s.syncAllClickCaptureModes);
  const flowNodes = useFlowStore((s) => s.flow.nodes || {});

  const handleDefaultCaptureModeChange = async (next: string) => {
    const mode = next === 'frida_ui' ? 'frida_ui' : 'coord';
    if (mode === defaultCaptureMode) return;

    const clicks = Object.values(flowNodes).filter((n: any) => n?.type === 'click');
    const differing = clicks.filter((n: any) => {
      const cur = n.params?.capture_mode || defaultCaptureMode;
      return cur !== mode;
    });

    if (differing.length > 0) {
      const label = mode === 'frida_ui' ? 'Frida UI' : '坐标';
      const ok = await confirm({
        title: '修改默认点击录入模式',
        description: `当前有 ${differing.length} 个点击节点的录入模式与「${label}」不同。确认后将把所有这些节点改为「${label}」，之后新建的点击节点也会默认使用此模式。`,
        confirmText: '全部修改',
      });
      if (!ok) return;
      syncAllClickCaptureModes(mode);
    }

    setDefaultCaptureMode(mode);
  };

  const [processes, setProcesses] = useState<ProcRow[]>([]);
  const [processFilter, setProcessFilter] = useState('');
  const [selectedKey, setSelectedKey] = useState(''); // "pid|name"
  const [onlyWithWindow, setOnlyWithWindow] = useState(true);
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
  const listSeq = useRef(0);
  const onlyWithWindowRef = useRef(onlyWithWindow);
  onlyWithWindowRef.current = onlyWithWindow;

  const refreshFrida = useCallback(async () => {
    try {
      const st = await bridge.fridaStatus();
      if (st && typeof st === 'object') {
        setFridaStatus(st);
      }
    } catch {
      /* ignore polling errors */
    }
  }, []);

  const refreshProcesses = useCallback(async (withWindow?: boolean) => {
    const flag = typeof withWindow === 'boolean' ? withWindow : onlyWithWindowRef.current;
    const seq = ++listSeq.current;
    setListBusy(true);
    try {
      const res = await withTimeout(
        bridge.fridaListProcesses(null, flag),
        20000,
        '刷新进程列表',
      );
      if (seq !== listSeq.current) return;
      if (res?.ok && Array.isArray(res.processes)) {
        // Keep only fields the UI needs, and cap list size to bound memory.
        const slim = res.processes.slice(0, 500).map((p: ProcRow) => ({
          pid: p.pid,
          name: p.name,
          window_title: p.window_title,
          exe_base: p.exe_base,
          display: p.display,
        }));
        setProcesses(slim);
        setSelectedKey((prev) => {
          if (!prev) return prev;
          const pid = Number(prev.split('|')[0]);
          return slim.some((p: ProcRow) => p.pid === pid) ? prev : '';
        });
        setFridaMsg((m) => (m.startsWith('无法枚举') || m.includes('枚举进程') ? '' : m));
      } else {
        setProcesses([]);
        setFridaMsg(res?.error || res?.message || '无法枚举进程');
      }
    } catch (e: any) {
      if (seq !== listSeq.current) return;
      setProcesses([]);
      setFridaMsg(String(e?.message || e || '枚举进程失败'));
    } finally {
      if (seq === listSeq.current) setListBusy(false);
    }
  }, []);

  useEffect(() => {
    void refreshFrida();
    const t = setInterval(() => {
      void refreshFrida();
    }, 3000);
    return () => clearInterval(t);
  }, [refreshFrida]);

  // Load once on mount + whenever filter mode changes (stable callback, no loop)
  useEffect(() => {
    void refreshProcesses(onlyWithWindow);
  }, [onlyWithWindow, refreshProcesses]);

  const filtered = useMemo(() => {
    const q = processFilter.trim().toLowerCase();
    if (!q) return processes;
    return processes.filter((p) => {
      const hay = [
        p.name,
        String(p.pid),
        p.window_title || '',
        p.exe || '',
        p.exe_base || '',
        p.display || '',
      ]
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
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
    if (fridaBusy) return;
    setFridaBusy(true);
    setFridaMsg(`正在连接 ${selected.name} (PID ${selected.pid})…`);
    try {
      const res = await withTimeout(
        bridge.fridaAttach(selected.name, selected.pid),
        45000,
        '连接进程',
      );
      const ok = res?.ok === true;
      if (ok && res?.attached !== false) {
        if (res.hooked) {
          setFridaMsg(`连接成功：${res.process_name || selected.name}${res.pid ? ` (PID ${res.pid})` : ''} · Hook 就绪`);
        } else {
          const warn = res.warning || res.last_error || 'UI Hook 未就绪';
          setFridaMsg(
            `连接成功：${res.process_name || selected.name}${res.pid ? ` (PID ${res.pid})` : ''} · Hook 未就绪：${warn}`,
          );
        }
      } else {
        setFridaMsg(res?.error || res?.message || res?.last_error || '连接失败');
      }
      await refreshFrida();
    } catch (e: any) {
      setFridaMsg(String(e?.message || e || '连接失败'));
      await refreshFrida();
    } finally {
      setFridaBusy(false);
    }
  };

  const handleDetach = async () => {
    if (fridaBusy) return;
    setFridaBusy(true);
    setFridaMsg('正在断开…');
    try {
      await withTimeout(bridge.fridaDetach(), 15000, '断开连接');
      setFridaMsg('已断开');
      await refreshFrida();
    } catch (e: any) {
      setFridaMsg(String(e?.message || e || '断开失败'));
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
          <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
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
              onValueChange={(v) => {
                void handleDefaultCaptureModeChange(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="coord">坐标（屏幕点击）</SelectItem>
                <SelectItem value="frida_ui">Frida UI（Unity 组件）</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              顶栏「录制」与新建点击节点默认使用此模式。修改时若已有节点模式不一致，将提示并同步全部点击节点。
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
                onClick={() => {
                  void refreshProcesses(onlyWithWindow);
                }}
                title="刷新进程列表"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${listBusy ? 'animate-spin' : ''}`} />
                刷新
              </Button>
            </div>

            <div className="flex items-start gap-3">
              <Checkbox
                id="only-with-window"
                checked={onlyWithWindow}
                onCheckedChange={(v) => setOnlyWithWindow(!!v)}
                className="mt-0.5"
              />
              <Label
                htmlFor="only-with-window"
                className="text-xs font-normal normal-case tracking-normal cursor-pointer leading-relaxed"
                style={{ color: colors.secondaryText }}
              >
                仅显示有窗口的进程（推荐：过滤掉同名后台/辅助进程）
              </Label>
            </div>

            <Input
              value={processFilter}
              onChange={(e) => setProcessFilter(e.target.value)}
              placeholder="过滤：窗口标题 / 进程名 / PID / 路径"
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
                    {listBusy
                      ? '加载中…'
                      : onlyWithWindow
                        ? '无带窗口的进程；可取消勾选或点刷新'
                        : '无匹配进程，点刷新重试'}
                  </SelectItem>
                ) : (
                  filtered.slice(0, 400).map((p) => (
                    <SelectItem key={`${p.pid}|${p.name}`} value={`${p.pid}|${p.name}`}>
                      <span className="font-mono text-xs leading-snug block max-w-[420px] truncate">
                        {p.display ||
                          (p.window_title
                            ? `${p.window_title} · ${p.name} · PID ${p.pid}`
                            : `${p.name} · PID ${p.pid}`)}
                      </span>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {selected && (
              <p className="text-xs font-mono leading-relaxed opacity-70 break-all" style={{ color: colors.secondaryText }}>
                {selected.window_title ? `窗口：${selected.window_title}` : '无窗口标题'}
                {selected.exe ? `\n路径：${selected.exe}` : ''}
              </p>
            )}
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              默认只列出有可见窗口的进程，避免同名辅助进程干扰。选中后按 PID 连接。
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
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              {fridaMsg}
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
              <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
                开启后，录制、运行、取点、框选时会暂时隐藏 Nexuz，避免点到本程序。
                <br />
                录制隐藏时使用屏幕右上角外部「停止录制」浮窗；未隐藏时使用应用内浮层。录制快捷键{' '}
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-xs">
                  Ctrl+X+F10
                </kbd>
                （支持点击/按键/延迟/滚轮，不含拖拽/悬停/打字）。运行中可全局{' '}
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-xs">
                  Ctrl+X+F5
                </kbd>{' '}
                暂停、
                <kbd className="px-1 py-0.5 rounded bg-black/10 dark:bg-white/10 font-mono text-xs">
                  Ctrl+X+F4
                </kbd>{' '}
                结束。
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
