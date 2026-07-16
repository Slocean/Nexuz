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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Loader2 } from 'lucide-react';

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
        const description = opts?.description || '';
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

export function AppDialogProvider({ children }: { children: React.ReactNode }) {
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

  return (
    <DialogCtx.Provider value={api}>
      {children}

      <AlertDialog
        open={!!confirmState?.open}
        onOpenChange={(open) => {
          // Only treat dismiss (overlay / Esc) as cancel; Action/Cancel handle themselves.
          if (!open && confirmResolver.current) finishConfirm(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmState?.title}</AlertDialogTitle>
            <AlertDialogDescription className="whitespace-pre-wrap">
              {confirmState?.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
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
        </AlertDialogContent>
      </AlertDialog>

      <Dialog
        open={!!alertState?.open}
        onOpenChange={(open) => {
          if (!open && alertResolver.current && !alertState?.loading) finishAlert();
        }}
      >
        <DialogContent
          showClose={!alertState?.loading}
          onPointerDownOutside={(e) => {
            if (alertState?.loading) e.preventDefault();
          }}
          onEscapeKeyDown={(e) => {
            if (alertState?.loading) e.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>{alertState?.title}</DialogTitle>
            <DialogDescription asChild>
              <div className="text-sm text-[var(--muted-foreground)]">
                {alertState?.loading ? (
                  <div className="flex items-center gap-2 py-1">
                    <Loader2 className="w-4 h-4 animate-spin shrink-0" />
                    <span className="whitespace-pre-wrap">
                      {alertState?.description || '加载中…'}
                    </span>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap">{alertState?.description}</p>
                )}
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            {alertState?.loading ? (
              <Button type="button" variant="ghost" disabled>
                请稍候…
              </Button>
            ) : (
              <Button type="button" onClick={finishAlert}>
                {alertState?.okText}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DialogCtx.Provider>
  );
}
