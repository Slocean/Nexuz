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
  FolderOpen,
  CircleDot,
  Pause,
  Square,
  Trash2,
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
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { bridge } from '@/bridge';
import { useAppDialog } from './AppDialogs';

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
  onBackToMain?: () => void;
  onSave?: () => Promise<boolean> | boolean | void;
  onOpen?: () => void;
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
  onBackToMain,
  onSave,
  onOpen,
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
  onViewModeChange
}: ToolbarProps) {
  const { alert, confirm } = useAppDialog();
  const [isSaved, setIsSaved] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [onTop, setOnTop] = useState(false);
  const [updateDot, setUpdateDot] = useState(false);
  const [annDot, setAnnDot] = useState(false);
  const colors = getThemeColors(themeName, themeMode);
  const themes: ThemeName[] = ['Ocean', 'Mint', 'Purple', 'Rose', 'Orange'];

  useEffect(() => {
    bridge.windowIsMaximized?.().then((res: any) => {
      if (res?.maximized != null) setMaximized(!!res.maximized);
    });
    bridge.windowIsOnTop?.().then((res: any) => {
      if (res?.on_top != null) setOnTop(!!res.on_top);
    });
    (async () => {
      try {
        const upd = await bridge.checkForUpdate();
        if (upd?.ok && upd.update_available) setUpdateDot(true);
      } catch {
        /* ignore */
      }
      try {
        const ann = await bridge.fetchAnnouncement();
        const a = ann?.announcement;
        if (!a?.id) return;
        let readId = '';
        try {
          readId = localStorage.getItem('nexuz.announcementReadId') || '';
        } catch {
          /* ignore */
        }
        if (String(a.id) !== readId) setAnnDot(true);
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const handleCheckUpdate = async () => {
    try {
      const res = await bridge.checkForUpdate();
      if (!res?.ok) {
        await alert({ title: '检查更新失败', description: res?.error || '无法连接 GitHub' });
        return;
      }
      setUpdateDot(!!res.update_available);
      if (!res.update_available) {
        await alert({
          title: '已是最新版本',
          description: `当前版本 ${res.current_version}`,
        });
        return;
      }

      const notes = String(res.release_notes || '').trim();
      const preview = notes
        ? `\n\n更新说明：\n${notes.slice(0, 600)}${notes.length > 600 ? '…' : ''}`
        : '';
      const goDownload = await confirm({
        title: `发现新版本 ${res.latest_version}`,
        description: `当前 ${res.current_version} → ${res.latest_version}${preview}`,
        confirmText: '下载更新',
        cancelText: '稍后',
      });
      if (!goDownload) return;

      const dl = await bridge.downloadUpdate(res.download_url || null);
      if (!dl?.ok) {
        const open = await confirm({
          title: '下载失败',
          description: dl?.error || '无法下载更新包',
          confirmText: '打开 Releases',
          cancelText: '关闭',
        });
        if (open) await bridge.openReleasesPage();
        return;
      }

      const goApply = await confirm({
        title: '下载完成',
        description: `${dl.message || '更新包已就绪'}。是否立即替换并重启？请先保存流程。`,
        confirmText: '立即更新',
        cancelText: '稍后',
      });
      if (!goApply) {
        await alert({
          title: '已下载',
          description: '可稍后在「设置 → 关于与更新」点击「立即更新」。',
        });
        return;
      }

      const applied = await bridge.applyUpdate();
      if (!applied?.ok) {
        await alert({ title: '无法更新', description: applied?.error || '应用更新失败' });
      }
    } catch (e: any) {
      await alert({ title: '检查更新失败', description: String(e?.message || e) });
    }
  };

  const handleAnnouncement = async () => {
    try {
      const res = await bridge.fetchAnnouncement();
      const list = Array.isArray(res?.history) && res.history.length
        ? res.history
        : res?.announcement
          ? [res.announcement]
          : [];
      if (!res?.ok || !list.length) {
        await alert({ title: '更新记录', description: res?.error || '暂无公告' });
        return;
      }
      const text = list
        .map((item: any) => {
          const ver = item.version || item.id || '';
          const title = item.title || '更新';
          const body = String(item.body || '').trim();
          return `[${ver}] ${title}${body ? `\n${body}` : ''}`;
        })
        .join('\n\n────────\n\n');
      await alert({ title: '更新记录', description: text });
      const latestId = list[0]?.version || list[0]?.id;
      if (latestId) {
        try {
          localStorage.setItem('nexuz.announcementReadId', String(latestId));
        } catch {
          /* ignore */
        }
        setAnnDot(false);
      }
    } catch (e: any) {
      await alert({ title: '获取公告失败', description: String(e?.message || e) });
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
      className="relative h-14 border-b z-40 shrink-0">
      {/* True-centered primary actions */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20">
        <div className="flex items-center gap-1 bg-black/5 dark:bg-white/5 p-1 rounded-2xl border border-black/10 dark:border-white/10">
          <Button
            size="sm"
            onClick={onRunWorkflow}
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
            <span>
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
              onClick={onPause}
              disabled={execStatus !== 'running'}
              title="暂停（X+F5）"
            >
              <Pause className="w-3.5 h-3.5" />
              <span>暂停</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={onStop}
            disabled={execStatus === 'idle' && !recording}
            title="停止（X+F4）"
          >
            <Square className="w-3 h-3" />
            <span>{execStatus === 'stopping' ? '停止中' : '停止'}</span>
          </Button>

          {onForceReset ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onForceReset}
              title="卡住时点这里：强制清运行/录制状态，回到可运行"
              style={{ color: colors.danger }}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>重置</span>
            </Button>
          ) : null}

          {onToggleDebug && (
            <Button
              variant="ghost"
              size="sm"
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
              <span>{debugMode ? '调试中' : '调试'}</span>
            </Button>
          )}

          <div className="w-px h-5 bg-black/15 dark:bg-white/15 mx-0.5" />

          <Button variant="ghost" size="sm" onClick={handleSave} title="保存">
            {isSaved ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" />
            ) : (
              <Save className="w-3.5 h-3.5 opacity-80" />
            )}
            <span className={isSaved ? 'text-emerald-500' : undefined}>{isSaved ? '已保存' : '保存'}</span>
          </Button>

          {onOpen && (
            <Button variant="ghost" size="sm" onClick={onOpen} title="打开">
              <FolderOpen className="w-3.5 h-3.5 opacity-80" />
              <span>打开</span>
            </Button>
          )}

          {onToggleRecord && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggleRecord}
              style={{ color: recording ? colors.danger : undefined }}
              title={recording ? '停止录制' : '录制操作：把鼠标/键盘转成流程节点'}>
              <CircleDot className={`w-3.5 h-3.5 ${recording ? 'animate-pulse' : ''}`} />
              <span>{recording ? '停止录制' : '录制'}</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={onClearCanvas}
            style={{ color: colors.danger }}
            title="清空画布">
            <Trash2 className="w-3.5 h-3.5" />
            <span>清空</span>
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
            onClick={() => void handleAnnouncement()}
            title="更新公告">
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
              <Button variant="ghost" size="icon" className="h-8 w-8" title="主题色">
                <Palette className="w-4 h-4 opacity-80" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuLabel>主题色</DropdownMenuLabel>
              {themes.map(t => (
                <DropdownMenuItem key={t} onClick={() => setThemeName(t)}>
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

          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 px-0"
            onClick={() => setThemeMode(themeMode === 'light' ? 'dark' : 'light')}
            title={themeMode === 'light' ? '切换暗色' : '切换亮色'}>
            {themeMode === 'light' ? (
              <Moon className="w-4 h-4 opacity-80" />
            ) : (
              <Sun className="w-4 h-4 opacity-80" />
            )}
          </Button>

          <div className="flex items-center ml-1 pl-1 border-l border-black/10 dark:border-white/10">
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
    </header>
  );
}
