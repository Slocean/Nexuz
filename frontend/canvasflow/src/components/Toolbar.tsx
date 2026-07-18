import React, { useEffect, useState } from 'react';
import {
  Play,
  Save,
  Sun,
  Moon,
  Sparkles,
  Palette,
  RefreshCw,
  Check,
  Download,
  Upload,
  CircleDot,
  Pause,
  Square,
  Trash2,
  Undo2,
  Redo2,
  RotateCcw,
  Bug,
  FileCode2,
  Settings2,
  Minus,
  Maximize2,
  Minimize2,
  Pin,
  Waypoints,
  Megaphone,
  ArrowUpCircle,
  AppWindow,
  MousePointerClick,
  X
} from 'lucide-react';
import { ThemeName, ThemeMode } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { bridge } from '@/bridge';
import { useFlowStore } from '../../../src/store/flowModelStore';
import { useAppDialog } from './AppDialogs';
import { useUpdateDialog } from './UpdateDialog';

interface ToolbarProps {
  themeName: ThemeName;
  setThemeName: (name: ThemeName) => void;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
  onRunWorkflow: () => void;
  isExecuting: boolean;
  onToggleAssistant: () => void;
  isAssistantOpen: boolean;
  onClearCanvas: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  onBackToMain?: () => void;
  onSave?: () => Promise<boolean> | boolean | void;
  onImport?: () => void;
  onExport?: () => void;
  onToggleRecord?: () => void;
  recording?: boolean;
  onPause?: () => void;
  onResume?: () => void;
  onStop?: () => void;
  onForceReset?: () => void;
  onToggleDebug?: () => void;
  debugMode?: boolean;
  execStatus?: string;
  viewMode?: 'canvas' | 'code' | 'settings';
  onViewModeChange?: (mode: 'canvas' | 'code' | 'settings') => void;
  hotkeyLabels?: {
    start_run?: string;
    stop_run?: string;
    pause_run?: string;
    record_stop?: string;
  };
}

export default function Toolbar({
  themeName,
  setThemeName,
  themeMode,
  setThemeMode,
  onRunWorkflow,
  isExecuting,
  onToggleAssistant,
  isAssistantOpen,
  onClearCanvas,
  onUndo,
  onRedo,
  canUndo = false,
  canRedo = false,
  onBackToMain,
  onSave,
  onImport,
  onExport,
  onToggleRecord,
  recording,
  onPause,
  onResume,
  onStop,
  onForceReset,
  onToggleDebug,
  debugMode = false,
  execStatus = 'idle',
  viewMode = 'canvas',
  onViewModeChange,
  hotkeyLabels,
}: ToolbarProps) {
  const runKey = hotkeyLabels?.start_run || 'X+F3';
  const pauseKey = hotkeyLabels?.pause_run || 'X+F5';
  const stopKey = hotkeyLabels?.stop_run || 'X+F4';
  const recordStopKey = hotkeyLabels?.record_stop || 'X+F10';
  const { openAlert } = useAppDialog();
  const { openUpdate } = useUpdateDialog();
  const pluginModeRemote = useFlowStore((s) => s.pluginModeRemote);
  const showToolbarLabels = useFlowStore((s) => !!s.showToolbarLabels);
  // Priority: viewport < xl always hides labels; when wide enough, settings decide.
  const labelCls = showToolbarLabels ? 'hidden xl:inline' : 'hidden';
  const btnPad = showToolbarLabels ? 'px-2 xl:px-3' : 'px-2';
  const [isSaved, setIsSaved] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [onTop, setOnTop] = useState(false);
  const [pluginMode, setPluginMode] = useState(false);
  const [pluginOpacity, setPluginOpacity] = useState(0.85);
  const [pluginClickThrough, setPluginClickThrough] = useState(false);
  const [updateDot, setUpdateDot] = useState(false);
  const [annDot, setAnnDot] = useState(false);
  const colors = getThemeColors(themeName, themeMode);
  const themes: ThemeName[] = ['Ocean', 'Mint', 'Purple', 'Rose', 'Orange'];

  const applyPluginUiClass = (enabled: boolean, opacity = pluginOpacity) => {
    const op = Math.max(0.25, Math.min(1, Number(opacity) || 0.85));
    document.documentElement.classList.toggle('plugin-mode', !!enabled);
    document.documentElement.style.setProperty('--plugin-opacity', enabled ? String(op) : '1');
    // Precompute % for color-mix (avoids calc()* in older WebView2)
    document.documentElement.style.setProperty(
      '--plugin-fill',
      enabled ? `${Math.round(op * 70)}%` : '100%',
    );
    document.documentElement.style.setProperty(
      '--plugin-chrome-fill',
      enabled ? `${Math.round(op * 85)}%` : '100%',
    );
  };

  const persistPluginPrefs = (state: {
    enabled: boolean;
    opacity: number;
    click_through: boolean;
  }) => {
    try {
      localStorage.setItem('nexuz.pluginMode', JSON.stringify(state));
    } catch {
      /* ignore */
    }
  };

  const syncPluginMode = async (patch: {
    enabled?: boolean;
    opacity?: number;
    click_through?: boolean;
  }) => {
    const res = await bridge.setPluginMode?.(patch);
    if (res?.ok === false) {
      openAlert({
        title: '插件模式',
        description: res.error || '设置失败',
      });
      return;
    }
    const enabled = !!res?.enabled;
    const opacity = Number(res?.opacity ?? pluginOpacity);
    const clickThrough = !!res?.click_through;
    setPluginMode(enabled);
    if (res?.opacity != null) setPluginOpacity(opacity);
    if (res?.click_through != null) setPluginClickThrough(clickThrough);
    if (res?.on_top != null) setOnTop(!!res.on_top);
    applyPluginUiClass(enabled, opacity);
    persistPluginPrefs({
      enabled,
      opacity,
      click_through: clickThrough,
    });
  };

  useEffect(() => {
    if (!pluginModeRemote) return;
    const op = Number(pluginModeRemote.opacity ?? 0.85);
    setPluginMode(!!pluginModeRemote.enabled);
    if (pluginModeRemote.opacity != null) setPluginOpacity(op);
    setPluginClickThrough(!!pluginModeRemote.click_through);
    if (pluginModeRemote.on_top != null) setOnTop(!!pluginModeRemote.on_top);
    applyPluginUiClass(!!pluginModeRemote.enabled, op);
    persistPluginPrefs({
      enabled: !!pluginModeRemote.enabled,
      opacity: op,
      click_through: !!pluginModeRemote.click_through,
    });
  }, [pluginModeRemote?.rev]);

  useEffect(() => {
    bridge.windowIsMaximized?.().then((res: any) => {
      if (res?.maximized != null) setMaximized(!!res.maximized);
    });
    bridge.windowIsOnTop?.().then((res: any) => {
      if (res?.on_top != null) setOnTop(!!res.on_top);
    });
    (async () => {
      try {
        const saved = JSON.parse(localStorage.getItem('nexuz.pluginMode') || 'null');
        const remote = await bridge.getPluginMode?.();
        if (saved?.enabled) {
          await syncPluginMode({
            enabled: true,
            opacity: Number(saved.opacity ?? remote?.opacity ?? 0.85),
            click_through: !!saved.click_through,
          });
        } else if (remote?.ok) {
          setPluginMode(!!remote.enabled);
          if (remote.opacity != null) setPluginOpacity(Number(remote.opacity));
          setPluginClickThrough(!!remote.click_through);
          applyPluginUiClass(!!remote.enabled, Number(remote.opacity ?? 0.85));
        }
      } catch {
        /* ignore */
      }
    })();
    (async () => {
      try {
        const upd = await bridge.checkForUpdate();
        if (upd?.ok && upd.update_available) setUpdateDot(true);
      } catch {
        /* ignore */
      }
      try {
        const res = await bridge.fetchNotice();
        const n = res?.notice;
        if (!n?.id || !n?.body) return;
        let readId = '';
        try {
          const stored = await bridge.getNoticeReadId?.();
          if (stored?.ok && stored.id) readId = String(stored.id);
        } catch {
          /* ignore */
        }
        if (!readId) {
          try {
            readId = localStorage.getItem('nexuz.noticeReadId') || '';
          } catch {
            /* ignore */
          }
        }
        if (String(n.id) !== readId) setAnnDot(true);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const handleCheckUpdate = async () => {
    // Dialog opens immediately with loading; network runs inside openUpdate()
    const res = await openUpdate();
    if (res?.ok) setUpdateDot(!!res.update_available);
  };

  const handleNotice = async () => {
    const dlg = openAlert({
      title: '通知',
      description: '正在获取通知…',
      loading: true,
      okText: '我知道了',
    });
    try {
      const res = await bridge.fetchNotice();
      const n = res?.notice;
      if (!res?.ok || !n?.body) {
        dlg.setContent({
          title: '通知',
          description: res?.error || '暂无通知',
          okText: '我知道了',
        });
        await dlg.done;
        return;
      }
      dlg.setContent({
        title: n.title || '通知',
        description: String(n.body),
        okText: '我知道了',
      });
      if (n.id) {
        try {
          await bridge.setNoticeReadId?.(String(n.id));
        } catch {
          /* ignore */
        }
        try {
          localStorage.setItem('nexuz.noticeReadId', String(n.id));
        } catch {
          /* ignore */
        }
        setAnnDot(false);
      }
      await dlg.done;
    } catch (e: any) {
      dlg.setContent({
        title: '获取通知失败',
        description: String(e?.message || e),
        okText: '我知道了',
      });
      await dlg.done;
    }
  };

  const handleSave = async () => {
    if (onSave) {
      const ok = await onSave();
      if (ok) {
        setIsSaved(true);
        setTimeout(() => setIsSaved(false), 2000);
      }
      return;
    }
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const onWinMinimize = (e: React.MouseEvent) => {
    e.stopPropagation();
    bridge.windowMinimize();
  };
  const onWinMaximize = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const res = await bridge.windowToggleMaximize();
    if (res?.maximized != null) setMaximized(!!res.maximized);
    else setMaximized(v => !v);
  };
  const onWinClose = (e: React.MouseEvent) => {
    e.stopPropagation();
    bridge.windowClose();
  };
  const onWinToggleOnTop = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await Promise.race([
        bridge.windowToggleOnTop?.() ?? Promise.resolve(null),
        new Promise<{ ok: false; error: string }>(resolve =>
          setTimeout(() => resolve({ ok: false, error: 'timeout' }), 3000)
        )
      ]);
      if (res && (res as any).on_top != null) setOnTop(!!(res as any).on_top);
      else if ((res as any)?.ok !== false) setOnTop(v => !v);
    } catch {
      /* ignore bridge errors */
    }
  };

  return (
    <header
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text
      }}
      className="relative flex flex-col border-b z-40 shrink-0">
      {/* Top/bottom padding strips — frameless window drag handle */}
      <div
        className="pywebview-drag-region h-1.5 w-full shrink-0"
        title="拖动窗口"
        aria-hidden
      />
      <div className="relative h-14">
      {/* True-centered primary actions */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20">
        <div className="flex items-center gap-0.5 bg-black/5 dark:bg-white/5 p-1 rounded-2xl border border-black/10 dark:border-white/10">
          <Button
            size="sm"
            className={btnPad}
            onClick={onRunWorkflow}
            title={
              execStatus === 'stopping'
                ? '停止中'
                : execStatus === 'running'
                  ? '运行中'
                  : execStatus === 'paused' || execStatus === 'breakpoint'
                    ? `继续（${runKey}）`
                    : `运行（${runKey}）`
            }
            disabled={
              isExecuting &&
              execStatus !== 'paused' &&
              execStatus !== 'breakpoint'
            }
            style={{
              backgroundColor:
                isExecuting &&
                execStatus !== 'paused' &&
                execStatus !== 'breakpoint'
                  ? colors.secondaryText + '20'
                  : colors.primary,
              color: '#FFFFFF'
            }}>
            {execStatus === 'running' || execStatus === 'stopping' ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span className={labelCls}>
              {execStatus === 'stopping'
                ? '停止中'
                : execStatus === 'running'
                  ? '运行中'
                  : execStatus === 'paused' || execStatus === 'breakpoint'
                    ? '继续'
                    : '运行'}
            </span>
          </Button>

          {execStatus === 'paused' || execStatus === 'breakpoint' || debugMode ? null : (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onPause}
              disabled={execStatus !== 'running'}
              title={`暂停（${pauseKey}）`}
            >
              <Pause className="w-3.5 h-3.5" />
              <span className={labelCls}>暂停</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            className={btnPad}
            onClick={onStop}
            disabled={execStatus === 'idle' && !recording}
            title={`停止（${stopKey}）`}
          >
            <Square className="w-3 h-3" />
            <span className={labelCls}>{execStatus === 'stopping' ? '停止中' : '停止'}</span>
          </Button>

          {onForceReset ? (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onForceReset}
              title="卡住时点这里：强制清运行/录制状态，回到可运行"
              style={{ color: colors.danger }}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span className={labelCls}>重置</span>
            </Button>
          ) : null}

          {onToggleDebug && (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onToggleDebug}
              disabled={execStatus === 'stopping'}
              title={debugMode ? '关闭调试模式' : '开启调试模式（断点 / 单步）'}
              style={
                debugMode
                  ? { color: '#d97706', backgroundColor: 'rgba(245, 158, 11, 0.12)' }
                  : undefined
              }
            >
              <Bug className="w-3.5 h-3.5" />
              <span className={labelCls}>{debugMode ? '调试中' : '调试'}</span>
            </Button>
          )}

          <div className="w-px h-5 bg-black/15 dark:bg-white/15 mx-0.5" />

          <Button variant="ghost" size="sm" className={btnPad} onClick={handleSave} title="保存">
            {isSaved ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" />
            ) : (
              <Save className="w-3.5 h-3.5 opacity-80" />
            )}
            <span className={`${labelCls} ${isSaved ? 'text-emerald-500' : ''}`}>
              {isSaved ? '已保存' : '保存'}
            </span>
          </Button>

          {onImport && (
            <Button variant="ghost" size="sm" className={btnPad} onClick={onImport} title="从文件导入流程">
              <Upload className="w-3.5 h-3.5 opacity-80" />
              <span className={labelCls}>导入</span>
            </Button>
          )}

          {onExport && (
            <Button variant="ghost" size="sm" className={btnPad} onClick={onExport} title="导出流程到文件">
              <Download className="w-3.5 h-3.5 opacity-80" />
              <span className={labelCls}>导出</span>
            </Button>
          )}

          {onToggleRecord && (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onToggleRecord}
              style={{ color: recording ? colors.danger : undefined }}
              title={
                recording
                  ? `停止录制（${recordStopKey}）`
                  : `录制操作：把鼠标/键盘转成流程节点；停止：${recordStopKey}`
              }>
              <CircleDot className={`w-3.5 h-3.5 ${recording ? 'animate-pulse' : ''}`} />
              <span className={labelCls}>{recording ? '停止录制' : '录制'}</span>
            </Button>
          )}

          {onUndo && (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onUndo}
              disabled={!canUndo}
              title="撤销（Ctrl+Z）"
            >
              <Undo2 className="w-3.5 h-3.5 opacity-80" />
              <span className={labelCls}>撤销</span>
            </Button>
          )}

          {onRedo && (
            <Button
              variant="ghost"
              size="sm"
              className={btnPad}
              onClick={onRedo}
              disabled={!canRedo}
              title="重做（Ctrl+Y）"
            >
              <Redo2 className="w-3.5 h-3.5 opacity-80" />
              <span className={labelCls}>重做</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            className={btnPad}
            onClick={onClearCanvas}
            style={{ color: colors.danger }}
            title="清空画布">
            <Trash2 className="w-3.5 h-3.5" />
            <span className={labelCls}>清空</span>
          </Button>
        </div>
      </div>

      <div className="relative z-10 h-full flex items-center justify-between px-2">
        {/* Left: brand + view tabs + AI */}
        <div className="flex items-center gap-1.5 min-w-0 shrink-0 z-10">
          <div className="pywebview-drag-region flex items-center gap-2 pl-1 pr-2">
            {onBackToMain && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="pywebview-no-drag"
                onClick={onBackToMain}>
                主程序
              </Button>
            )}
            <div className="h-14 w-14 shrink-0 flex items-center justify-center">
              <img
                src={`${import.meta.env.BASE_URL}logo.png`}
                alt="Nexuz"
                title="Nexuz"
                className="max-h-full max-w-full object-contain select-none"
                draggable={false}
              />
            </div>
            <span className="font-semibold text-sm opacity-90 select-none">Nexuz</span>
          </div>

          {onViewModeChange && (
            <div className="flex items-center gap-1 bg-black/5 dark:bg-white/5 p-1 rounded-2xl border border-black/10 dark:border-white/10">
              <Button
                size="sm"
                className="h-8 w-8 px-0"
                onClick={() => onViewModeChange('canvas')}
                title="画布"
                style={
                  viewMode === 'canvas'
                    ? { backgroundColor: colors.primary, color: '#FFFFFF' }
                    : { backgroundColor: 'transparent', color: colors.text }
                }
                variant="ghost">
                <Waypoints className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="sm"
                className="h-8 w-8 px-0"
                onClick={() => onViewModeChange('code')}
                title="JSON"
                style={
                  viewMode === 'code'
                    ? { backgroundColor: colors.primary, color: '#FFFFFF' }
                    : { backgroundColor: 'transparent', color: colors.text }
                }
                variant="ghost">
                <FileCode2 className="w-3.5 h-3.5" />
              </Button>
              <Button
                size="sm"
                className="h-8 w-8 px-0"
                onClick={() => onViewModeChange('settings')}
                title="设置"
                style={
                  viewMode === 'settings'
                    ? { backgroundColor: colors.primary, color: '#FFFFFF' }
                    : { backgroundColor: 'transparent', color: colors.text }
                }
                variant="ghost">
                <Settings2 className="w-3.5 h-3.5" />
              </Button>
            </div>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onToggleAssistant}
            title="Flow AI"
            style={isAssistantOpen ? { color: colors.primary } : undefined}>
            <Sparkles className="w-4 h-4" />
          </Button>
        </div>

        {/* Drag filler */}
        <div className="pywebview-drag-region flex-1 self-stretch min-w-[24px] mx-2" />

        {/* Right: update / announce / theme / window */}
        <div className="flex items-center gap-1 shrink-0 z-10">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 relative"
            onClick={() => void handleNotice()}
            title="通知">
            <Megaphone className="w-4 h-4" />
            {annDot ? (
              <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-amber-500" />
            ) : null}
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 relative"
            onClick={() => void handleCheckUpdate()}
            title="检查更新">
            <ArrowUpCircle className="w-4 h-4" />
            {updateDot ? (
              <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-emerald-500" />
            ) : null}
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="主题">
                <Palette className="w-4 h-4 opacity-80" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48">
              <DropdownMenuLabel>深浅主题</DropdownMenuLabel>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setThemeMode('light');
                }}
              >
                <Sun className="w-3.5 h-3.5 opacity-80" />
                <span className="flex-1">浅色</span>
                {themeMode === 'light' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : null}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  setThemeMode('dark');
                }}
              >
                <Moon className="w-3.5 h-3.5 opacity-80" />
                <span className="flex-1">深色</span>
                {themeMode === 'dark' ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : null}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>主题色</DropdownMenuLabel>
              {themes.map(t => (
                <DropdownMenuItem
                  key={t}
                  onSelect={(e) => {
                    e.preventDefault();
                    setThemeName(t);
                  }}
                >
                  <span
                    style={{ backgroundColor: getThemeColors(t, themeMode).primary }}
                    className="w-3 h-3 rounded-full border border-black/20 dark:border-white/20"
                  />
                  <span className="flex-1">{t}</span>
                  {themeName === t && <Check className="w-3.5 h-3.5 text-emerald-500" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex items-center ml-1 pl-1 border-l border-black/10 dark:border-white/10">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title="插件模式（浮在游戏上）"
                  className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
                  style={pluginMode ? { color: colors.primary } : undefined}
                >
                  <AppWindow className={`w-3.5 h-3.5 ${pluginMode ? 'opacity-100' : 'opacity-80'}`} />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64 z-[200]">
                <DropdownMenuLabel>插件模式</DropdownMenuLabel>
                <p className="px-2 pb-2 text-[11px] leading-relaxed opacity-60">
                  浮在无边框全屏游戏之上，背景半透明。独占全屏点到本窗口时仍可能退出全屏。开启点击穿透后按 X+F9 可开关穿透。
                </p>
                <DropdownMenuItem
                  onSelect={(e) => {
                    e.preventDefault();
                    void syncPluginMode({
                      enabled: !pluginMode,
                      opacity: pluginOpacity,
                      click_through: pluginClickThrough,
                    });
                  }}
                >
                  <AppWindow className="w-3.5 h-3.5" />
                  <span className="flex-1">{pluginMode ? '关闭插件模式' : '开启插件模式'}</span>
                  {pluginMode ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : null}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <div
                  className="px-2 py-2 space-y-1.5"
                  onPointerDown={(e) => e.stopPropagation()}
                  onPointerUp={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="opacity-70">不透明度</span>
                    <span className="font-mono opacity-60">{Math.round(pluginOpacity * 100)}%</span>
                  </div>
                  <input
                    type="range"
                    min={25}
                    max={100}
                    step={5}
                    disabled={!pluginMode}
                    value={Math.round(pluginOpacity * 100)}
                    className="w-full accent-current disabled:opacity-40"
                    onChange={(e) => {
                      const v = Number(e.target.value) / 100;
                      setPluginOpacity(v);
                      applyPluginUiClass(true, v);
                      if (!pluginMode) return;
                      // Debounce: apply while dragging (mouseup often lost inside dropdown)
                      const t = (window as any).__nexuzPluginOpacityTimer as number | undefined;
                      if (t) window.clearTimeout(t);
                      (window as any).__nexuzPluginOpacityTimer = window.setTimeout(() => {
                        void syncPluginMode({
                          enabled: true,
                          opacity: v,
                          click_through: pluginClickThrough,
                        });
                      }, 120);
                    }}
                    onPointerUp={(e) => {
                      if (!pluginMode) return;
                      const v = Number((e.target as HTMLInputElement).value) / 100;
                      const t = (window as any).__nexuzPluginOpacityTimer as number | undefined;
                      if (t) window.clearTimeout(t);
                      void syncPluginMode({
                        enabled: true,
                        opacity: v,
                        click_through: pluginClickThrough,
                      });
                    }}
                  />
                </div>
                <DropdownMenuItem
                  disabled={!pluginMode}
                  onSelect={(e) => {
                    e.preventDefault();
                    void syncPluginMode({
                      enabled: true,
                      opacity: pluginOpacity,
                      click_through: !pluginClickThrough,
                    });
                  }}
                >
                  <MousePointerClick className="w-3.5 h-3.5" />
                  <span className="flex-1">点击穿透（操作游戏）</span>
                  {pluginClickThrough ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : null}
                </DropdownMenuItem>
                {pluginMode ? (
                  <p className="px-2 pb-2 text-[10px] opacity-50">穿透开关快捷键：X+F9</p>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              type="button"
              onClick={onWinToggleOnTop}
              title={onTop ? '取消置顶' : '窗口置顶'}
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
              style={onTop ? { color: colors.primary } : undefined}>
              <Pin className={`w-3.5 h-3.5 ${onTop ? 'fill-current' : 'opacity-80'}`} />
            </button>
            <button
              type="button"
              onClick={onWinMinimize}
              title="最小化"
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors">
              <Minus className="w-4 h-4 opacity-80" />
            </button>
            <button
              type="button"
              onClick={onWinMaximize}
              title={maximized ? '还原' : '最大化'}
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors">
              {maximized ? (
                <Minimize2 className="w-3.5 h-3.5 opacity-80" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5 opacity-80" />
              )}
            </button>
            <button
              type="button"
              onClick={onWinClose}
              title="关闭"
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-rose-500 hover:text-white transition-colors">
              <X className="w-4 h-4 opacity-90" />
            </button>
          </div>
        </div>
      </div>
      </div>
      <div
        className="pywebview-drag-region h-1.5 w-full shrink-0"
        title="拖动窗口"
        aria-hidden
      />
    </header>
  );
}
