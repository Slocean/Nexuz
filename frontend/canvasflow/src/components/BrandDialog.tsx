/**
 * Shared branded dialog shell for notice / update (and confirm chrome).
 * Logo header + eyebrow + Dialog / AlertDialog content styling.
 */
import React from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog';
import { ThemeMode } from '../types';
import { getThemeColors } from '../theme';
import { useFlowStore } from '@/store/flowModelStore';

type ChromeProps = {
  eyebrow?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
};

/** Inner brand frame (logos + eyebrow). Use inside AlertDialogContent or via BrandDialog. */
export function BrandDialogChrome({
  eyebrow,
  icon,
  children,
  footer,
  className = '',
}: ChromeProps) {
  const themeName = useFlowStore((s) => s.themeName);
  const themeMode = useFlowStore((s) => s.themeMode);
  const colors = getThemeColors(themeName, themeMode);
  const dark = themeMode === 'dark';

  return (
    <div className={`relative overflow-hidden ${className}`}>
      <div className="relative flex items-start gap-3 mb-3.5 pr-6">
        <img
          src={`${import.meta.env.BASE_URL}logo.png`}
          alt=""
          className="h-11 w-11 object-contain shrink-0"
          draggable={false}
        />
        <div className="min-w-0 flex-1 pt-0.5">
          <img
            src={`${import.meta.env.BASE_URL}logo2.png`}
            alt="Nexuz"
            className="h-5 w-auto max-w-[8.5rem] object-contain object-left"
            draggable={false}
          />
          {(eyebrow || icon) && (
            <div
              className="mt-1.5 flex items-center gap-1.5 text-[11px] tracking-[0.14em] uppercase"
              style={{ color: dark ? 'rgba(148,163,184,0.95)' : colors.secondaryText }}
            >
              {icon}
              {eyebrow}
            </div>
          )}
        </div>
      </div>

      <div
        className="relative h-px w-full mb-3.5"
        style={{
          background: dark
            ? 'linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent)'
            : 'linear-gradient(90deg, transparent, rgba(0,0,0,0.08), transparent)',
        }}
      />

      <div className="relative space-y-3">{children}</div>

      {footer ? (
        <div className="relative mt-4 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">{footer}</div>
      ) : null}
    </div>
  );
}

export function brandDialogContentClass(themeMode: ThemeMode) {
  const dark = themeMode === 'dark';
  return [
    'sm:max-w-md overflow-hidden p-0 gap-0 border',
    dark
      ? 'bg-[var(--popover)] border-white/10 text-slate-100 shadow-2xl'
      : 'bg-[var(--popover)] border-black/10 text-slate-800 shadow-2xl',
  ].join(' ');
}

type BrandDialogProps = ChromeProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When true: hide close, block outside click / Escape */
  dismissLocked?: boolean;
  a11yTitle: string;
  a11yDescription?: string;
};

/** Full branded Dialog used by notice + update flows. */
export default function BrandDialog({
  open,
  onOpenChange,
  dismissLocked = false,
  a11yTitle,
  a11yDescription = '',
  eyebrow,
  icon,
  children,
  footer,
  className,
}: BrandDialogProps) {
  const themeMode = useFlowStore((s) => s.themeMode);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showClose={!dismissLocked}
        className={brandDialogContentClass(themeMode) + ' p-5'}
        onPointerDownOutside={(e) => {
          if (dismissLocked) e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (dismissLocked) e.preventDefault();
        }}
      >
        <DialogTitle className="sr-only">{a11yTitle}</DialogTitle>
        <DialogDescription className="sr-only">{a11yDescription}</DialogDescription>
        <BrandDialogChrome eyebrow={eyebrow} icon={icon} footer={footer} className={className}>
          {children}
        </BrandDialogChrome>
      </DialogContent>
    </Dialog>
  );
}
