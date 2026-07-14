/**
 * Save flow name — shadcn Dialog.
 */
import React, { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export default function SaveNameDialog({
  open,
  initialName,
  onCancel,
  onConfirm,
  title = '保存流程',
  description = '输入名称后保存到 flows 目录，可在左侧「流程管理」中打开。',
  label = '流程名称',
  confirmText = '保存',
  placeholder = '例如：登录自动化',
}: {
  open: boolean;
  initialName?: string;
  onCancel: () => void;
  onConfirm: (name: string) => void;
  title?: string;
  description?: string;
  label?: string;
  confirmText?: string;
  placeholder?: string;
}) {
  const [name, setName] = useState(initialName || '');

  useEffect(() => {
    if (open) setName(initialName || '');
  }, [open, initialName]);

  const submit = () => {
    const n = name.trim();
    if (!n) return;
    onConfirm(n);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label className="text-xs">{label}</Label>
          <Input
            autoFocus
            value={name}
            placeholder={placeholder}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            取消
          </Button>
          <Button type="button" onClick={submit} disabled={!name.trim()}>
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
