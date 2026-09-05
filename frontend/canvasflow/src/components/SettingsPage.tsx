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
  Globe,
  MousePointer2,
  RefreshCw,
  Save,
  Settings2,
  Trash2,
  Unplug,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Keyboard,
  Puzzle,
  Type,
  Terminal,
  X,
  PanelsTopLeft,
  Sparkles
} from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DEFAULT_HOTKEYS, formatHotkeyLabel, useFlowStore } from '@/store/flowModelStore';
import { bridge } from '@/bridge';
import { useAppDialog } from './AppDialogs';
import { useUpdateDialog } from './UpdateDialog';
import McpTutorialDialog from './McpTutorialDialog';
import PythonScriptEditor from './PythonScriptEditor';
import { starterForFilename } from '../userBlockTemplate';

function eventToHotkeyKey(e: KeyboardEvent): string | null {
  const k = e.key;
  if (k === 'Control') return 'ctrl';
  if (k === 'Shift') return 'shift';
  if (k === 'Alt') return 'alt';
  if (k === 'Meta') return 'win';
  if (/^F\d{1,2}$/i.test(k)) return k.toLowerCase();
  if (k.length === 1) return k.toLowerCase();
  if (e.code?.startsWith('Key')) return e.code.slice(3).toLowerCase();
  return null;
}

/** Capture a global-style combo for settings (e.g. x+f10). */
function HotkeyCaptureField({
  value,
  onChange,
  colors
}: {
  value: string[];
  onChange: (keys: string[]) => void;
  colors: ThemeColors;
}) {
  const [listening, setListening] = useState(false);
  const heldRef = useRef<string[]>([]);
  const display = formatHotkeyLabel(value) || '未设置';

  useEffect(() => {
    if (!listening) return;
    heldRef.current = [];
    const onDown = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const name = eventToHotkeyKey(e);
      if (!name) return;
      if (!heldRef.current.includes(name)) {
        heldRef.current = [...heldRef.current, name];
      }
    };
    const onUp = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (heldRef.current.length) {
        const mods = ['ctrl', 'alt', 'shift', 'win'];
        const ordered = [
          ...mods.filter(m => heldRef.current.includes(m)),
          ...heldRef.current.filter(k => !mods.includes(k))
        ];
        onChange(ordered);
      }
      setListening(false);
    };
    window.addEventListener('keydown', onDown, true);
    window.addEventListener('keyup', onUp, true);
    return () => {
      window.removeEventListener('keydown', onDown, true);
      window.removeEventListener('keyup', onUp, true);
    };
  }, [listening, onChange]);

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <div
        className="w-[6.5rem] h-8 px-2 rounded-md border flex items-center justify-center font-mono text-xs truncate"
        style={{ borderColor: colors.border, backgroundColor: 'rgba(0,0,0,0.04)' }}>
        {listening ? (
          <span className="text-amber-500 animate-pulse text-[11px]">按下…</span>
        ) : (
          <span title={display}>{display}</span>
        )}
      </div>
      <Button
        type="button"
        variant={listening ? 'default' : 'outline'}
        size="sm"
        className="h-8 shrink-0 px-2"
        onClick={() => setListening(v => !v)}
        title="点击后按下新的快捷键组合">
        <Keyboard className="w-3.5 h-3.5" />
        {listening ? '取消' : '改键'}
      </Button>
    </div>
  );
}

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
      v => {
        clearTimeout(t);
        resolve(v);
      },
      e => {
        clearTimeout(t);
        reject(e);
      }
    );
  });
}

/** ? icon — portal tooltip (opaque, not clipped by overflow) */
function HelpHint({
  text,
  colors,
  themeMode
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
      onBlur={hide}>
      <span
        className="inline-flex items-center justify-center w-4 h-4 rounded-full cursor-help opacity-50 hover:opacity-90"
        style={{ color: colors.secondaryText }}
        tabIndex={0}
        aria-label="说明">
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
              boxShadow: themeMode === 'dark' ? '0 10px 32px rgba(0,0,0,0.55)' : '0 10px 32px rgba(0,0,0,0.18)'
            }}>
            {text}
          </div>,
          document.body
        )}
    </span>
  );
}

function SettingsSection({
  id,
  title,
  icon,
  open,
  onToggle,
  colors,
  headerRight,
  children
}: {
  id?: string;
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
      id={id}
      className="rounded-2xl border overflow-hidden"
      style={{ borderColor: colors.border, backgroundColor: colors.surface }}>
      <div className="flex items-center gap-1 pr-2">
        <button
          type="button"
          className="flex-1 min-w-0 flex items-center gap-2 px-4 py-3.5 text-left hover:bg-black/[0.03] dark:hover:bg-white/[0.03]"
          onClick={onToggle}
          aria-expanded={open}>
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
          <div className="shrink-0 flex items-center gap-1" onClick={e => e.stopPropagation()}>
            {headerRight}
          </div>
        ) : null}
      </div>
      {open ? (
        <div className="px-5 pb-5 space-y-4 border-t" style={{ borderColor: colors.border }}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

const SETTINGS_SECTION_IDS = [
  'about',
  'ai',
  'mcp',
  'browser',
  'data',
  'userBlocks',
  'announce',
  'click',
  'frida',
  'window',
  'save',
  'shortcuts',
  'logging'
] as const;

type SectionId = (typeof SETTINGS_SECTION_IDS)[number];

export default function SettingsPage({
  themeName,
  themeMode,
  onClose,
  expandSection
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
  onClose?: () => void;
  /** Open a settings section on mount (e.g. 'ai' for API Key). */
  expandSection?: SectionId;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const { confirm, alert } = useAppDialog();
  const { openUpdate } = useUpdateDialog();
  const hideWindowOnRecord = useFlowStore(s => s.hideWindowOnRecord);
  const setHideWindowOnRecord = useFlowStore(s => s.setHideWindowOnRecord);
  const showToolbarLabels = useFlowStore(s => !!s.showToolbarLabels);
  const setShowToolbarLabels = useFlowStore(s => s.setShowToolbarLabels);
  const nodeContextMenuMode = useFlowStore(s => (s.nodeContextMenuMode === 'flat' ? 'flat' : 'grouped'));
  const setNodeContextMenuMode = useFlowStore(s => s.setNodeContextMenuMode);
  const hideSidePanelsOnSettings = useFlowStore(s => s.hideSidePanelsOnSettings !== false);
  const setHideSidePanelsOnSettings = useFlowStore(s => s.setHideSidePanelsOnSettings);
  const appendAuditLog = useFlowStore(s => s.appendAuditLog);
  const autoSaveEnabled = useFlowStore(s => s.autoSaveEnabled);
  const setAutoSaveEnabled = useFlowStore(s => s.setAutoSaveEnabled);
  const autoSaveIntervalSec = useFlowStore(s => s.autoSaveIntervalSec);
  const setAutoSaveIntervalSec = useFlowStore(s => s.setAutoSaveIntervalSec);
  const saveAfterRun = useFlowStore(s => s.saveAfterRun);
  const setSaveAfterRun = useFlowStore(s => s.setSaveAfterRun);
  const hotkeys = useFlowStore(s => s.hotkeys);
  const setHotkey = useFlowStore(s => s.setHotkey);
  const resetHotkeys = useFlowStore(s => s.resetHotkeys);
  const setSchemas = useFlowStore(s => s.setSchemas);
  const defaultCaptureMode = useFlowStore(s => s.defaultCaptureMode);
  const setDefaultCaptureMode = useFlowStore(s => s.setDefaultCaptureMode);
  const defaultPickMethod = useFlowStore(s => s.defaultPickMethod);
  const setDefaultPickMethod = useFlowStore(s => s.setDefaultPickMethod);
  const defaultCoordinateMode = useFlowStore(s => s.defaultCoordinateMode);
  const setDefaultCoordinateMode = useFlowStore(s => s.setDefaultCoordinateMode);
  const defaultOutputCoordinateMode = useFlowStore(s => s.defaultOutputCoordinateMode);
  const setDefaultOutputCoordinateMode = useFlowStore(s => s.setDefaultOutputCoordinateMode);
  const defaultNodeIntervalMs = useFlowStore(s => s.defaultNodeIntervalMs);
  const setDefaultNodeIntervalMs = useFlowStore(s => s.setDefaultNodeIntervalMs);
  const syncAllPickMethods = useFlowStore(s => s.syncAllPickMethods);
  const syncAllClickCaptureModes = useFlowStore(s => s.syncAllClickCaptureModes);
  const syncAllClickCoordinateModes = useFlowStore(s => s.syncAllClickCoordinateModes);
  const syncAllOutputCoordinateModes = useFlowStore(s => s.syncAllOutputCoordinateModes);
  const flowNodes = useFlowStore(s => s.flow.nodes || {});

  const diagLogging = useFlowStore(s => s.diagLogging);
  const setDiagLogging = useFlowStore(s => s.setDiagLogging);
  const autoCheckUpdate = useFlowStore(s => s.autoCheckUpdate);
  const setAutoCheckUpdate = useFlowStore(s => s.setAutoCheckUpdate);

  type AiPreset = { id: string; label: string; base_url: string; model: string };
  type AiOptionSlot = {
    base_url?: string;
    model?: string;
    api_key?: string;
    has_api_key?: boolean;
    api_key_masked?: string;
  };
  const [aiPreset, setAiPreset] = useState('custom');
  const [aiBaseUrl, setAiBaseUrl] = useState('https://api.openai.com/v1');
  const [aiModel, setAiModel] = useState('gpt-4o-mini');
  const [aiApiKey, setAiApiKey] = useState('');
  const [aiHasKey, setAiHasKey] = useState(false);
  const [aiKeyMasked, setAiKeyMasked] = useState('');
  const [aiPresets, setAiPresets] = useState<AiPreset[]>([]);
  const [aiOptions, setAiOptions] = useState<Record<string, AiOptionSlot>>({});
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState('');
  const [aiDirty, setAiDirty] = useState(false);
  const [aiRemoteModels, setAiRemoteModels] = useState<{ id: string; owned_by?: string }[]>([]);
  const [aiImageRemoteModels, setAiImageRemoteModels] = useState<{ id: string; owned_by?: string }[]>([]);
  const [aiAllowDangerous, setAiAllowDangerous] = useState(false);
  const [aiLlmCache, setAiLlmCache] = useState(true);
  const [aiAllowRunBlock, setAiAllowRunBlock] = useState(false);
  const [aiTab, setAiTab] = useState<'general' | 'image'>('general');
  const [agentCardOpen, setAgentCardOpen] = useState(false);
  const [aiSkills, setAiSkills] = useState<
    { id: string; label?: string; description?: string; enabled?: boolean }[]
  >([]);
  const [aiEvalMsg, setAiEvalMsg] = useState('');
  const [aiAuditEvents, setAiAuditEvents] = useState<{ ts?: string; event?: string; skill?: string }[]>(
    []
  );
  const [aiImageBaseUrl, setAiImageBaseUrl] = useState('');
  const [aiImageModel, setAiImageModel] = useState('');
  const [aiImageApiKey, setAiImageApiKey] = useState('');
  const [aiImageHasKey, setAiImageHasKey] = useState(false);
  const [aiImageKeyMasked, setAiImageKeyMasked] = useState('');
  const [mcpEnabled, setMcpEnabled] = useState(true);
  const [mcpStatus, setMcpStatus] = useState<{
    running?: boolean;
    listen_port?: number | null;
    pid?: number | null;
  } | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [mcpMsg, setMcpMsg] = useState('');
  const [mcpTutorialOpen, setMcpTutorialOpen] = useState(false);

  const refreshAiSkills = useCallback(async () => {
    try {
      const res = await bridge.aiListSkills?.();
      if (res?.ok && Array.isArray(res.skills)) setAiSkills(res.skills);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshAiAudit = useCallback(async () => {
    try {
      const res = await bridge.aiListAudit?.(20);
      if (res?.ok && Array.isArray(res.events)) setAiAuditEvents(res.events);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await bridge.aiGetConfig?.();
        if (cancelled || !res?.ok || !res.config) return;
        const c = res.config;
        const opts =
          c.options && typeof c.options === 'object' ? (c.options as Record<string, AiOptionSlot>) : {};
        const preset = c.preset || 'custom';
        setAiPreset(preset);
        setAiBaseUrl(c.base_url || '');
        setAiModel(c.model || '');
        setAiHasKey(!!c.has_api_key);
        setAiKeyMasked(c.api_key_masked || '');
        setAiApiKey('');
        setAiPresets(Array.isArray(c.presets) ? c.presets : []);
        setAiAllowDangerous(!!c.allow_dangerous);
        setAiLlmCache(c.llm_cache_enabled !== false);
        setAiAllowRunBlock(!!c.allow_run_block);
        setAiImageBaseUrl(c.image_base_url || '');
        setAiImageModel(c.image_model || '');
        setAiImageHasKey(!!c.has_image_api_key);
        setAiImageKeyMasked(c.image_api_key_masked || '');
        setAiImageApiKey('');
        setAiOptions({
          ...opts,
          [preset]: {
            ...(opts[preset] || {}),
            base_url: c.base_url || '',
            model: c.model || '',
            has_api_key: !!c.has_api_key,
            api_key_masked: c.api_key_masked || ''
          }
        });
        setAiDirty(false);
      } catch {
        /* ignore */
      }
      if (!cancelled) {
        await refreshAiSkills();
        await refreshAiAudit();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshAiSkills, refreshAiAudit]);

  const refreshMcpStatus = useCallback(async () => {
    try {
      const res = await bridge.mcpGetStatus?.();
      if (res?.ok) {
        setMcpEnabled(!!res.enabled);
        setMcpStatus(res);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshMcpStatus();
  }, [refreshMcpStatus]);

  const handleToggleMcp = async (enabled: boolean) => {
    setMcpBusy(true);
    try {
      const res = await bridge.mcpSetConfig?.({ enabled });
      if (res?.ok) {
        setMcpEnabled(!!res.config?.enabled);
        setMcpMsg(enabled ? '已启动本地 MCP 服务' : '已停止 MCP 服务，外部 AI 将无法连接');
      } else {
        setMcpMsg(res?.error || '设置失败');
      }
      await refreshMcpStatus();
    } catch (e: any) {
      setMcpMsg(String(e?.message || e || '设置失败'));
    } finally {
      setMcpBusy(false);
    }
  };

  const handleCopyMcpCommand = async () => {
    setMcpBusy(true);
    try {
      const res = await bridge.mcpClientConfig?.();
      if (!res?.ok) {
        setMcpMsg(res?.error || '生成接入命令失败');
        return;
      }
      if (!res.shell_exists) {
        setMcpMsg(`未找到壳进程文件：${res.shell_path}（请将 nexuz_mcp.py 放在程序同目录后重试）`);
        return;
      }
      await navigator.clipboard.writeText(String(res.command || ''));
      setMcpMsg('接入命令已复制，粘贴到终端执行即可注册到 Claude Code');
    } catch (e: any) {
      setMcpMsg(String(e?.message || e || '复制失败'));
    } finally {
      setMcpBusy(false);
    }
  };

  type BrowserConfigShape = {
    engine: string;
    headless: boolean;
    keep_alive: boolean;
    profile_dir: string;
    edge_path: string;
  };

  const [browserCfg, setBrowserCfg] = useState<BrowserConfigShape>({
    engine: 'auto',
    headless: true,
    keep_alive: false,
    profile_dir: '',
    edge_path: ''
  });
  const [browserRunning, setBrowserRunning] = useState(false);
  const [browserEngineLive, setBrowserEngineLive] = useState<string | null>(null);
  const [browserFound, setBrowserFound] = useState(true);
  const [browserBusy, setBrowserBusy] = useState(false);
  const [browserMsg, setBrowserMsg] = useState('');

  const refreshBrowserStatus = useCallback(async () => {
    try {
      const res = await bridge.browserStatus?.();
      if (res?.ok) {
        setBrowserCfg({
          engine: res.config?.engine || 'auto',
          headless: !!res.config?.headless,
          keep_alive: !!res.config?.keep_alive,
          profile_dir: res.config?.profile_dir || '',
          edge_path: res.config?.edge_path || ''
        });
        setBrowserRunning(!!res.running);
        setBrowserEngineLive(res.engine || null);
        setBrowserFound(!!res.browser_found);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshBrowserStatus();
  }, [refreshBrowserStatus]);

  const handleSaveBrowser = async (patch: Partial<BrowserConfigShape>) => {
    setBrowserBusy(true);
    try {
      const res = await bridge.browserSetConfig?.(patch);
      if (res?.ok) {
        setBrowserMsg('已保存（正在运行的浏览器会话会按新配置重建）');
      } else {
        setBrowserMsg(res?.error || '保存失败');
      }
      await refreshBrowserStatus();
    } catch (e: any) {
      setBrowserMsg(String(e?.message || e || '保存失败'));
    } finally {
      setBrowserBusy(false);
    }
  };

  const fetchAiModels = async (
    baseUrl?: string,
    apiKey?: string,
    opts?: { silent?: boolean; target?: 'general' | 'image' }
  ) => {
    const silent = !!opts?.silent;
    const target = opts?.target ?? 'general';
    const isImage = target === 'image';
    const url = (baseUrl ?? (isImage ? aiImageBaseUrl : aiBaseUrl)).trim();
    if (!url) {
      if (!silent) setAiMsg('请先填写 Base URL');
      return;
    }
    if (!silent) {
      setAiBusy(true);
      setAiMsg('正在从网关拉取模型列表…');
    }
    try {
      const res = await bridge.aiListModels?.(
        url,
        (apiKey ?? (isImage ? aiImageApiKey : aiApiKey)).trim(),
        target
      );
      if (!res?.ok) {
        if (isImage) setAiImageRemoteModels([]);
        else setAiRemoteModels([]);
        if (!silent) {
          setAiMsg(res?.error || '拉取模型失败');
        }
        return;
      }
      const models = Array.isArray(res.models) ? res.models : [];
      if (isImage) {
        setAiImageRemoteModels(models);
        if (models.length && !aiImageModel.trim()) {
          setAiImageModel(models[0].id);
          setAiDirty(true);
        }
        if (!silent) {
          setAiMsg(
            models.length
              ? `已拉取 ${models.length} 个生图模型（可在下方选择）`
              : '服务已响应，但未返回任何模型'
          );
        }
        return;
      }
      setAiRemoteModels(models);
      if (models.length && !aiModel.trim()) {
        setAiModel(models[0].id);
        setAiDirty(true);
      }
      if (!silent) {
        setAiMsg(
          models.length
            ? `已拉取 ${models.length} 个模型（可在下方选择）`
            : '服务已响应，但未返回任何模型（请在 LM Studio 中 Load 模型）'
        );
      }
    } catch (e: any) {
      if (isImage) setAiImageRemoteModels([]);
      else setAiRemoteModels([]);
      if (!silent) setAiMsg(String(e?.message || e || '拉取模型失败'));
    } finally {
      if (!silent) setAiBusy(false);
    }
  };

  const stashCurrentAiOption = (presetId: string, options: Record<string, AiOptionSlot>) => {
    const next = { ...options };
    const prev = next[presetId] || {};
    next[presetId] = {
      ...prev,
      base_url: aiBaseUrl,
      model: aiModel,
      has_api_key: !!aiApiKey.trim() || !!aiHasKey || !!prev.has_api_key,
      api_key_masked: aiKeyMasked || prev.api_key_masked || '',
      ...(aiApiKey.trim() ? { api_key: aiApiKey.trim() } : {})
    };
    return next;
  };

  const applyAiPreset = (presetId: string) => {
    if (presetId === aiPreset) return;
    const stashed = stashCurrentAiOption(aiPreset, aiOptions);
    const saved = stashed[presetId];
    const found = aiPresets.find(p => p.id === presetId);
    let nextUrl = saved?.base_url ?? '';
    let nextModel = saved?.model ?? '';
    if (!saved) {
      if (found && presetId !== 'custom') {
        nextUrl = found.base_url || '';
        nextModel = found.model || (presetId === 'lmstudio' ? '' : '');
      } else {
        nextUrl = aiBaseUrl;
        nextModel = aiModel;
      }
    }
    setAiOptions(stashed);
    setAiPreset(presetId);
    setAiBaseUrl(nextUrl);
    setAiModel(nextModel);
    setAiHasKey(!!saved?.has_api_key);
    setAiKeyMasked(saved?.api_key_masked || '');
    setAiApiKey(saved?.api_key || '');
    setAiDirty(true);
    // Local OpenAI-compat servers: auto-discover loaded models
    if (presetId === 'lmstudio' || presetId === 'ollama') {
      void fetchAiModels(nextUrl, saved?.api_key || '');
    }
  };

  const handleSaveAiConfig = async () => {
    if (aiBusy) return;
    setAiBusy(true);
    setAiMsg('正在保存…');
    try {
      const stashed = stashCurrentAiOption(aiPreset, aiOptions);
      const optionsPayload: Record<string, Record<string, string>> = {};
      for (const [pid, slot] of Object.entries(stashed)) {
        const item: Record<string, string> = {
          base_url: String(slot.base_url || '').trim(),
          model: String(slot.model || '').trim()
        };
        if (slot.api_key && String(slot.api_key).trim()) {
          item.api_key = String(slot.api_key).trim();
        }
        optionsPayload[pid] = item;
      }
      const patch: Record<string, unknown> = {
        enabled: true,
        provider: 'openai_compat',
        preset: aiPreset,
        base_url: aiBaseUrl.trim(),
        model: aiModel.trim(),
        allow_dangerous: aiAllowDangerous,
        llm_cache_enabled: aiLlmCache,
        allow_run_block: aiAllowRunBlock,
        keep_existing_key: true,
        options: optionsPayload
      };
      if (aiApiKey.trim()) {
        patch.api_key = aiApiKey.trim();
      }
      patch.image_base_url = aiImageBaseUrl.trim();
      patch.image_model = aiImageModel.trim();
      if (aiImageApiKey.trim()) {
        patch.image_api_key = aiImageApiKey.trim();
      }
      const res = await bridge.aiSetConfig(patch);
      if (!res?.ok) {
        setAiMsg(res?.error || '保存失败');
        return;
      }
      const c = res.config || {};
      const opts =
        c.options && typeof c.options === 'object' ? (c.options as Record<string, AiOptionSlot>) : {};
      setAiPreset(c.preset || aiPreset);
      setAiBaseUrl(c.base_url || aiBaseUrl);
      setAiModel(c.model || aiModel);
      setAiHasKey(!!c.has_api_key);
      setAiKeyMasked(c.api_key_masked || '');
      setAiApiKey('');
      setAiImageBaseUrl(c.image_base_url || '');
      setAiImageModel(c.image_model || '');
      setAiImageHasKey(!!c.has_image_api_key);
      setAiImageKeyMasked(c.image_api_key_masked || '');
      setAiImageApiKey('');
      setAiOptions(opts);
      setAiDirty(false);
      setAiMsg('已保存（含各厂商选项）');
      appendAuditLog?.('已更新 Nexuz Ai 配置', { preset: c.preset, model: c.model });
      try {
        window.dispatchEvent(new CustomEvent('nexuz-ai-config-changed', { detail: c }));
      } catch {
        /* ignore */
      }
    } catch (e: any) {
      setAiMsg(String(e?.message || e || '保存失败'));
    } finally {
      setAiBusy(false);
    }
  };

  const handleTestAiConnection = async (target: 'general' | 'image' = 'general') => {
    if (aiBusy) return;
    const isImage = target === 'image';
    // 生图测试可带未保存的输入（显式传参）；聊天测试走已保存配置。
    if (!isImage && aiDirty) {
      setAiMsg('请先保存配置再测试连接');
      return;
    }
    setAiBusy(true);
    setAiMsg(isImage ? '正在测试生图网关…' : '正在测试连接…');
    try {
      if (isImage) {
        const res = await bridge.aiTestConnection?.(
          'image',
          aiImageBaseUrl.trim(),
          aiImageApiKey.trim(),
          aiImageModel.trim()
        );
        if (!res?.ok) {
          setAiMsg(res?.error || '生图网关连接失败');
          return;
        }
        const bits = [`网关可达（${Number(res.models_count) || 0} 个模型）`];
        if (res.model) {
          bits.push(
            `模型 ${res.model}${res.model_found ? '✓' : '（未在网关列表中，部分网关不列出图像模型，仍可保存使用）'}`
          );
        } else {
          bits.push('尚未填写生图模型 ID');
        }
        setAiMsg(bits.join(' · '));
        return;
      }
      const res = await bridge.aiTestConnection();
      if (!res?.ok) {
        setAiMsg(res?.error || '连接失败');
        return;
      }
      const bits = [`连接成功（模型 ${res.model || aiModel}）`];
      if (typeof res.supports_structured === 'boolean') {
        bits.push(res.supports_structured ? '结构化✓' : '结构化✗');
      }
      if (typeof res.supports_vision === 'boolean') {
        bits.push(res.supports_vision ? '多模态✓' : '纯文本通路');
      }
      if (res.hint) bits.push(String(res.hint));
      setAiMsg(bits.join(' · '));
    } catch (e: any) {
      setAiMsg(String(e?.message || e || '连接失败'));
    } finally {
      setAiBusy(false);
    }
  };

  const handleDiagLoggingChange = async (enabled: boolean) => {
    setDiagLogging(enabled);
    try {
      await bridge.setDiagLogging?.(enabled);
    } catch {
      /* ignore */
    }
    appendAuditLog?.(enabled ? '已开启诊断日志' : '已关闭诊断日志', { diag: enabled });
  };

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
        confirmText: '全部修改'
      });
      if (!ok) return;
      syncAllClickCaptureModes(mode);
    }

    setDefaultCaptureMode(mode);
    appendAuditLog?.(`修改默认点击录入模式 → ${mode === 'frida_ui' ? 'Frida UI' : '坐标'}`, {
      defaultCaptureMode: mode
    });
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
        confirmText: '全部修改'
      });
      if (!ok) return;
      syncAllPickMethods(method);
    }

    setDefaultPickMethod(method);
    appendAuditLog?.(`修改默认取点方式 → ${method === 'live' ? '实地取点' : '截图取点'}`, {
      defaultPickMethod: method
    });
  };

  const handleDefaultCoordinateModeChange = async (next: string) => {
    const mode = next === 'window_client' || next === 'virtual_norm' ? next : 'screen_abs';
    if (mode === defaultCoordinateMode) return;

    const differing = Object.values(flowNodes).filter((n: any) => {
      if (n?.type !== 'click' || (n.params?.capture_mode || 'coord') !== 'coord') return false;
      const cur = n.params?.coord?.coordinate_mode || n.params?.coordinate_mode || defaultCoordinateMode;
      return cur !== mode;
    });

    if (differing.length > 0) {
      const labels: Record<string, string> = {
        screen_abs: '屏幕绝对坐标',
        window_client: '目标窗口相对',
        virtual_norm: '虚拟桌面比例'
      };
      const ok = await confirm({
        title: '修改默认坐标基准',
        description: `当前有 ${differing.length} 个坐标点击节点的坐标基准与「${labels[mode]}」不同。确认后将把这些节点全部改为「${labels[mode]}」，之后新建点击节点也会默认选中此基准。`,
        confirmText: '全部修改'
      });
      if (!ok) return;
      syncAllClickCoordinateModes(mode);
    }

    setDefaultCoordinateMode(mode);
    appendAuditLog?.(`修改默认坐标基准 → ${mode}`, { defaultCoordinateMode: mode });
  };

  const handleDefaultOutputCoordinateModeChange = async (next: string) => {
    const mode =
      next === 'region_rel' || next === 'window_client' || next === 'screen_abs'
        ? next
        : 'window_client';
    if (mode === defaultOutputCoordinateMode) return;

    const differing = Object.values(flowNodes).filter((n: any) => {
      if (n?.type !== 'ocr_recognize' && n?.type !== 'find_image') return false;
      const cur = n.params?.output_coordinate_mode || defaultOutputCoordinateMode || 'window_client';
      return cur !== mode;
    });

    if (differing.length > 0) {
      const labels: Record<string, string> = {
        screen_abs: '屏幕绝对',
        region_rel: '区域相对',
        window_client: '目标窗口相对',
      };
      const ok = await confirm({
        title: '修改默认输出坐标',
        description: `当前有 ${differing.length} 个识别节点（OCR / 找图）的输出坐标与「${labels[mode]}」不同。确认后将把这些节点全部改为「${labels[mode]}」，之后新建识别节点也会默认选中此方式。`,
        confirmText: '全部修改'
      });
      if (!ok) return;
      syncAllOutputCoordinateModes(mode);
    }

    setDefaultOutputCoordinateMode(mode);
    appendAuditLog?.(`修改默认输出坐标 → ${mode}`, { defaultOutputCoordinateMode: mode });
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

  const [userBlocksPath, setUserBlocksPath] = useState('');
  const [userBlocksBusy, setUserBlocksBusy] = useState(false);
  const [userBlocksMsg, setUserBlocksMsg] = useState('');
  const [userBlockFiles, setUserBlockFiles] = useState<
    { name: string; path?: string; trusted?: boolean; sha256?: string }[]
  >([]);
  const [userBlockFile, setUserBlockFile] = useState('');
  const [userBlockCode, setUserBlockCode] = useState('');
  const [userBlockDirty, setUserBlockDirty] = useState(false);
  const [newBlockName, setNewBlockName] = useState('');

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

  const refreshUserBlocksDir = useCallback(async () => {
    try {
      const info = await bridge.getUserBlocksDir();
      if (info?.ok) {
        setUserBlocksPath(String(info.path || ''));
      }
    } catch {
      /* ignore */
    }
  }, []);

  const refreshUserBlockFiles = useCallback(
    async (preferName?: string) => {
      try {
        const res = await bridge.listUserBlockFiles();
        if (!res?.ok) return;
        const files = Array.isArray(res.files) ? res.files : [];
        setUserBlockFiles(files);
        if (res.path) setUserBlocksPath(String(res.path));
        const names = files.map((f: any) => String(f.name || ''));
        const pick =
          (preferName && names.includes(preferName) && preferName) ||
          (userBlockFile && names.includes(userBlockFile) && userBlockFile) ||
          names[0] ||
          '';
        if (pick && pick !== userBlockFile) {
          setUserBlockFile(pick);
        } else if (!pick) {
          setUserBlockFile('');
          setUserBlockCode('');
          setUserBlockDirty(false);
        }
      } catch {
        /* ignore */
      }
    },
    [userBlockFile]
  );

  const loadUserBlockFile = useCallback(async (name: string) => {
    if (!name) {
      setUserBlockCode('');
      setUserBlockDirty(false);
      return;
    }
    setUserBlocksBusy(true);
    try {
      const res = await bridge.readUserBlockFile(name);
      if (res?.ok) {
        setUserBlockCode(String(res.content ?? ''));
        setUserBlockDirty(false);
        setUserBlocksMsg('');
      } else {
        setUserBlocksMsg(res?.error || '读取失败');
      }
    } catch (e: any) {
      setUserBlocksMsg(String(e?.message || e));
    } finally {
      setUserBlocksBusy(false);
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
      const res = await withTimeout(bridge.fridaListProcesses(null, flag), 20000, '刷新进程列表');
      if (seq !== listSeq.current) return;
      if (res?.ok && Array.isArray(res.processes)) {
        const slim = res.processes.slice(0, 500).map((p: ProcRow) => ({
          pid: p.pid,
          name: p.name,
          window_title: p.window_title,
          exe_base: p.exe_base,
          display: p.display
        }));
        setProcesses(slim);
        setSelectedKey(prev => {
          if (!prev) return prev;
          const pid = Number(prev.split('|')[0]);
          return slim.some((p: ProcRow) => p.pid === pid) ? prev : '';
        });
        setFridaMsg(m => (m.startsWith('无法枚举') || m.includes('枚举进程') ? '' : m));
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
    void refreshUserBlocksDir();
    void refreshUserBlockFiles();
  }, [loadAbout, loadAnnouncement, refreshDataDir, refreshUserBlocksDir, refreshUserBlockFiles]);

  useEffect(() => {
    if (userBlockFile) void loadUserBlockFile(userBlockFile);
  }, [userBlockFile, loadUserBlockFile]);

  const handleOpenUserBlocksDir = async () => {
    setUserBlocksBusy(true);
    setUserBlocksMsg('');
    try {
      const res = await bridge.openUserBlocksDir();
      if (!res?.ok) setUserBlocksMsg(res?.error || '无法打开用户积木目录');
      else {
        await refreshUserBlocksDir();
        await refreshUserBlockFiles(userBlockFile);
      }
    } catch (e: any) {
      setUserBlocksMsg(String(e?.message || e));
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const handleRefreshUserBlocks = async () => {
    setUserBlocksBusy(true);
    setUserBlocksMsg('');
    try {
      await refreshUserBlockFiles(userBlockFile);
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) {
        setSchemas(list);
        const customCount = list.filter((s: any) => (s?.category || '') === '自定义').length;
        setUserBlocksMsg(`已刷新积木列表（自定义 ${customCount} 个）`);
      } else {
        setUserBlocksMsg('刷新失败：注册表无效');
      }
      await refreshUserBlocksDir();
    } catch (e: any) {
      setUserBlocksMsg(String(e?.message || e));
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const handleSaveUserBlock = async () => {
    if (!userBlockFile) {
      setUserBlocksMsg('请先选择或新建文件');
      return;
    }
    setUserBlocksBusy(true);
    setUserBlocksMsg('');
    try {
      const res = await bridge.writeUserBlockFile(userBlockFile, userBlockCode);
      if (!res?.ok) {
        setUserBlocksMsg(res?.error || '保存失败');
        return;
      }
      setUserBlockDirty(false);
      await refreshUserBlockFiles(userBlockFile);
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) setSchemas(list);
      setUserBlocksMsg(`已保存 ${userBlockFile}，并刷新积木列表`);
    } catch (e: any) {
      setUserBlocksMsg(String(e?.message || e));
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const handleTrustUserBlock = async () => {
    if (!userBlockFile) return;
    const selectedFile = userBlockFiles.find(file => file.name === userBlockFile);
    const ok = await confirm({
      title: '授权此用户积木？',
      description:
        `文件：${userBlockFile}\nSHA-256：${selectedFile?.sha256 || '未知'}\n\n` +
        '授权后，模块顶层代码与 handler 可在隔离 worker 中运行。worker 阻断网络和子进程，允许本地文件读写（图片处理类积木需要落盘产出），但仍可读取当前用户文件。仅在你已审查全部代码并信任来源时继续。',
      confirmText: '我已审查并授权',
      destructive: true
    });
    if (!ok) return;
    setUserBlocksBusy(true);
    try {
      const res = await bridge.trustUserBlockFile(userBlockFile);
      if (!res?.ok) {
        setUserBlocksMsg(res?.error || '授权失败');
        return;
      }
      await refreshUserBlockFiles(userBlockFile);
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) setSchemas(list);
      setUserBlocksMsg(`已授权 ${userBlockFile} · ${String(res.sha256 || '').slice(0, 12)}…`);
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const handleRevokeUserBlock = async () => {
    if (!userBlockFile) return;
    setUserBlocksBusy(true);
    try {
      const res = await bridge.revokeUserBlockFile(userBlockFile);
      if (!res?.ok) {
        setUserBlocksMsg(res?.error || '撤销授权失败');
        return;
      }
      await refreshUserBlockFiles(userBlockFile);
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) setSchemas(list);
      setUserBlocksMsg(`已停用 ${userBlockFile}`);
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const handleCreateUserBlock = async () => {
    let name = String(newBlockName || '').trim();
    if (!name) {
      setUserBlocksMsg('请输入新文件名，如 my_block.py');
      return;
    }
    if (!name.toLowerCase().endsWith('.py')) name = `${name}.py`;
    if (!/^[A-Za-z0-9_\-]+\.py$/.test(name) || name.startsWith('_')) {
      setUserBlocksMsg('文件名仅允许字母数字_-，且不能以下划线开头');
      return;
    }
    if (userBlockDirty) {
      const ok = await confirm({
        title: '放弃未保存更改？',
        description: '当前文件有未保存修改，新建将丢弃这些更改。',
        confirmText: '继续新建',
        destructive: true
      });
      if (!ok) return;
    }
    const starter = starterForFilename(name);
    setUserBlocksBusy(true);
    try {
      const res = await bridge.writeUserBlockFile(name, starter);
      if (!res?.ok) {
        setUserBlocksMsg(res?.error || '创建失败');
        return;
      }
      setNewBlockName('');
      await refreshUserBlockFiles(name);
      setUserBlockFile(name);
      setUserBlockCode(starter);
      setUserBlockDirty(false);
      const list = await bridge.getBlockRegistry();
      if (Array.isArray(list)) setSchemas(list);
      setUserBlocksMsg(`已创建 ${name}`);
    } catch (e: any) {
      setUserBlocksMsg(String(e?.message || e));
    } finally {
      setUserBlocksBusy(false);
    }
  };

  const selectedUserBlockMeta = useMemo(
    () => userBlockFiles.find(file => file.name === userBlockFile) || null,
    [userBlockFiles, userBlockFile]
  );

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
      confirmText: '恢复默认'
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

  const handleExportDataPack = async () => {
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const res = await bridge.exportDataPack();
      if (res?.cancelled) return;
      setDataDirMsg(res?.ok ? `数据包已导出：${res.path}` : res?.error || '导出失败');
    } catch (e: any) {
      setDataDirMsg(String(e?.message || e));
    } finally {
      setDataDirBusy(false);
    }
  };

  const handleRestoreDataPack = async () => {
    setDataDirBusy(true);
    setDataDirMsg('');
    try {
      const preview = await bridge.previewImportDataPack();
      if (preview?.cancelled) return;
      if (!preview?.ok) {
        setDataDirMsg(preview?.error || '无法读取数据包');
        return;
      }
      const ok = await confirm({
        title: '恢复 Nexuz 数据包',
        description: `将恢复 ${preview.file_count || 0} 个用户文件。现有数据会先自动备份，API Key 不会从数据包导入。是否继续？`,
        confirmText: '备份并恢复',
        destructive: true
      });
      if (!ok) return;
      const res = await bridge.commitImportDataPack(preview.import_token);
      setDataDirMsg(
        res?.ok
          ? `恢复完成，原数据备份于：${res.backup_path}。建议重启应用。`
          : res?.error || '恢复失败'
      );
      if (res?.ok) await refreshDataDir();
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
      destructive: true
    });
    if (!ok) return;
    const ok2 = await confirm({
      title: '再次确认',
      description: '确定要删除整个数据目录吗？',
      confirmText: '确定删除',
      destructive: true
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
      destructive: true
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
    return processes.filter(p => {
      const hay = [p.name, String(p.pid), p.window_title || '', p.exe || '', p.exe_base || '', p.display || '']
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [processes, processFilter]);

  const selected = useMemo(() => {
    if (!selectedKey || selectedKey === '__empty') return null;
    const pid = Number(selectedKey.split('|')[0]);
    return processes.find(p => p.pid === pid) || null;
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
      const res = await withTimeout(bridge.fridaAttach(selected.name, selected.pid), 45000, '连接进程');
      const ok = res?.ok === true;
      if (ok && res?.attached !== false) {
        if (res.hooked) {
          setFridaMsg(
            `连接成功：${res.process_name || selected.name}${res.pid ? ` (PID ${res.pid})` : ''} · Hook 就绪`
          );
        } else {
          const warn = res.warning || res.last_error || 'UI Hook 未就绪';
          setFridaMsg(
            `连接成功：${res.process_name || selected.name}${res.pid ? ` (PID ${res.pid})` : ''} · Hook 未就绪：${warn}`
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
  };

  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>(
    () =>
      Object.fromEntries(
        SETTINGS_SECTION_IDS.map(id => [id, expandSection === id])
      ) as Record<SectionId, boolean>
  );
  const toggleSection = (id: SectionId) => {
    setOpenSections(prev => ({ ...prev, [id]: !prev[id] }));
  };

  useEffect(() => {
    if (!expandSection) return;
    setOpenSections(prev => ({ ...prev, [expandSection]: true }));
    const t = window.setTimeout(() => {
      document.getElementById(`settings-section-${expandSection}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }, 80);
    return () => window.clearTimeout(t);
  }, [expandSection]);

  return (
    <div className="flex-1 min-w-0 h-full overflow-auto">
      <div
        className="w-full max-w-none px-6 py-8 space-y-3"
        style={hideSidePanelsOnSettings ? undefined : { paddingLeft: '3rem', paddingRight: '3rem' }}>
        <div className="flex items-center gap-2 mb-5">
          <Settings2 style={{ color: colors.primary }} className="w-5 h-5" />
          <h1 className="font-display text-xl font-semibold" style={{ color: colors.text }}>
            设置
          </h1>
          <HelpHint text="全局偏好，保存在本机，与当前流程无关。" colors={colors} themeMode={themeMode} />
          {onClose ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 ml-auto shrink-0 opacity-70 hover:opacity-100"
              onClick={onClose}
              title="关闭设置"
              aria-label="关闭设置">
              <X className="w-4 h-4" />
            </Button>
          ) : null}
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
              title="打开 GitHub Releases">
              <ExternalLink className="w-3.5 h-3.5" />
              Releases
            </Button>
          }>
          <p className="text-sm pt-1" style={{ color: colors.text }}>
            当前版本 <span className="font-mono font-medium">{appVersion || '…'}</span>
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
              onCheckedChange={v => handleAutoCheckChange(v === true)}
            />
            <Label
              htmlFor="auto-check-update"
              className="text-sm cursor-pointer inline-flex items-center gap-1.5"
              style={{ color: colors.text }}>
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
          id="settings-section-ai"
          title="Nexuz Ai"
          icon={<Sparkles className="w-4 h-4" />}
          open={openSections.ai}
          onToggle={() => toggleSection('ai')}
          colors={colors}
          headerRight={
            <HelpHint
              text="API Key 仅保存在本机。支持 OpenAI 兼容网关（DeepSeek、通义、Ollama、LM Studio 等）。选 LM Studio 会自动拉取本机已加载模型；本地服务 API Key 可留空。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <Tabs value={aiTab} onValueChange={v => setAiTab(v as 'general' | 'image')}>
            <TabsList>
              <TabsTrigger value="general">通用模型 / Agent</TabsTrigger>
              <TabsTrigger value="image">生图模型</TabsTrigger>
            </TabsList>

            <TabsContent value="general" className="space-y-3 mt-2">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                厂商预设
              </Label>
              <Select value={aiPreset || 'custom'} onValueChange={v => applyAiPreset(v)}>
                <SelectTrigger className="h-9">
                  <SelectValue placeholder="选择预设" />
                </SelectTrigger>
                <SelectContent>
                  {(aiPresets.length
                    ? aiPresets
                    : [
                        { id: 'openai', label: 'OpenAI' },
                        { id: 'deepseek', label: 'DeepSeek' },
                        { id: 'lmstudio', label: 'LM Studio' },
                        { id: 'ollama', label: 'Ollama' },
                        { id: 'custom', label: '自定义' }
                      ]
                  ).map(p => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                模型
              </Label>
              {aiRemoteModels.length > 0 ? (
                <Select
                  value={aiModel || aiRemoteModels[0]?.id}
                  onValueChange={v => {
                    setAiModel(v);
                    setAiDirty(true);
                  }}>
                  <SelectTrigger className="h-9 font-mono text-xs">
                    <SelectValue placeholder="选择已拉取的模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {aiRemoteModels.map(m => (
                      <SelectItem key={m.id} value={m.id} className="font-mono text-xs">
                        {m.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={aiModel}
                  onChange={e => {
                    setAiModel(e.target.value);
                    setAiDirty(true);
                  }}
                  placeholder="如 qwen2.5-7b / gpt-4o-mini"
                  className="h-9 font-mono text-xs"
                />
              )}
            </div>
          </div>

          {aiRemoteModels.length > 0 ? (
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                或手动填写模型 ID
              </Label>
              <Input
                value={aiModel}
                onChange={e => {
                  setAiModel(e.target.value);
                  setAiDirty(true);
                }}
                placeholder="可覆盖上方选择"
                className="h-9 font-mono text-xs"
              />
            </div>
          ) : null}

          <div className="space-y-1.5">
            <Label className="text-xs opacity-70" style={{ color: colors.text }}>
              Base URL
            </Label>
            <Input
              value={aiBaseUrl}
              onChange={e => {
                setAiBaseUrl(e.target.value);
                setAiDirty(true);
              }}
              placeholder="http://127.0.0.1:1234/v1"
              className="h-9 font-mono text-xs"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs opacity-70" style={{ color: colors.text }}>
              API Key
            </Label>
            <Input
              type="password"
              value={aiApiKey}
              onChange={e => {
                setAiApiKey(e.target.value);
                setAiDirty(true);
              }}
              placeholder={
                aiHasKey
                  ? `已保存 ${aiKeyMasked || '****'}（留空则保持不变）`
                  : aiPreset === 'lmstudio' || aiPreset === 'ollama'
                    ? '本地服务可留空'
                    : '粘贴厂商 API Key'
              }
              className="h-9 font-mono text-xs"
              autoComplete="off"
            />
          </div>

          <div
            className="rounded-xl border px-3 py-2.5 mt-1"
            style={{ borderColor: colors.border }}>
            <button
              type="button"
              className="w-full flex items-center justify-between gap-2 cursor-pointer bg-transparent border-0 p-0"
              onClick={() => setAgentCardOpen(o => !o)}>
              <p className="text-xs font-medium" style={{ color: colors.text }}>
                Agent 平台（策略 / 技能 / 评测）
              </p>
              <ChevronDown
                className={`w-3.5 h-3.5 shrink-0 transition-transform ${agentCardOpen ? '' : '-rotate-90'}`}
                style={{ color: colors.secondaryText }}
              />
            </button>
            {agentCardOpen ? (
            <div className="space-y-2 mt-2">
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox
                checked={aiAllowDangerous}
                onCheckedChange={v => {
                  setAiAllowDangerous(!!v);
                  setAiDirty(true);
                }}
              />
              允许高危积木（run_command / python_script / file_io，默认关）
            </label>
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox
                checked={aiAllowRunBlock}
                onCheckedChange={v => {
                  setAiAllowRunBlock(!!v);
                  setAiDirty(true);
                }}
              />
              允许 AI 实时执行积木（run_block；动作类仍需高危开关，默认关）
            </label>
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox
                checked={aiLlmCache}
                onCheckedChange={v => {
                  setAiLlmCache(!!v);
                  setAiDirty(true);
                }}
              />
              AI 结果缓存（结构化阶段 / 生图 / 识图命名，默认开）
            </label>
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {aiSkills.length === 0 ? (
                <p className="text-[11px]" style={{ color: colors.secondaryText }}>
                  暂无技能包（或未加载）
                </p>
              ) : (
                aiSkills.map(sk => (
                  <label
                    key={sk.id}
                    className="flex items-start gap-2 text-xs"
                    style={{ color: colors.text }}>
                    <Checkbox
                      checked={sk.enabled !== false}
                      onCheckedChange={async v => {
                        const enabled = !!v;
                        try {
                          const res = await bridge.aiSetSkillEnabled?.(sk.id, enabled);
                          if (res?.ok && Array.isArray(res.skills)) setAiSkills(res.skills);
                          else await refreshAiSkills();
                        } catch {
                          /* ignore */
                        }
                      }}
                    />
                    <span>
                      <span className="font-medium">{sk.label || sk.id}</span>
                      {sk.description ? (
                        <span className="block opacity-60">{sk.description}</span>
                      ) : null}
                    </span>
                  </label>
                ))
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={aiBusy}
                onClick={async () => {
                  setAiBusy(true);
                  setAiEvalMsg('正在跑 mock 评测…');
                  try {
                    const res = await bridge.aiRunEval?.();
                    if (!res?.ok) {
                      setAiEvalMsg(res?.error || '评测失败');
                      return;
                    }
                    const pct = Math.round((Number(res.pass_rate) || 0) * 1000) / 10;
                    setAiEvalMsg(`通过 ${res.passed}/${res.total}（${pct}%）`);
                  } catch (e: any) {
                    setAiEvalMsg(String(e?.message || e || '评测失败'));
                  } finally {
                    setAiBusy(false);
                  }
                }}>
                跑评测集
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={aiBusy}
                onClick={() => void refreshAiAudit()}>
                刷新审计
              </Button>
            </div>
            {aiEvalMsg ? (
              <p className="text-xs" style={{ color: colors.secondaryText }}>
                {aiEvalMsg}
              </p>
            ) : null}
            {aiAuditEvents.length > 0 ? (
              <div className="space-y-1 max-h-28 overflow-y-auto font-mono text-[10px] opacity-80">
                {aiAuditEvents.slice(0, 8).map((ev, i) => (
                  <div key={`${ev.ts || i}-${ev.event || ''}`}>
                    {(ev.ts || '').slice(0, 19)} · {ev.event || 'event'}
                    {ev.skill ? ` · ${ev.skill}` : ''}
                  </div>
                ))}
              </div>
            ) : null}
            </div>
            ) : null}
          </div>
            </TabsContent>

            <TabsContent value="image" className="space-y-2 mt-2">
          <div
            className="rounded-xl border px-3 py-2.5 space-y-2 mt-1"
            style={{ borderColor: colors.border }}>
            <p className="text-xs font-medium" style={{ color: colors.text }}>
              生图模型（AI 生图积木）
            </p>
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                模型 ID
              </Label>
              {aiImageRemoteModels.length > 0 ? (
                <Select
                  value={aiImageModel || aiImageRemoteModels[0]?.id}
                  onValueChange={v => {
                    setAiImageModel(v);
                    setAiDirty(true);
                  }}>
                  <SelectTrigger className="h-9 font-mono text-xs">
                    <SelectValue placeholder="选择已拉取的模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {aiImageRemoteModels.map(m => (
                      <SelectItem key={m.id} value={m.id} className="font-mono text-xs">
                        {m.id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={aiImageModel}
                  onChange={e => {
                    setAiImageModel(e.target.value);
                    setAiDirty(true);
                  }}
                  placeholder="如 cogview-4 / dall-e-3 / Kolors"
                  className="h-9 font-mono text-xs"
                />
              )}
            </div>
            {aiImageRemoteModels.length > 0 ? (
              <div className="space-y-1.5">
                <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                  或手动填写模型 ID
                </Label>
                <Input
                  value={aiImageModel}
                  onChange={e => {
                    setAiImageModel(e.target.value);
                    setAiDirty(true);
                  }}
                  placeholder="可覆盖上方选择"
                  className="h-9 font-mono text-xs"
                />
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                Base URL
              </Label>
              <Input
                value={aiImageBaseUrl}
                onChange={e => {
                  setAiImageBaseUrl(e.target.value);
                  setAiDirty(true);
                }}
                placeholder="留空则沿用「通用模型」页的 Base URL"
                className="h-9 font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs opacity-70" style={{ color: colors.text }}>
                API Key
              </Label>
              <Input
                type="password"
                value={aiImageApiKey}
                onChange={e => {
                  setAiImageApiKey(e.target.value);
                  setAiDirty(true);
                }}
                placeholder={
                  aiImageHasKey
                    ? `已保存 ${aiImageKeyMasked || '****'}（留空则保持不变）`
                    : '留空则沿用「通用模型」页的 API Key'
                }
                className="h-9 font-mono text-xs"
                autoComplete="off"
              />
            </div>
            <p className="text-[11px]" style={{ color: colors.secondaryText }}>
              走 OpenAI 兼容 /images/generations 接口；同厂商生图只需填模型 ID。
            </p>
          </div>
            </TabsContent>

            <div className="flex flex-wrap items-center gap-2 mt-2">
              <Button type="button" size="sm" disabled={aiBusy} onClick={() => void handleSaveAiConfig()}>
                保存
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={aiBusy}
                onClick={() => void fetchAiModels(undefined, undefined, { target: aiTab })}>
                拉取模型
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={aiBusy}
                onClick={() => void handleTestAiConnection(aiTab)}>
                测试连接
              </Button>
              {aiDirty ? (
                <span className="text-xs text-amber-600 dark:text-amber-400">有未保存的更改</span>
              ) : null}
            </div>
            {aiMsg ? (
              <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
                {aiMsg}
              </p>
            ) : null}
          </Tabs>
        </SettingsSection>

        <SettingsSection
          title="MCP / 外部 AI"
          icon={<Link2 className="w-4 h-4" />}
          open={openSections.mcp}
          onToggle={() => toggleSection('mcp')}
          colors={colors}
          headerRight={
            <HelpHint
              text="通过 MCP 协议把 Nexuz 积木能力开放给本机 AI 编码代理（Claude Code / zcode 等）。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div className="rounded-xl border px-3 py-2.5 space-y-2 mt-1" style={{ borderColor: colors.border }}>
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox checked={mcpEnabled} onCheckedChange={v => void handleToggleMcp(!!v)} />
              允许本地 MCP 服务（仅 127.0.0.1 + 每次启动随机令牌，默认开）
            </label>
            <p className="text-[11px]" style={{ color: colors.secondaryText }}>
              {mcpStatus?.running
                ? `运行中 · 端口 ${mcpStatus.listen_port} · 进程 ${mcpStatus.pid}`
                : '已停止（外部 AI 无法连接）'}
            </p>
            <p className="text-[11px]" style={{ color: colors.secondaryText }}>
              外部 AI 的积木执行不受「Nexuz AI」页开关约束（授权由所接入的 AI 客户端负责）；
              python_script / run_command / 自定义积木 / 电源操作始终不可由外部 AI 执行（含子流程与定时再触发）。
              所有调用写入审计日志。
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={mcpBusy}
                onClick={() => void handleCopyMcpCommand()}>
                复制接入命令
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => setMcpTutorialOpen(true)}>
                接入教程
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={mcpBusy}
                onClick={() => void refreshMcpStatus()}>
                <RefreshCw className="w-3.5 h-3.5" />
                刷新状态
              </Button>
            </div>
            {mcpMsg ? (
              <p className="text-xs" style={{ color: colors.secondaryText }}>
                {mcpMsg}
              </p>
            ) : null}
          </div>
          <McpTutorialDialog open={mcpTutorialOpen} onOpenChange={setMcpTutorialOpen} colors={colors} />
        </SettingsSection>

        <SettingsSection
          title="浏览器引擎"
          icon={<Globe className="w-4 h-4" />}
          open={openSections.browser}
          onToggle={() => toggleSection('browser')}
          colors={colors}
          headerRight={
            <HelpHint
              text="浏览器积木（导航/提取/点击等）使用的引擎：默认驱动本机 Edge（CDP），独立隔离 profile，不影响日常浏览器。安装 DrissionPage 后可选 drission 引擎。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div className="rounded-xl border px-3 py-2.5 space-y-2 mt-1" style={{ borderColor: colors.border }}>
            <div className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <span className="shrink-0">引擎</span>
              <Select
                value={browserCfg.engine}
                onValueChange={v => void handleSaveBrowser({ engine: v })}>
                <SelectTrigger className="h-8 w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">自动（推荐）</SelectItem>
                  <SelectItem value="cdp">CDP（本机 Edge/Chrome）</SelectItem>
                  <SelectItem value="drission">DrissionPage</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox
                checked={browserCfg.headless}
                onCheckedChange={v => void handleSaveBrowser({ headless: !!v })}
              />
              默认无头模式（不弹浏览器窗口）
            </label>
            <label className="flex items-center gap-2 text-xs" style={{ color: colors.text }}>
              <Checkbox
                checked={browserCfg.keep_alive}
                onCheckedChange={v => void handleSaveBrowser({ keep_alive: !!v })}
              />
              流程结束后保持浏览器（keep-alive）
            </label>
            <div className="flex items-center gap-2">
              <Input
                value={browserCfg.edge_path}
                placeholder="浏览器路径（留空自动查找 Edge/Chrome）"
                className="h-8 flex-1 font-mono text-xs"
                onChange={e => setBrowserCfg(c => ({ ...c, edge_path: e.target.value }))}
              />
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={browserBusy}
                onClick={() => void handleSaveBrowser({ edge_path: browserCfg.edge_path.trim() })}>
                <Save className="w-3.5 h-3.5" />
                保存路径
              </Button>
            </div>
            <p className="text-[11px]" style={{ color: colors.secondaryText }}>
              {browserRunning
                ? `浏览器会话运行中 · 引擎 ${browserEngineLive || '…'}`
                : '浏览器未启动（首次使用浏览器积木时自动拉起）'}
              {!browserFound ? ' · ⚠ 未找到本机 Edge/Chrome，请在上方指定浏览器路径' : ''}
            </p>
            <p className="text-[11px]" style={{ color: colors.secondaryText }}>
              浏览器使用独立隔离 profile（data_dir/browser_profile），默认不含你的登录态；
              导航/点击/填充/JS 属动作类积木，外部 AI 执行需同时开启「Nexuz AI」页的两个开关。
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={browserBusy}
                onClick={() => void refreshBrowserStatus()}>
                <RefreshCw className="w-3.5 h-3.5" />
                刷新状态
              </Button>
            </div>
            {browserMsg ? (
              <p className="text-xs" style={{ color: colors.secondaryText }}>
                {browserMsg}
              </p>
            ) : null}
          </div>
        </SettingsSection>

        <SettingsSection
          title="数据存储"
          icon={<HardDrive className="w-4 h-4" />}
          open={openSections.data}
          onToggle={() => toggleSection('data')}
          colors={colors}
          headerRight={
            <HelpHint
              text="流程、模板、截图等保存在本机数据目录（默认 %LOCALAPPDATA%\Nexuz）。热更新只替换程序，不会动这里。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
            仅可信代码：自定义积木只在可终止的隔离 worker 中加载和执行，阻断网络和子进程、
            允许本地文件读写（落盘产出）；但仍可读取当前用户文件，且不是完整安全沙箱。
            注册表刷新只读取静态 SCHEMA；仍请只使用你已审查、且来源可信的 Python 文件。
          </div>
          <div
            className="rounded-xl border px-3 py-2.5 font-mono text-xs break-all mt-1"
            style={{ borderColor: colors.border, color: colors.text }}>
            {dataDirPath || '…'}
            <span className="block mt-1 opacity-60">
              {dataDirExists ? '目录存在' : '目录不存在（保存后会自动创建）'}
              {dataDirIsDefault ? ' · 默认位置' : ' · 自定义位置'}
            </span>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handleExportDataPack()}>
              导出数据包
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handleRestoreDataPack()}>
              恢复数据包
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handleOpenDataDir()}>
              <FolderOpen className="w-3.5 h-3.5" />
              打开数据目录
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handlePickDataDir()}>
              更改位置
            </Button>
            {!dataDirIsDefault && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={dataDirBusy}
                onClick={() => void handleResetDataDir()}>
                恢复默认
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              onClick={() => void handleClearScreenshotCache()}
              title="清理 screenshots 缓存（区域截图 / 匹配预览），不影响流程与模板">
              <Trash2 className="w-3.5 h-3.5" />
              清理截图缓存
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={dataDirBusy}
              className="text-rose-500 border-rose-500/40 hover:bg-rose-500/10"
              onClick={() => void handleClearDataDir()}>
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
          title="自定义积木"
          icon={<Puzzle className="w-4 h-4" />}
          open={openSections.userBlocks}
          onToggle={() => toggleSection('userBlocks')}
          colors={colors}
          headerRight={
            <HelpHint
              text="在下方编辑器编写 SCHEMA + handler，保存后点「刷新积木」出现在侧栏「自定义」。也可在外部编辑同一目录下的 .py。type 不可与内置重名。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div
            className="rounded-xl border px-3 py-2.5 font-mono text-xs break-all mt-1"
            style={{ borderColor: colors.border, color: colors.text }}>
            {userBlocksPath || '…'}
            {selectedUserBlockMeta ? (
              <span className="block mt-1 opacity-60">
                {selectedUserBlockMeta.trusted ? '已授权' : '未授权，不会出现在积木列表'}
                {selectedUserBlockMeta.sha256
                  ? ` · SHA-256 ${selectedUserBlockMeta.sha256.slice(0, 16)}…`
                  : ''}
              </span>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={userBlockFile || undefined}
              onValueChange={v => {
                if (userBlockDirty) {
                  void (async () => {
                    const ok = await confirm({
                      title: '切换文件？',
                      description: '当前有未保存修改，切换将丢弃更改。',
                      confirmText: '切换',
                      destructive: true
                    });
                    if (ok) {
                      setUserBlockDirty(false);
                      setUserBlockFile(v);
                    }
                  })();
                  return;
                }
                setUserBlockFile(v);
              }}>
              <SelectTrigger className="h-8 text-xs w-[12rem]">
                <SelectValue placeholder="选择 .py 文件" />
              </SelectTrigger>
              <SelectContent>
                {userBlockFiles.map(f => (
                  <SelectItem key={f.name} value={f.name} className="text-xs font-mono">
                    {f.trusted ? '已授权' : '未授权'} · {f.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={userBlocksBusy || !userBlockFile}
              onClick={() => void handleSaveUserBlock()}>
              <Save className="w-3.5 h-3.5" />
              保存{userBlockDirty ? ' *' : ''}
            </Button>
            {selectedUserBlockMeta?.trusted ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={userBlocksBusy || !userBlockFile}
                onClick={() => void handleRevokeUserBlock()}>
                停用
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={userBlocksBusy || !userBlockFile || userBlockDirty}
                onClick={() => void handleTrustUserBlock()}>
                审查并授权
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={userBlocksBusy}
              onClick={() => void handleRefreshUserBlocks()}>
              <RefreshCw className="w-3.5 h-3.5" />
              刷新积木
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={userBlocksBusy}
              onClick={() => void handleOpenUserBlocksDir()}>
              <FolderOpen className="w-3.5 h-3.5" />
              打开目录
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="h-8 text-xs font-mono w-[12rem]"
              placeholder="新文件 my_block.py"
              value={newBlockName}
              onChange={e => setNewBlockName(e.target.value)}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={userBlocksBusy}
              onClick={() => void handleCreateUserBlock()}>
              新建积木
            </Button>
          </div>
          {userBlockFile ? (
            <PythonScriptEditor
              value={userBlockCode}
              onChange={v => {
                setUserBlockCode(v);
                setUserBlockDirty(true);
              }}
              themeMode={themeMode}
              mode="block"
              height={320}
            />
          ) : (
            <p className="text-xs opacity-60">暂无文件，可点「新建积木」或从示例开始。</p>
          )}
          {userBlocksMsg ? (
            <p className="text-sm leading-relaxed" style={{ color: colors.secondaryText }}>
              {userBlocksMsg}
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
              title="刷新公告">
              <RefreshCw className={`w-3.5 h-3.5 ${annBusy ? 'animate-spin' : ''}`} />
            </Button>
          }>
          {updateHistory.length > 0 || announcement?.body ? (
            <div
              className="max-h-72 overflow-y-auto pr-1 space-y-1 rounded-xl border mt-1"
              style={{ borderColor: colors.border }}>
              {(updateHistory.length ? updateHistory : [announcement]).map((item: any, idx: number) => {
                const key = String(item.version || item.id || idx);
                const open = !!annOpenIds[key];
                return (
                  <div key={key} className="border-b last:border-b-0" style={{ borderColor: colors.border }}>
                    <button
                      type="button"
                      className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-black/5 dark:hover:bg-white/5"
                      onClick={() => setAnnOpenIds(prev => ({ ...prev, [key]: !prev[key] }))}>
                      {open ? (
                        <ChevronDown className="w-3.5 h-3.5 shrink-0 opacity-70" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 shrink-0 opacity-70" />
                      )}
                      <span className="font-mono text-xs opacity-70 shrink-0">
                        v{item.version || item.id || '?'}
                      </span>
                      <span className="text-sm font-medium truncate flex-1" style={{ color: colors.text }}>
                        {item.title || '更新'}
                      </span>
                    </button>
                    {open ? (
                      <div
                        className="px-3 pb-3 pl-9 text-sm leading-relaxed whitespace-pre-wrap"
                        style={{ color: colors.secondaryText }}>
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
          colors={colors}>
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
              onValueChange={v => {
                void handleDefaultCaptureModeChange(v);
              }}>
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
              onValueChange={v => {
                void handleDefaultPickMethodChange(v);
              }}>
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
              value={defaultCoordinateMode || 'window_client'}
              onValueChange={v => {
                void handleDefaultCoordinateModeChange(v);
              }}>
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
              <Label className="text-sm font-medium normal-case tracking-normal" style={{ color: colors.text }}>
                默认输出坐标
              </Label>
              <HelpHint
                text="OCR取字、图像模板匹配等识别节点输出的坐标格式。屏幕绝对=桌面像素；区域相对=相对识别/搜索区域左上角；目标窗口相对=附带窗口绑定，可直接给鼠标节点用（窗口挪动后仍准）。修改时若画布上已有不同设置的识别节点，将先提示并同步。"
                colors={colors}
                themeMode={themeMode}
              />
            </div>
            <Select
              value={defaultOutputCoordinateMode || 'window_client'}
              onValueChange={v => {
                void handleDefaultOutputCoordinateModeChange(v);
              }}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="screen_abs">屏幕绝对</SelectItem>
                <SelectItem value="region_rel">区域相对</SelectItem>
                <SelectItem value="window_client">目标窗口相对（推荐）</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-1.5">
              <Label
                htmlFor="default-node-interval"
                className="text-sm font-medium normal-case tracking-normal"
                style={{ color: colors.text }}>
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
              value={defaultNodeIntervalMs ?? 500}
              onChange={e => setDefaultNodeIntervalMs(e.target.value)}
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
          }>
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
                title="刷新进程列表">
                <RefreshCw className={`w-3.5 h-3.5 ${listBusy ? 'animate-spin' : ''}`} />
                刷新
              </Button>
            </div>

            <div className="flex items-center gap-2">
              <Checkbox
                id="only-with-window"
                checked={onlyWithWindow}
                onCheckedChange={v => setOnlyWithWindow(!!v)}
              />
              <Label
                htmlFor="only-with-window"
                className="text-xs font-normal normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                仅显示有窗口的进程
                <HelpHint text="推荐：过滤掉同名后台/辅助进程。" colors={colors} themeMode={themeMode} />
              </Label>
            </div>

            <Input
              value={processFilter}
              onChange={e => setProcessFilter(e.target.value)}
              placeholder="过滤：窗口标题 / 进程名 / PID / 路径"
              className="font-mono text-xs"
            />
            <Select
              value={selectedKey || undefined}
              onValueChange={v => {
                if (v !== '__empty') setSelectedKey(v);
              }}>
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
                  filtered.slice(0, 400).map(p => (
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
                style={{ color: colors.secondaryText }}>
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
              onClick={handleDetach}>
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
          colors={colors}>
          <div className="space-y-3 pt-1">
            <div className="flex items-center gap-3">
              <Checkbox
                id="setting-hide-window"
                checked={hideWindowOnRecord}
                onCheckedChange={v => setHideWindowOnRecord(!!v)}
              />
              <Label
                htmlFor="setting-hide-window"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                <EyeOff className="w-3.5 h-3.5 opacity-70" />
                操作时防误点（运行监控 / 录制隐藏）
                <HelpHint
                  text={
                    <>
                      开启后：运行流程时主窗口会缩成右上角监控小窗（暂停/结束、当前节点、CPU/内存）；录制、取点、框选时仍会暂时隐藏主窗口，避免点到本程序。
                      <br />
                      录制隐藏时使用屏幕右上角外部「停止录制」浮窗；未隐藏时使用应用内浮层。全局快捷键（运行/暂停/停止/停止录制）均可在下方「快捷键」中重新录制。
                    </>
                  }
                  colors={colors}
                  themeMode={themeMode}
                />
              </Label>
            </div>
            <div className="flex items-center gap-3">
              <Checkbox
                id="setting-toolbar-labels"
                checked={showToolbarLabels}
                onCheckedChange={v => setShowToolbarLabels(!!v)}
              />
              <Label
                htmlFor="setting-toolbar-labels"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                <Type className="w-3.5 h-3.5 opacity-70" />
                显示顶部按钮文字
                <HelpHint
                  text="开启后，窗口较宽时顶部按钮显示文字；关闭后始终只显示图标。窗口变窄时会自动隐藏文字（优先于本开关）。"
                  colors={colors}
                  themeMode={themeMode}
                />
              </Label>
            </div>
            <div className="flex items-center gap-3">
              <Checkbox
                id="setting-hide-side-panels"
                checked={hideSidePanelsOnSettings}
                onCheckedChange={v => setHideSidePanelsOnSettings(!!v)}
              />
              <Label
                htmlFor="setting-hide-side-panels"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                <PanelsTopLeft className="w-3.5 h-3.5 opacity-70" />
                打开设置时隐藏左右面板
                <HelpHint
                  text="开启后进入设置会临时隐藏左侧积木栏与右侧属性栏，设置全幅显示；关闭设置后恢复原来的展开状态。关闭本选项则设置只占中间区域。"
                  colors={colors}
                  themeMode={themeMode}
                />
              </Label>
            </div>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <Label
                className="text-sm font-medium normal-case tracking-normal inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                <MousePointer2 className="w-3.5 h-3.5 opacity-70" />
                节点右键菜单
                <HelpHint
                  text="全部一级：所有操作平铺显示。二级组合：一级只保留运行/重命名/复制/折叠，其余收入「更多」与「删除」子菜单。"
                  colors={colors}
                  themeMode={themeMode}
                />
              </Label>
              <Select
                value={nodeContextMenuMode}
                onValueChange={v => setNodeContextMenuMode(v === 'flat' ? 'flat' : 'grouped')}>
                <SelectTrigger className="h-8 text-xs w-[11rem]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grouped">二级菜单组合</SelectItem>
                  <SelectItem value="flat">全部一级菜单</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <p className="text-xs leading-relaxed opacity-60 pt-3" style={{ color: colors.text }}>
            标题栏「插件模式」可让窗口浮在无边框全屏游戏之上并调节透明度。默认快捷键：
            {formatHotkeyLabel(hotkeys?.plugin_mode || DEFAULT_HOTKEYS.plugin_mode)} 开关插件模式、
            {formatHotkeyLabel(hotkeys?.click_through || DEFAULT_HOTKEYS.click_through)}{' '}
            开关点击穿透（可在下方「快捷键」中改键）。独占全屏游戏在点到本窗口时仍可能退出全屏。
          </p>
        </SettingsSection>

        <SettingsSection
          title="保存"
          icon={<Save className="w-4 h-4" />}
          open={openSections.save}
          onToggle={() => toggleSection('save')}
          colors={colors}
          headerRight={
            <HelpHint
              text="定时自动保存仅对已有文件路径的流程生效。「运行后自动保存」即使从未保存过，也会按「时间_节点数」自动命名并写入流程库。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div className="space-y-4 pt-1">
            <div className="flex items-center gap-3">
              <Checkbox
                id="setting-auto-save"
                checked={autoSaveEnabled}
                onCheckedChange={v => setAutoSaveEnabled(!!v)}
              />
              <Label
                htmlFor="setting-auto-save"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer"
                style={{ color: colors.text }}>
                启用自动保存
              </Label>
            </div>
            <div className="flex items-center gap-3 pl-0.5">
              <Label
                htmlFor="setting-auto-save-interval"
                className="text-sm font-medium normal-case tracking-normal shrink-0"
                style={{ color: colors.text }}>
                自动保存间隔（秒）
              </Label>
              <Input
                id="setting-auto-save-interval"
                type="number"
                min={10}
                max={3600}
                step={10}
                className="h-8 w-28"
                disabled={!autoSaveEnabled}
                value={autoSaveIntervalSec}
                onChange={e => setAutoSaveIntervalSec(e.target.value)}
                title="范围 10～3600 秒"
              />
            </div>
            <div className="flex items-center gap-3">
              <Checkbox
                id="setting-save-after-run"
                checked={saveAfterRun}
                onCheckedChange={v => setSaveAfterRun(!!v)}
              />
              <Label
                htmlFor="setting-save-after-run"
                className="text-sm font-medium normal-case tracking-normal cursor-pointer inline-flex items-center gap-1.5"
                style={{ color: colors.text }}>
                运行结束后自动保存流程
                <HelpHint
                  text="流程运行完成或停止后自动保存。若尚未保存过，将自动命名为「年月日_时分秒_N节点」并写入流程库。"
                  colors={colors}
                  themeMode={themeMode}
                />
              </Label>
            </div>
          </div>
        </SettingsSection>

        <SettingsSection
          title="快捷键"
          icon={<Keyboard className="w-4 h-4" />}
          open={openSections.shortcuts}
          onToggle={() => toggleSection('shortcuts')}
          colors={colors}>
          <div className="space-y-3 pt-1 text-sm" style={{ color: colors.text }}>
            <p className="text-xs opacity-70 leading-relaxed">
              在输入框中打字时，下列画布快捷键不会触发，以免误删或打断输入。全局快捷键在窗口隐藏时仍可用，可点「改键」重新录制。
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
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Ctrl</kbd>
                  {'+'}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Z</kbd>
                  {' / '}
                  <kbd className="font-mono px-1 rounded bg-black/5 dark:bg-white/10">Y</kbd>
                  ：撤销 / 重做流程编辑
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
            <div className="rounded-lg border px-3 py-2.5 space-y-3" style={{ borderColor: colors.border }}>
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium opacity-80">录制与运行（全局，可改）</p>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs opacity-70"
                  onClick={async () => {
                    const next = resetHotkeys();
                    try {
                      await bridge.setHotkeys?.(next);
                    } catch {
                      /* ignore */
                    }
                  }}
                  title="恢复全部全局快捷键为默认">
                  全部恢复默认
                </Button>
              </div>
              {(
                [
                  { slot: 'start_run', label: '开始 / 继续运行' },
                  { slot: 'pause_run', label: '运行中暂停' },
                  { slot: 'stop_run', label: '结束运行' },
                  { slot: 'record_stop', label: '停止录制' },
                  { slot: 'plugin_mode', label: '开关插件模式' },
                  { slot: 'click_through', label: '开关点击穿透' }
                ] as const
              ).map(row => (
                <div key={row.slot} className="flex items-center gap-2 min-w-0">
                  <div className="flex items-center gap-1.5 min-w-0 flex-1">
                    <Label className="text-xs opacity-80 shrink-0">{row.label}</Label>
                    <button
                      type="button"
                      className="text-[11px] opacity-50 hover:opacity-80 shrink-0 whitespace-nowrap"
                      title={`恢复为默认 ${formatHotkeyLabel(DEFAULT_HOTKEYS[row.slot])}`}
                      onClick={async () => {
                        const res = setHotkey(row.slot, DEFAULT_HOTKEYS[row.slot]);
                        if (res?.ok === false) return;
                        try {
                          await bridge.setHotkeys?.(res.hotkeys);
                        } catch {
                          /* ignore */
                        }
                      }}>
                      默认 {formatHotkeyLabel(DEFAULT_HOTKEYS[row.slot])}
                    </button>
                  </div>
                  <HotkeyCaptureField
                    value={hotkeys?.[row.slot] || DEFAULT_HOTKEYS[row.slot]}
                    colors={colors}
                    onChange={async keys => {
                      const res = setHotkey(row.slot, keys);
                      if (res?.ok === false) {
                        await alert({
                          title: '快捷键冲突',
                          description: res.error || '与其它快捷键重复，请换一组'
                        });
                        return;
                      }
                      try {
                        const sync = await bridge.setHotkeys?.(res.hotkeys || hotkeys);
                        if (sync?.ok === false) {
                          await alert({
                            title: '快捷键冲突',
                            description: sync.error || '与其它快捷键重复'
                          });
                        }
                      } catch {
                        /* ignore */
                      }
                    }}
                  />
                </div>
              ))}
              <p className="text-[11px] opacity-55 leading-relaxed">
                建议使用「字母/修饰键 + 功能键」。各组全局快捷键不能互相重复。点击穿透快捷键在插件模式开启时生效。
              </p>
            </div>
          </div>
        </SettingsSection>

        <SettingsSection
          title="日志"
          icon={<Terminal className="w-4 h-4" />}
          open={openSections.logging}
          onToggle={() => toggleSection('logging')}
          colors={colors}
          headerRight={
            <HelpHint
              text="右侧面板默认只显示「运行」日志。系统/操作可按过滤器查看；诊断默认关闭，开启后才会落盘并出现在面板中。"
              colors={colors}
              themeMode={themeMode}
            />
          }>
          <div className="flex items-center gap-2 pt-1">
            <Checkbox
              id="diag-logging"
              checked={diagLogging}
              onCheckedChange={v => void handleDiagLoggingChange(v === true)}
            />
            <Label
              htmlFor="diag-logging"
              className="text-sm cursor-pointer inline-flex items-center gap-1.5"
              style={{ color: colors.text }}>
              记录诊断日志
              <HelpHint
                text="包含内存采样、坐标换算中间值等细节。关闭时不推送到界面、不写入诊断落盘。"
                colors={colors}
                themeMode={themeMode}
              />
            </Label>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}
