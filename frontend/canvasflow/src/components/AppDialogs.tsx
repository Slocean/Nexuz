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

type DialogApi = {
  confirm: (opts: ConfirmOpts | string) => Promise<boolean>;
  alert: (opts: AlertOpts | string) => Promise<void>;
};

const DialogCtx = createContext<DialogApi | null>(null);

export function useAppDialog(): DialogApi {
  const ctx = useContext(DialogCtx);
  if (!ctx) {
    // Fallback for components outside provider (should not happen)
    return {
      confirm: async (opts) =>
        window.confirm(typeof opts === 'string' ? opts : opts.description),
      alert: async (opts) => {
        window.alert(typeof opts === 'string' ? opts : opts.description);
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
      });
    });
  }, []);

  const api = useMemo(() => ({ confirm, alert }), [confirm, alert]);

  const finishConfirm = (v: boolean) => {
    const resolve = confirmResolver.current;
    confirmResolver.current = null;
    setConfirmState((s) => (s ? { ...s, open: false } : s));
    resolve?.(v);
  };

  const finishAlert = () => {
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
          if (!open && alertResolver.current) finishAlert();
        }}
      >
        <DialogContent showClose={false}>
          <DialogHeader>
            <DialogTitle>{alertState?.title}</DialogTitle>
            <DialogDescription className="whitespace-pre-wrap">
              {alertState?.description}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" onClick={finishAlert}>
              {alertState?.okText}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </DialogCtx.Provider>
  );
}
