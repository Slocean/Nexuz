/**
 * App-wide shadcn Dialog / AlertDialog helpers (replace window.confirm / alert).
 */
import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Bell, Loader2 } from 'lucide-react';
import { useFlowStore } from '@/store/flowModelStore';
import BrandDialog, { BrandDialogChrome, brandDialogContentClass } from './BrandDialog';

type ConfirmOpts = {
  title?: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;
};

type AlertOpts = {
  title?: string;
  description: string;
  okText?: string;
};

type OpenAlertOpts = {
  title?: string;
  description?: string;
  okText?: string;
  /** When true, show spinner and hide OK until setContent / update */
  loading?: boolean;
};

type AlertHandle = {
  /** Replace content and exit loading (user can dismiss with OK) */
  setContent: (opts: { title?: string; description: string; okText?: string }) => void;
  /** Update fields without closing; can toggle loading */
  update: (opts: Partial<OpenAlertOpts> & { description?: string }) => void;
  /** Resolves when user clicks OK (after loading ends) */
  done: Promise<void>;
};

type DialogApi = {
  confirm: (opts: ConfirmOpts | string) => Promise<boolean>;
  alert: (opts: AlertOpts | string) => Promise<void>;
  /** Open dialog immediately (optionally loading), then setContent when ready */
  openAlert: (opts?: OpenAlertOpts) => AlertHandle;
};

const DialogCtx = createContext<DialogApi | null>(null);

export function useAppDialog(): DialogApi {
  const ctx = useContext(DialogCtx);
  if (!ctx) {
    return {
      confirm: async (opts) =>
        window.confirm(typeof opts === 'string' ? opts : opts.description),
      alert: async (opts) => {
        window.alert(typeof opts === 'string' ? opts : opts.description);
      },
      openAlert: (opts) => {
        return {
          setContent: (o) => {
            window.alert(o.description);
          },
          update: () => {},
          done: Promise.resolve(),
        };
      },
    };
  }
  return ctx;
}

function noticeEyebrow(title: string): string {
  const t = String(title || '');
  if (/通知|公告|notice/i.test(t)) return 'Notice Channel';
  if (/失败|错误|error/i.test(t)) return 'System Alert';
  return 'Message';
}

export function AppDialogProvider({ children }: { children: React.ReactNode }) {
  const themeMode = useFlowStore((s) => s.themeMode);

  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    title: string;
    description: string;
    confirmText: string;
    cancelText: string;
    destructive: boolean;
  } | null>(null);
  const confirmResolver = useRef<((v: boolean) => void) | null>(null);

  const [alertState, setAlertState] = useState<{
    open: boolean;
    title: string;
    description: string;
    okText: string;
    loading: boolean;
  } | null>(null);
  const alertResolver = useRef<(() => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOpts | string) => {
    const o = typeof opts === 'string' ? { description: opts } : opts;
    return new Promise<boolean>((resolve) => {
      confirmResolver.current = resolve;
      setConfirmState({
        open: true,
        title: o.title || '请确认',
        description: o.description,
        confirmText: o.confirmText || '确定',
        cancelText: o.cancelText || '取消',
        destructive: !!o.destructive,
      });
    });
  }, []);

  const alert = useCallback((opts: AlertOpts | string) => {
    const o = typeof opts === 'string' ? { description: opts } : opts;
    return new Promise<void>((resolve) => {
      alertResolver.current = resolve;
      setAlertState({
        open: true,
        title: o.title || '提示',
        description: o.description,
        okText: o.okText || '知道了',
        loading: false,
      });
    });
  }, []);

  const openAlert = useCallback((opts?: OpenAlertOpts): AlertHandle => {
    let resolveDone: (() => void) | null = null;
    const done = new Promise<void>((resolve) => {
      resolveDone = resolve;
    });
    alertResolver.current = () => {
      resolveDone?.();
    };
    setAlertState({
      open: true,
      title: opts?.title || '提示',
      description: opts?.description || (opts?.loading ? '加载中…' : ''),
      okText: opts?.okText || '知道了',
      loading: !!opts?.loading,
    });
    return {
      setContent: (o) => {
        setAlertState((s) =>
          s
            ? {
                ...s,
                title: o.title ?? s.title,
                description: o.description,
                okText: o.okText || s.okText,
                loading: false,
              }
            : s,
        );
      },
      update: (o) => {
        setAlertState((s) =>
          s
            ? {
                ...s,
                title: o.title ?? s.title,
                description: o.description ?? s.description,
                okText: o.okText ?? s.okText,
                loading: o.loading !== undefined ? !!o.loading : s.loading,
              }
            : s,
        );
      },
      done,
    };
  }, []);

  const api = useMemo(() => ({ confirm, alert, openAlert }), [confirm, alert, openAlert]);

  const finishConfirm = (v: boolean) => {
    const resolve = confirmResolver.current;
    confirmResolver.current = null;
    setConfirmState((s) => (s ? { ...s, open: false } : s));
    resolve?.(v);
  };

  const finishAlert = () => {
    if (alertState?.loading) return;
    const resolve = alertResolver.current;
    alertResolver.current = null;
    setAlertState((s) => (s ? { ...s, open: false } : s));
    resolve?.();
  };

  const dark = themeMode === 'dark';

  return (
    <DialogCtx.Provider value={api}>
      {children}

      <AlertDialog
        open={!!confirmState?.open}
        onOpenChange={(open) => {
          if (!open && confirmResolver.current) finishConfirm(false);
        }}
      >
        <AlertDialogContent className={brandDialogContentClass(themeMode) + ' p-5'}>
          <BrandDialogChrome eyebrow="Confirm" icon={<Bell className="w-3 h-3" />}>
            <AlertDialogHeader className="p-0 space-y-2 text-left">
              <AlertDialogTitle className="text-base font-semibold tracking-tight">
                {confirmState?.title}
              </AlertDialogTitle>
              <AlertDialogDescription
                className={`whitespace-pre-wrap text-sm leading-relaxed ${
                  dark ? 'text-slate-300' : 'text-slate-600'
                }`}
              >
                {confirmState?.description}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter className="p-0 mt-1 sm:justify-end">
              <AlertDialogCancel
                className={dark ? 'border-white/15 bg-white/5 hover:bg-white/10' : undefined}
                onClick={(e) => {
                  e.preventDefault();
                  finishConfirm(false);
                }}
              >
                {confirmState?.cancelText}
              </AlertDialogCancel>
              <AlertDialogAction
                className={
                  confirmState?.destructive
                    ? 'bg-[var(--destructive)] text-white hover:opacity-90'
                    : undefined
                }
                onClick={(e) => {
                  e.preventDefault();
                  finishConfirm(true);
                }}
              >
                {confirmState?.confirmText}
              </AlertDialogAction>
            </AlertDialogFooter>
          </BrandDialogChrome>
        </AlertDialogContent>
      </AlertDialog>

      <BrandDialog
        open={!!alertState?.open}
        onOpenChange={(open) => {
          if (!open && alertResolver.current && !alertState?.loading) finishAlert();
        }}
        dismissLocked={!!alertState?.loading}
        a11yTitle={alertState?.title || '提示'}
        a11yDescription={alertState?.description || ''}
        eyebrow={noticeEyebrow(alertState?.title || '')}
        icon={<Bell className="w-3 h-3" />}
        footer={
          alertState?.loading ? (
            <Button type="button" variant="ghost" disabled className="opacity-60">
              请稍候…
            </Button>
          ) : (
            <Button type="button" onClick={finishAlert}>
              {alertState?.okText}
            </Button>
          )
        }
      >
        {alertState?.title && !/^通知$/i.test(alertState.title.trim()) ? (
          <h3 className="text-base font-semibold tracking-tight leading-snug">
            {alertState.title}
          </h3>
        ) : null}
        <div
          className={`text-sm leading-relaxed ${
            dark ? 'text-slate-200' : 'text-slate-700'
          }`}
        >
          {alertState?.loading ? (
            <div className="flex items-center gap-2 py-0.5">
              <Loader2 className="w-4 h-4 animate-spin shrink-0 text-sky-400" />
              <span className="whitespace-pre-wrap">
                {alertState?.description || '加载中…'}
              </span>
            </div>
          ) : (
            <p className="whitespace-pre-wrap">{alertState?.description}</p>
          )}
        </div>
      </BrandDialog>
    </DialogCtx.Provider>
  );
}
