/**
 * App settings page — behavior / window prefs (not buried in Inspector).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  EyeOff,
  ExternalLink,
  FolderOpen,
  HardDrive,
  Info,
  Link2,
  Megaphone,
  Monitor,
  MousePointer2,
  RefreshCw,
  Settings2,
  Trash2,
  Unplug,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Keyboard,
} from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
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
import { useUpdateDialog } from './UpdateDialog';

type ThemeColors = ReturnType<typeof getThemeColors>;

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

/** ? icon — portal tooltip (opaque, not clipped by overflow) */
function HelpHint({
  text,
  colors,
  themeMode,
}: {
  text: React.ReactNode;
  colors: ThemeColors;
  themeMode: ThemeMode;
}) {
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; width: number } | null>(null);

  const updatePos = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const tipW = Math.min(320, Math.max(160, window.innerWidth - 16));
    const tipH = tipRef.current?.offsetHeight || 96;
    let left = r.left + r.width / 2 - tipW / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tipW - 8));
    const spaceAbove = r.top - 8;
    const spaceBelow = window.innerHeight - r.bottom - 8;
    let top: number;
    if (spaceAbove >= tipH + 4 || spaceAbove >= spaceBelow) {
      top = Math.max(8, r.top - tipH - 8);
    } else {
      top = r.bottom + 8;
      if (top + tipH > window.innerHeight - 8) {
        top = Math.max(8, window.innerHeight - tipH - 8);
      }
    }
    setPos({ left, top, width: tipW });
  }, []);

  const show = useCallback(() => {
    setOpen(true);
    updatePos();
    requestAnimationFrame(() => {
      updatePos();
      requestAnimationFrame(updatePos);
    });
  }, [updatePos]);

  const hide = useCallback(() => {
    setOpen(false);
    setPos(null);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onScrollOrResize = () => updatePos();
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize);
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true);
      window.removeEventListener('resize', onScrollOrResize);
    };
  }, [open, updatePos]);

  const tipBg = themeMode === 'dark' ? '#141822' : '#ffffff';
  const tipFg = themeMode === 'dark' ? '#e8eaef' : '#1a1d26';
  const tipBorder = themeMode === 'dark' ? 'rgba(255,255,255,0.16)' : 'rgba(0,0,0,0.12)';

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex items-center align-middle shrink-0"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      <span
        className="inline-flex items-center justify-center w-4 h-4 rounded-full cursor-help opacity-50 hover:opacity-90"
        style={{ color: colors.secondaryText }}
        tabIndex={0}
        aria-label="说明"
      >
        <CircleHelp className="w-3.5 h-3.5" />
      </span>
      {open &&
        createPortal(
          <div
            ref={tipRef}
            role="tooltip"
            className="fixed z-[300] rounded-lg border px-2.5 py-1.5 text-xs leading-relaxed pointer-events-none"
            style={{
              left: pos?.left ?? -9999,
              top: pos?.top ?? -9999,
              width: pos?.width ?? Math.min(320, window.innerWidth - 16),
              visibility: pos ? 'visible' : 'hidden',
              borderColor: tipBorder,
              backgroundColor: tipBg,
              color: tipFg,
              boxShadow:
                themeMode === 'dark'
                  ? '0 10px 32px rgba(0,0,0,0.55)'
                  : '0 10px 32px rgba(0,0,0,0.18)',
            }}
          >
            {text}
          </div>,
          document.body,
        )}
    </span>
  );
}

function SettingsSection({
  title,
  icon,
  open,
  onToggle,
  colors,
  headerRight,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  colors: ThemeColors;
  headerRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-2xl border overflow-hidden"
      style={{ borderColor: colors.border, backgroundColor: colors.surface }}
    >
      <div className="flex items-center gap-1 pr-2">
        <button
          type="button"
          className="flex-1 min-w-0 flex items-center gap-2 px-4 py-3.5 text-left hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
          onClick={onToggle}
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="w-4 h-4 shrink-0 opacity-60" style={{ color: colors.text }} />
          ) : (
            <ChevronRight className="w-4 h-4 shrink-0 opacity-60" style={{ color: colors.text }} />
          )}
          <span className="shrink-0 opacity-70" style={{ color: colors.text }}>
            {icon}
          </span>
          <h2 className="font-display text-sm font-semibold truncate" style={{ color: colors.text }}>
            {title}
          </h2>
        </button>
        {headerRight ? (
          <div className="shrink-0 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            {headerRight}
          </div>
        ) : null}
      </div>
      {open ? <div className="px-5 pb-5 space-y-4 border-t" style={{ borderColor: colors.border }}>{children}</div> : null}
    </section>
  );
}

const SETTINGS_SECTION_IDS = [
  'about',
  'data',
  'announce',
  'click',
  'frida',
  'window',
  'shortcuts',
] as const;

type SectionId = (typeof SETTINGS_SECTION_IDS)[number];

export default function SettingsPage({
  themeName,
  themeMode,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const { confirm } = useAppDialog();
  const { openUpdate } = useUpdateDialog();
  const hideWindowOnRecord = useFlowStore((s) => s.hideWindowOnRecord);
  const setHideWindowOnRecord = useFlowStore((s) => s.setHideWindowOnRecord);
  const defaultCaptureMode = useFlowStore((s) => s.defaultCaptureMode);
  const setDefaultCaptureMode = useFlowStore((s) => s.setDefaultCaptureMode);
  const defaultPickMethod = useFlowStore((s) => s.defaultPickMethod);
  const setDefaultPickMethod = useFlowStore((s) => s.setDefaultPickMethod);
  const defaultCoordinateMode = useFlowStore((s) => s.defaultCoordinateMode);
  const setDefaultCoordinateMode = useFlowStore((s) => s.setDefaultCoordinateMode);
  const defaultNodeIntervalMs = useFlowStore((s) => s.defaultNodeIntervalMs);
  const setDefaultNodeIntervalMs = useFlowStore((s) => s.setDefaultNodeIntervalMs);
  const syncAllPickMethods = useFlowStore((s) => s.syncAllPickMethods);
  const syncAllClickCaptureModes = useFlowStore((s) => s.syncAllClickCaptureModes);
  const syncAllClickCoordinateModes = useFlowStore((s) => s.syncAllClickCoordinateModes);
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

  const handleDefaultPickMethodChange = async (next: string) => {
    const method = next === 'live' ? 'live' : 'screenshot';
    if (method === defaultPickMethod) return;

    const differing = Object.values(flowNodes).filter((n: any) => {
      const cur = n?.params?.pick_method;
      return (cur === 'live' || cur === 'screenshot') && cur !== method;
    });

    if (differing.length > 0) {
      const label = method === 'live' ? '实地取点' : '截图取点';
      const ok = await confirm({
        title: '修改默认取色 / 取点方式',
        description: `当前有 ${differing.length} 个节点的取点方式与「${label}」不同。确认后将把这些节点全部改为「${label}」，之后未单独设置的节点也会默认使用此方式。`,
        confirmText: '全部修改',
      });
      if (!ok) return;
      syncAllPickMethods(method);
    }

    setDefaultPickMethod(method);
  };

  const handleDefaultCoordinateModeChange = async (next: string) => {
    const mode =
      next === 'window_client' || next === 'virtual_norm' ? next : 'screen_abs';
    if (mode === defaultCoordinateMode) return;

    const differing = Object.values(flowNodes).filter((n: any) => {
      if (n?.type !== 'click' || (n.params?.capture_mode || 'coord') !== 'coord') return false;
      const cur =
        n.params?.coord?.coordinate_mode ||
        n.params?.coordinate_mode ||
        defaultCoordinateMode;
      return cur !== mode;
    });

    if (differing.length > 0) {
      const labels: Record<string, string> = {
        screen_abs: '屏幕绝对坐标',
        window_client: '目标窗口相对',
        virtual_norm: '虚拟桌面比例',
      };
      const ok = await confirm({
        title: '修改默认坐标基准',
        description: `当前有 ${differing.length} 个坐标点击节点的坐标基准与「${labels[mode]}」不同。确认后将把这些节点全部改为「${labels[mode]}」，之后新建点击节点也会默认选中此基准。`,
        confirmText: '全部修改',
      });
      if (!ok) return;
      syncAllClickCoordinateModes(mode);
    }

    setDefaultCoordinateMode(mode);
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

  const [appVersion, setAppVersion] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);
  const [updateMsg, setUpdateMsg] = useState('');
  const [updateInfo, setUpdateInfo] = useState<any>(null);
  const [autoCheckUpdate, setAutoCheckUpdate] = useState(() => {
    try {
      const v = localStorage.getItem('nexuz.autoCheckUpdate');
      if (v === null) return true;
      return v !== '0' && v !== 'false';
    } catch {
      return true;
    }
  });
  const [announcement, setAnnouncement] = useState<any>(null);
  const [updateHistory, setUpdateHistory] = useState<any[]>([]);
  const [annOpenIds, setAnnOpenIds] = useState<Record<string, boolean>>({});
  const [annBusy, setAnnBusy] = useState(false);

  const [dataDirPath, setDataDirPath] = useState('');
  const [dataDirDefault, setDataDirDefault] = useState('');
  const [dataDirExists, setDataDirExists] = useState(false);
  const [dataDirIsDefault, setDataDirIsDefault] = useState(true);
  const [dataDirBusy, setDataDirBusy] = useState(false);
  const [dataDirMsg, setDataDirMsg] = useState('');

  const refreshDataDir = useCallback(async () => {
    try {
      const info = await bridge.getDataDirInfo();
      if (info?.ok) {
        setDataDirPath(String(info.path || ''));
        setDataDirDefault(String(info.default_path || ''));
        setDataDirExists(!!info.exists);
        setDataDirIsDefault(info.is_default !== false);
      }
    } catch {
      /* ignore */
    }
  }, []);

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

  const loadAbout = useCallback(async () => {
    try {
      const info = await bridge.getAppInfo();
      if (info?.version) setAppVersion(String(info.version));
    } catch {
      /* ignore */
    }
  }, []);

  const loadAnnouncement = useCallback(async () => {
    setAnnBusy(true);
    try {
      const res = await withTimeout(bridge.fetchAnnouncement(), 15000, '获取公告');
      if (res?.ok) {
        setAnnouncement(res.announcement || null);
        const hist = Array.isArray(res.history) ? res.history : [];
        setUpdateHistory(hist);
        // Expand only the latest by default
        const open: Record<string, boolean> = {};
        hist.forEach((item: any, idx: number) => {
          const key = String(item.version || item.id || idx);
          open[key] = idx === 0;
        });
        setAnnOpenIds(open);
      } else {
        setAnnouncement(null);
        setUpdateHistory([]);
      }
    } catch {
      setAnnouncement(null);
      setUpdateHistory([]);
    } finally {
      setAnnBusy(false);
    }
  }, []);

  useEffect(() => {
    if (fridaBusy) return;
    void refreshFrida();
    // Attached: poll every 3s (backend status is a fast path). Detached: 10s.
    const intervalMs = fridaStatus.attached ? 3000 : 10000;
    const t = setInterval(() => {
      void refreshFrida();
    }, intervalMs);
    return () => clearInterval(t);
  }, [refreshFrida, fridaBusy, fridaStatus.attached]);

  useEffect(() => {
    void refreshProcesses(onlyWithWindow);
  }, [onlyWithWindow, refreshProcesses]);

  useEffect(() => {
    void loadAbout();
    void loadAnnouncement();
    void refreshDataDir();
  }, [loadAbout, loadAnnouncement, refreshDataDir]);

  const handleOpenDataDir = async () => {
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.openDataDir();
      if (!res?.ok) setDataDirMsg(res?.error || '无法打开数据目录');
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

  const handlePickDataDir = async () => {
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.pickDataDir();
      if (res?.cancelled) return;
      if (!res?.ok) {
        setDataDirMsg(res?.error || '更改失败');
        return;
      }
      setDataDirMsg(`已更改存储位置：${res.path}`);
      await refreshDataDir();
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

  const handleResetDataDir = async () => {
    const ok = await confirm({
      title: '恢复默认存储位置',
      description: `将改回默认路径：\n${dataDirDefault || '%LOCALAPPDATA%\\Nexuz'}\n不会自动搬移已有文件。`,
      confirmText: '恢复默认',
    });
    if (!ok) return;
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.setDataDirPath(null);
      if (!res?.ok) {
        setDataDirMsg(res?.error || '恢复失败');
        return;
      }
      setDataDirMsg(`已恢复默认：${res.path}`);
      await refreshDataDir();
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

  const handleClearDataDir = async () => {
    const ok = await confirm({
      title: '清空数据目录',
      description: `将永久删除整个数据文件夹及其内容（流程、模板、截图等）：\n${dataDirPath || '（未知）'}\n\n此操作不可恢复。清空后目录会被移除，只有再次保存到此位置时才会新建。`,
      confirmText: '删除整个文件夹',
      destructive: true,
    });
    if (!ok) return;
    const ok2 = await confirm({
      title: '再次确认',
      description: '确定要删除整个数据目录吗？',
      confirmText: '确定删除',
      destructive: true,
    });
    if (!ok2) return;
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.clearDataDir();
      if (!res?.ok) {
        setDataDirMsg(res?.error || '清空失败');
        return;
      }
      setDataDirMsg(res.deleted ? '数据目录已删除' : res.message || '目录本就不存在');
      await refreshDataDir();
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

  const handleClearScreenshotCache = async () => {
    const ok = await confirm({
      title: '清理截图缓存',
      description:
        '将删除数据目录下 screenshots 中的区域截图、图像匹配预览等缓存文件。\n不会删除流程，也不会删除 templates 里的模板图片。',
      confirmText: '清理缓存',
      destructive: true,
    });
    if (!ok) return;
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.clearScreenshotCache();
      if (!res?.ok) {
        setDataDirMsg(res?.error || '清理失败');
        return;
      }
      setDataDirMsg(res.message || `已清理 ${res.deleted || 0} 个文件`);
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

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

  const handleCheckUpdate = async () => {
    if (updateBusy) return;
    setUpdateBusy(true);
    setUpdateMsg('正在检查更新…');
    try {
      // Dialog opens immediately with loading
      const res = await openUpdate();
      setUpdateInfo(res);
      if (!res?.ok) {
        setUpdateMsg(res?.error || '检查失败');
        return;
      }
      setUpdateMsg(res.message || (res.update_available ? '发现新版本' : '已是最新版本'));
    } catch (e: any) {
      setUpdateMsg(String(e?.message || e || '检查失败'));
    } finally {
      setUpdateBusy(false);
    }
  };

  const handleAutoCheckChange = (checked: boolean) => {
    setAutoCheckUpdate(checked);
    try {
      localStorage.setItem('nexuz.autoCheckUpdate', checked ? '1' : '0');
    } catch {
      /* ignore */
    }
  };

  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>(() =>
    Object.fromEntries(SETTINGS_SECTION_IDS.map((id) => [id, false])) as Record<SectionId, boolean>,
  );
  const toggleSection = (id: SectionId) => {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="flex-1 min-w-0 h-full overflow-auto">
      <div className="max-w-xl mx-auto px-8 py-10 space-y-3">
        <div className="flex items-center gap-2 mb-5">
          <Settings2 style={{ color: colors.primary }} className="w-5 h-5" />
          <h1 className="font-display text-xl font-semibold" style={{ color: colors.text }}>
            设置
          </h1>
          <HelpHint text="全局偏好，保存在本机，与当前流程无关。" colors={colors} themeMode={themeMode} />
        </div>

        <SettingsSection
          title="关于与更新"
          icon={<Info className="w-4 h-4" />}
          open={openSections.about}
          onToggle={() => toggleSection('about')}
          colors={colors}
          headerRight={
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 px-2"
              disabled={updateBusy}
              onClick={() => void bridge.openReleasesPage()}
              title="打开 GitHub Releases"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Releases
            </Button>
          }
        >
          <p className="text-sm pt-1" style={{ color: colors.text }}>
            当前版本{' '}
            <span className="font-mono font-medium">{appVersion || '…'}</span>
            {updateInfo?.latest_version && updateInfo?.update_available ? (
              <span className="ml-2 text-amber-600 dark:text-amber-400">
                · 可更新至 {updateInfo.latest_version}
              </span>
            ) : null}
          </p>

          <div className="flex items-center gap-2">
            <Checkbox
              id="auto-check-update"
              checked={autoCheckUpdate}
              onCheckedChange={(v) => handleAutoCheckChange(v === true)}
            />
            <Label
              htmlFor="auto-check-update"
              className="text-sm cursor-pointer inline-flex items-center gap-1.5"
              style={{ color: colors.text }}
            >
              程序启动时自动检查新版本
            </Label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={updateBusy} onClick={() => void handleCheckUpdate()}>
              <RefreshCw className={`w-3.5 h-3.5 ${updateBusy ? 'animate-spin' : ''}`} />
              检查更新
            </Button>
            {!updateMsg ? (
              <HelpHint
                text="点击「检查更新」可下载并安装新版本；下载进度与「立即更新」都在同一弹窗内完成。"
                colors={colors}
                themeMode={themeMode}
              />
            ) : null}
          </div>
          {updateMsg ? (
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              {updateMsg}
            </p>
          ) : null}
        </SettingsSection>

        <SettingsSection
          title="数据存储"
          icon={<HardDrive className="w-4 h-4" />}
          open={openSections.data}
          onToggle={() => toggleSection('data')}
          colors={colors}
          headerRight={<HelpHint text="流程、模板、截图等保存在本机数据目录（默认 %LOCALAPPDATA%\Nexuz）。热更新只替换程序，不会动这里。" colors={colors} themeMode={themeMode} />}
        >
          <div
            className="rounded-xl border px-3 py-2.5 font-mono text-xs break-all mt-1"
            style={{ borderColor: colors.border, color: colors.text }}
          >
            {dataDirPath || '…'}
            <span className="block mt-1 opacity-60">
              {dataDirExists ? '目录存在' : '目录不存在（保存后会自动创建）'}
              {dataDirIsDefault ? ' · 默认位置' : ' · 自定义位置'}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="outline" disabled={dataDirBusy} onClick={() => void handleOpenDataDir()}>
              <FolderOpen className="w-3.5 h-3.5" />
              打开数据目录
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={dataDirBusy} onClick={() => void handlePickDataDir()}>
              更改位置
            </Button>
            {!dataDirIsDefault && (
              <Button type="button" size="sm" variant="ghost" disabled={dataDirBusy} onClick={() => void handleResetDataDir()}>
                恢复默认
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handleClearScreenshotCache()}
              title="清理 screenshots 缓存（区域截图 / 匹配预览），不影响流程与模板"
            >
              <Trash2 className="w-3.5 h-3.5" />
              清理截图缓存
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              className="text-rose-500 border-rose-500/40 hover:bg-rose-500/10"
              onClick={() => void handleClearDataDir()}
            >
              <Trash2 className="w-3.5 h-3.5" />
              清空数据目录
            </Button>
          </div>
          {dataDirMsg ? (
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              {dataDirMsg}
            </p>
          ) : null}
        </SettingsSection>

        <SettingsSection
          title="更新公告"
          icon={<Megaphone className="w-4 h-4" />}
          open={openSections.announce}
          onToggle={() => toggleSection('announce')}
          colors={colors}
          headerRight={
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 px-2"
              disabled={annBusy}
              onClick={() => void loadAnnouncement()}
              title="刷新公告"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${annBusy ? 'animate-spin' : ''}`} />
            </Button>
          }
        >
          {updateHistory.length > 0 || announcement?.body ? (
            <div
              className="max-h-72 overflow-y-auto pr-1 space-y-1 rounded-xl border mt-1"
              style={{ borderColor: colors.border }}
            >
              {(updateHistory.length ? updateHistory : [announcement]).map((item: any, idx: number) => {
                const key = String(item.version || item.id || idx);
                const open = !!annOpenIds[key];
                return (
                  <div
                    key={key}
                    className="border-b last:border-b-0"
                    style={{ borderColor: colors.border }}
                  >
                    <button
                      type="button"
                      className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-black/5 dark:hover:bg-white/5"
                      onClick={() =>
                        setAnnOpenIds((prev) => ({ ...prev, [key]: !prev[key] }))
                      }
                    >
                      {open ? (
                        <ChevronDown className="w-3.5 h-3.5 shrink-0 opacity-70" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-70" />
                      )}
                      <span className="font-mono text-xs opacity-70 shrink-0">
                        v{item.version || item.id || '?'}
                      </span>
                      <span
                        className="text-sm font-medium truncate flex-1"
                        style={{ color: colors.text }}
                      >
                        {item.title || '更新'}
                      </span>
                    </button>
                    {open ? (
                      <div
                        className="px-3 pb-3 pl-9 text-sm leading-relaxed whitespace-pre-wrap"
                        style={{ color: colors.secondaryText }}
                      >
                        {item.body || '（无正文）'}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="text-sm leading-relaxed mt-1" style={{ color: colors.secondaryText }}>
              {annBusy ? '加载中…' : '暂无公告'}
            </p>
          )}
        </SettingsSection>

        <SettingsSection
          title="点击录入"
          icon={<MousePointer2 className="w-4 h-4" />}
          open={openSections.click}
          onToggle={() => toggleSection('click')}
          colors={colors}
        >
          <div className="space-y-2 pt-1">
            <div className="flex items-center gap-1.5">
              <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
                默认录入模式
              </Label>
              <HelpHint
                text="顶栏「录制」与新建点击节点默认使用此模式。修改时若已有节点模式不一致，将提示并同步全部点击节点。Frida 模式需先连接游戏进程。"
                colors={colors}
                themeMode={themeMode}
              />
            </div>
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
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
                取色 / 取点方式
              </Label>
              <HelpHint
                text="坐标模式下的取点、框选、截模板默认方式。修改时若已有节点取点方式不一致，将提示并同步这些节点。也可在节点参数里单独修改。Frida UI 录入不受此项影响。"
                colors={colors}
                themeMode={themeMode}
              />
            </div>
            <Select
              value={defaultPickMethod || 'screenshot'}
              onValueChange={(v) => {
                void handleDefaultPickMethodChange(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="screenshot">截图取点（弹窗缩放点选）</SelectItem>
                <SelectItem value="live">实地取点（全屏叠加实时点选）</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
                默认坐标基准
              </Label>
              <HelpHint
                text="新建坐标点击节点默认选中此基准。修改时若当前画布已有不同设置的坐标点击节点，将先提示并同步这些节点。"
                colors={colors}
                themeMode={themeMode}
              />
            </div>
            <Select
              value={defaultCoordinateMode || 'screen_abs'}
              onValueChange={(v) => {
                void handleDefaultCoordinateModeChange(v);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="screen_abs">屏幕绝对坐标</SelectItem>
                <SelectItem value="window_client">目标窗口相对（推荐）</SelectItem>
                <SelectItem value="virtual_norm">虚拟桌面比例</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Label
                htmlFor="default-node-interval"
                className="text-sm font-medium normal-case tracking-normal"
                style={{ color: colors.text }}
              >
                节点间延时（毫秒）
              </Label>
              <HelpHint
                text="每次进入后续节点前等待此时长；首个节点默认不等待。节点检查器可为单个节点设置独立的进入前延时，填写 0 可明确取消该节点等待。"
                colors={colors}
                themeMode={themeMode}
              />
            </div>
            <Input
              id="default-node-interval"
              type="number"
              min={0}
              step={10}
              value={defaultNodeIntervalMs ?? 0}
              onChange={(e) => setDefaultNodeIntervalMs(e.target.value)}
            />
          </div>
        </SettingsSection>

        <SettingsSection
          title="Frida 连接"
          icon={<Link2 className="w-4 h-4" />}
          open={openSections.frida}
          onToggle={() => toggleSection('frida')}
          colors={colors}
          headerRight={
            <HelpHint
              text="默认只列出有可见窗口的进程，避免同名辅助进程干扰。选中后按 PID 连接。用完请断开；空闲约 10 分钟将自动断开，以降低游戏卡顿风险。"
              colors={colors}
              themeMode={themeMode}
            />
          }
        >
          <div className="flex items-center gap-2 text-xs pt-1" style={{ color: colors.secondaryText }}>
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
          <p className="text-xs leading-relaxed opacity-80" style={{ color: colors.secondaryText }}>
            用完请断开；空闲约 10 分钟将自动断开，以降低游戏卡顿风险。
          </p>

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

            <div className="flex items-center gap-2">
              <Checkbox
                id="only-with-window"
                checked={onlyWithWindow}
                onCheckedChange={(v) => setOnlyWithWindow(!!v)}
              />
              <Label
                htmlFor="only-with-window"
                className="text-xs font-normal normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}
              >
                仅显示有窗口的进程
                <HelpHint text="推荐：过滤掉同名后台/辅助进程。" colors={colors} themeMode={themeMode} />
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
              <p
                className="text-xs font-mono leading-relaxed opacity-70 break-all"
                style={{ color: colors.secondaryText }}
              >
                {selected.window_title ? `窗口：${selected.window_title}` : '无窗口标题'}
                {selected.exe ? `\n路径：${selected.exe}` : ''}
              </p>
            )}
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
        </SettingsSection>

        <SettingsSection
          title="窗口与录制"
          icon={<Monitor className="w-4 h-4" />}
          open={openSections.window}
          onToggle={() => toggleSection('window')}
          colors={colors}
        >
          <div className="flex items-center gap-3 pt-1">
            <Checkbox
              id="setting-hide-window"
              checked={hideWindowOnRecord}
              onCheckedChange={(v) => setHideWindowOnRecord(!!v)}
            />
            <Label
              htmlFor="setting-hide-window"
              className="text-sm font-medium normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
              style={{ color: colors.text }}
            >
              <EyeOff className="w-3.5 h-3.5 opacity-70" />
              操作时隐藏主窗口
              <HelpHint
                text={
                  <>
                    开启后，录制、运行、取点、框选时会暂时隐藏 Nexuz，避免点到本程序。
                    <br />
                    录制隐藏时使用屏幕右上角外部「停止录制」浮窗；未隐藏时使用应用内浮层。录制快捷键 X+F10（支持点击/按键/延迟/滚轮，不含拖拽/悬停/打字）。运行中可全局 X+F5 暂停、X+F4 结束。
                  </>
                }
                colors={colors}
                themeMode={themeMode}
              />
            </Label>
          </div>
        </SettingsSection>

        <SettingsSection
          title="快捷键"
          icon={<Keyboard className="w-4 h-4" />}
          open={openSections.shortcuts}
          onToggle={() => toggleSection('shortcuts')}
          colors={colors}
        >
          <div className="space-y-3 pt-1 text-sm" style={{ color: colors.text }}>
            <p className="text-xs opacity-70 leading-relaxed">
              在输入框中打字时，下列画布快捷键不会触发，以免误删或打断输入。
            </p>
            <div className="rounded-lg border px-3 py-2.5 space-y-2" style={{ borderColor: colors.border }}>
              <p className="text-xs font-medium opacity-80">画布与节点</p>
              <ul className="space-y-1.5 text-xs leading-relaxed opacity-90">
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Delete</kbd>
                  {' / '}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Backspace</kbd>
                  ：删除选中节点（支持多选）
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Enter</kbd>
                  {' / '}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">空格</kbd>
                  ：对当前选中节点执行「取点」（仅坐标取点；Frida / 框选 / 截模板无效）
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Ctrl</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">A</kbd>
                  ：全选节点
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Ctrl</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">C</kbd>
                  {' / '}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">V</kbd>
                  ：复制 / 粘贴节点
                </li>
                <li>
                  顶栏「框选」工具，或{' '}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Shift</kbd>
                  +拖动画布空白：框选多个节点
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Ctrl</kbd>
                  +点击：多选 / 取消选中
                </li>
              </ul>
            </div>
            <div className="rounded-lg border px-3 py-2.5 space-y-2" style={{ borderColor: colors.border }}>
              <p className="text-xs font-medium opacity-80">录制与运行（全局）</p>
              <ul className="space-y-1.5 text-xs leading-relaxed opacity-90">
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">X</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">F10</kbd>
                  ：停止录制
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">X</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">F5</kbd>
                  ：运行中暂停 / 继续
                </li>
                <li>
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">X</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">F4</kbd>
                  ：结束运行
                </li>
              </ul>
            </div>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}
