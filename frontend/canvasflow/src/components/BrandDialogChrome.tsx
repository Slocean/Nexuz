/**
 * Shared chrome for notice / update dialogs — brand logos + glass frame.
 */
import React from 'react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';

type Props = {
  themeName: ThemeName;
  themeMode: ThemeMode;
  eyebrow?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
};

export default function BrandDialogChrome({
  themeName,
  themeMode,
  eyebrow,
  icon,
  children,
  footer,
  className = '',
}: Props) {
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

      {footer ? <div className="relative mt-4 flex flex-col-reverse sm:flex-row sm:justify-end gap-2">{footer}</div> : null}
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
