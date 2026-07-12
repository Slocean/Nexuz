import React, { useEffect, useState } from 'react';
import {
  Play,
  Save,
  Sun,
  Moon,
  Sparkles,
  Palette,
  Workflow,
  RefreshCw,
  Check,
  FolderOpen,
  CircleDot,
  Pause,
  Square,
  Trash2,
  StepForward,
  LayoutGrid,
  FileCode2,
  Settings2,
  Minus,
  Maximize2,
  Minimize2,
  X,
} from 'lucide-react';
import { ThemeName, ThemeMode } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { bridge } from '@/bridge';

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
  onStep?: () => void;
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
  onStep,
  execStatus = 'idle',
  viewMode = 'canvas',
  onViewModeChange,
}: ToolbarProps) {
  const [isSaved, setIsSaved] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const colors = getThemeColors(themeName, themeMode);
  const themes: ThemeName[] = ['Ocean', 'Mint', 'Purple', 'Rose', 'Orange'];

  useEffect(() => {
    bridge.windowIsMaximized?.().then((res: any) => {
      if (res?.maximized != null) setMaximized(!!res.maximized);
    });
  }, []);

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
    else setMaximized((v) => !v);
  };
  const onWinClose = (e: React.MouseEvent) => {
    e.stopPropagation();
    bridge.windowClose();
  };

  return (
    <header
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      className="relative h-14 border-b z-40 shrink-0"
    >
      {/* True-centered primary actions */}
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-20">
        <div className="flex items-center gap-1 bg-black/5 dark:bg-white/5 p-1 rounded-2xl border border-white/5">
          <Button
            size="sm"
            onClick={onRunWorkflow}
            disabled={isExecuting}
            style={{
              backgroundColor: isExecuting ? colors.secondaryText + '20' : colors.primary,
              color: '#FFFFFF',
            }}
          >
            {isExecuting ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5 fill-current" />
            )}
            <span>{isExecuting ? '运行中' : '运行'}</span>
          </Button>

          {execStatus === 'paused' ? (
            <Button variant="ghost" size="sm" onClick={onResume} title="继续">
              <Play className="w-3.5 h-3.5" />
              <span>继续</span>
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={onPause}
              disabled={!isExecuting}
              title="暂停"
            >
              <Pause className="w-3.5 h-3.5" />
              <span>暂停</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={onStop}
            disabled={execStatus === 'idle'}
            title="停止"
          >
            <Square className="w-3 h-3" />
            <span>停止</span>
          </Button>

          {onStep && (
            <Button variant="ghost" size="sm" onClick={onStep} title="单步">
              <StepForward className="w-3.5 h-3.5" />
              <span>单步</span>
            </Button>
          )}

          <div className="w-px h-5 bg-white/10 mx-0.5" />

          <Button variant="ghost" size="sm" onClick={handleSave} title="保存">
            {isSaved ? (
              <Check className="w-3.5 h-3.5 text-emerald-500" />
            ) : (
              <Save className="w-3.5 h-3.5 opacity-80" />
            )}
            <span className={isSaved ? 'text-emerald-500' : undefined}>
              {isSaved ? '已保存' : '保存'}
            </span>
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
              title={recording ? '停止录制' : '录制操作：把鼠标/键盘转成流程节点'}
            >
              <CircleDot className={`w-3.5 h-3.5 ${recording ? 'animate-pulse' : ''}`} />
              <span>{recording ? '停止录制' : '录制'}</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={onClearCanvas}
            style={{ color: colors.danger }}
            title="清空画布"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>清空</span>
          </Button>
        </div>
      </div>

      <div className="relative z-10 h-full flex items-center justify-between px-2">
        {/* Left: brand + theme / light-dark */}
        <div className="flex items-center gap-1.5 min-w-0 shrink-0 z-10">
          <div className="pywebview-drag-region flex items-center gap-2 pl-1 pr-2">
            {onBackToMain && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="pywebview-no-drag"
                onClick={onBackToMain}
              >
                主程序
              </Button>
            )}
            <div
              style={{ backgroundColor: colors.primary + '1A' }}
              className="h-8 w-8 rounded-xl flex items-center justify-center shrink-0"
              title="Nexuz"
            >
              <Workflow style={{ color: colors.primary }} className="w-4 h-4" />
            </div>
            <span className="font-display font-semibold text-sm tracking-wide opacity-90 select-none">
              Nexuz
            </span>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="主题色">
                <Palette className="w-4 h-4 opacity-80" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-44">
              <DropdownMenuLabel>主题色</DropdownMenuLabel>
              {themes.map((t) => (
                <DropdownMenuItem key={t} onClick={() => setThemeName(t)}>
                  <span
                    style={{ backgroundColor: getThemeColors(t, themeMode).primary }}
                    className="w-3 h-3 rounded-full border border-white/20"
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
            title={themeMode === 'light' ? '切换暗色' : '切换亮色'}
          >
            {themeMode === 'light' ? (
              <Moon className="w-4 h-4 opacity-80" />
            ) : (
              <Sun className="w-4 h-4 opacity-80" />
            )}
          </Button>

          {onViewModeChange && (
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2.5"
              onClick={() => onViewModeChange('settings')}
              title="设置"
              style={
                viewMode === 'settings'
                  ? {
                      backgroundColor: colors.primary + '22',
                      color: colors.primary,
                    }
                  : undefined
              }
            >
              <Settings2 className="w-4 h-4 opacity-80" />
              <span>设置</span>
            </Button>
          )}
        </div>

        {/* Drag filler */}
        <div className="pywebview-drag-region flex-1 self-stretch min-w-[24px] mx-2" />

        {/* Right: view / AI + window */}
        <div className="flex items-center gap-1 shrink-0 z-10">
          {onViewModeChange && (
            <div className="flex items-center gap-1 bg-black/5 dark:bg-white/5 p-1 rounded-2xl border border-white/5">
              <Button
                size="sm"
                className="h-8 px-2.5"
                onClick={() => onViewModeChange('canvas')}
                title="画布"
                style={
                  viewMode === 'canvas'
                    ? { backgroundColor: colors.primary, color: '#FFFFFF' }
                    : { backgroundColor: 'transparent', color: colors.text }
                }
                variant="ghost"
              >
                <LayoutGrid className="w-3.5 h-3.5" />
                <span>画布</span>
              </Button>
              <Button
                size="sm"
                className="h-8 px-2.5"
                onClick={() => onViewModeChange('code')}
                title="JSON"
                style={
                  viewMode === 'code'
                    ? { backgroundColor: colors.primary, color: '#FFFFFF' }
                    : { backgroundColor: 'transparent', color: colors.text }
                }
                variant="ghost"
              >
                <FileCode2 className="w-3.5 h-3.5" />
                <span>JSON</span>
              </Button>
            </div>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onToggleAssistant}
            title="Flow AI"
            style={isAssistantOpen ? { color: colors.primary } : undefined}
          >
            <Sparkles className="w-4 h-4" />
          </Button>

          <div className="flex items-center ml-1 pl-1 border-l border-white/10">
            <button
              type="button"
              onClick={onWinMinimize}
              title="最小化"
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
            >
              <Minus className="w-4 h-4 opacity-80" />
            </button>
            <button
              type="button"
              onClick={onWinMaximize}
              title={maximized ? '还原' : '最大化'}
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
            >
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
              className="h-8 w-9 inline-flex items-center justify-center rounded-lg hover:bg-rose-500 hover:text-white transition-colors"
            >
              <X className="w-4 h-4 opacity-90" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
