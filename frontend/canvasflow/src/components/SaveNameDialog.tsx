/**
 * Simple modal to name a flow before save.
 */
import React, { useEffect, useState } from 'react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function SaveNameDialog({
  open,
  initialName,
  themeName,
  themeMode,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  initialName?: string;
  themeName: ThemeName;
  themeMode: ThemeMode;
  onCancel: () => void;
  onConfirm: (name: string) => void;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const [name, setName] = useState(initialName || '');

  useEffect(() => {
    if (open) setName(initialName || '');
  }, [open, initialName]);

  if (!open) return null;

  const submit = () => {
    const n = name.trim();
    if (!n) return;
    onConfirm(n);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/45 backdrop-blur-sm">
      <div
        style={{ backgroundColor: colors.surface, borderColor: colors.border, color: colors.text }}
        className="w-[min(420px,92vw)] rounded-2xl border shadow-2xl p-5 space-y-4"
        role="dialog"
        aria-modal
      >
        <div>
          <h3 className="font-display font-semibold text-base">保存流程</h3>
          <p style={{ color: colors.secondaryText }} className="text-xs mt-1">
            输入名称后保存到 flows 目录，可在左侧「流程管理」中打开。
          </p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs">流程名称</Label>
          <Input
            autoFocus
            value={name}
            placeholder="例如：登录自动化"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
              if (e.key === 'Escape') onCancel();
            }}
          />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button type="button" onClick={submit} disabled={!name.trim()}>
            保存
          </Button>
        </div>
      </div>
    </div>
  );
}
