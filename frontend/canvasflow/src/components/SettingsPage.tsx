/**
 * App settings page — behavior / window prefs (not buried in Inspector).
 */
import React from 'react';
import { EyeOff, Monitor, Settings2 } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { useFlowStore } from '@/store/flowModelStore';

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
