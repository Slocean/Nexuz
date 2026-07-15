/**
 * Single-dialog update flow: info → downloading (progress) → ready (apply) → applying.
 *
 * Update mechanism (portable Nexuz.exe, not an installer):
 *   download → Nexuz_update.exe beside current exe
 *   apply → helper waits for exit → rename-swap → start new Nexuz.exe
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { bridge } from '@/bridge';
import { Loader2 } from 'lucide-react';

export type UpdateCheckInfo = {
  ok?: boolean;
  update_available?: boolean;
  current_version?: string;
  latest_version?: string;
  release_notes?: string;
  download_url?: string | null;
  html_url?: string;
  message?: string;
  error?: string;
};

type Phase = 'info' | 'downloading' | 'ready' | 'applying' | 'uptodate' | 'error';

type UpdateDialogApi = {
  openUpdate: (info?: UpdateCheckInfo | null) => Promise<void>;
};

const UpdateCtx = createContext<UpdateDialogApi | null>(null);

export function useUpdateDialog(): UpdateDialogApi {
  const ctx = useContext(UpdateCtx);
  if (!ctx) {
    return {
      openUpdate: async () => {
        console.warn('UpdateDialogProvider missing');
      },
    };
  }
  return ctx;
}

function formatNotes(notes: string | undefined, max = 500) {
  const t = String(notes || '').trim();
  if (!t) return '';
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

function ProgressBlock({
  statusText,
  percent,
  spinning,
  hint,
}: {
  statusText: string;
  percent: number | null;
  spinning: boolean;
  hint?: string;
}) {
  const showIndeterminate = spinning && percent == null;
  return (
    <div className="space-y-2 pt-1">
      <div className="flex items-center gap-2 text-sm">
        {spinning ? <Loader2 className="w-4 h-4 animate-spin shrink-0" /> : null}
        <span>{statusText}</span>
        {percent != null ? <span className="font-mono ml-auto">{percent}%</span> : null}
      </div>
      <div className="h-2 w-full rounded-full bg-black/10 dark:bg-white/10 overflow-hidden relative">
        {showIndeterminate ? (
          <div className="absolute inset-y-0 w-2/5 rounded-full bg-[var(--primary)] nexuz-indeterminate-bar" />
        ) : (
          <div
            className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
            style={{ width: `${percent ?? 0}%` }}
          />
        )}
      </div>
      {hint ? <p className="text-xs opacity-80">{hint}</p> : null}
    </div>
  );
}

export function UpdateDialogProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>('info');
  const [info, setInfo] = useState<UpdateCheckInfo | null>(null);
  const [error, setError] = useState('');
  const [percent, setPercent] = useState<number | null>(null);
  const [statusText, setStatusText] = useState('');

  useEffect(() => {
    const onProgress = (ev: Event) => {
      const d = (ev as CustomEvent).detail || {};
      const p = d.percent;
      if (typeof p === 'number' && Number.isFinite(p)) {
        setPercent(Math.max(0, Math.min(100, Math.round(p))));
      }
      if (d.message) setStatusText(String(d.message));
    };
    window.addEventListener('nexuz-update-progress', onProgress as EventListener);
    return () => window.removeEventListener('nexuz-update-progress', onProgress as EventListener);
  }, []);

  const busy = phase === 'downloading' || phase === 'applying';

  const close = useCallback(() => {
    if (busy) return;
    setOpen(false);
  }, [busy]);

  const openUpdate = useCallback(async (preset?: UpdateCheckInfo | null) => {
    setError('');
    setPercent(null);
    setStatusText('');
    setPhase('info');

    let data = preset || null;
    if (!data) {
      setOpen(true);
      setPhase('downloading');
      setStatusText('正在检查更新…');
      try {
        const res = await bridge.checkForUpdate();
        if (!res?.ok) {
          setPhase('error');
          setError(res?.error || '检查更新失败');
          return;
        }
        if (!res.update_available) {
          setInfo({
            current_version: res.current_version,
            latest_version: res.latest_version,
            message: res.message || '已是最新版本',
          });
          setPhase('uptodate');
          return;
        }
        data = res;
      } catch (e: any) {
        setPhase('error');
        setError(String(e?.message || e || '检查更新失败'));
        return;
      }
    } else if (data.update_available === false) {
      setInfo(data);
      setPhase('uptodate');
      setOpen(true);
      return;
    } else if (data.ok === false) {
      setInfo(data);
      setPhase('error');
      setError(data.error || '检查更新失败');
      setOpen(true);
      return;
    }

    setInfo(data);
    setPhase('info');
    setOpen(true);
  }, []);

  const startDownload = async () => {
    if (!info) return;
    setPhase('downloading');
    setPercent(null);
    setStatusText('正在下载更新包…');
    setError('');
    try {
      const dl = await bridge.downloadUpdate(info.download_url || null);
      if (!dl?.ok) {
        setPhase('error');
        setError(dl?.error || '下载失败');
        return;
      }
      setPercent(100);
      setStatusText(dl.message || '下载完成（100%）');
      setPhase('ready');
    } catch (e: any) {
      setPhase('error');
      setError(String(e?.message || e || '下载失败'));
    }
  };

  const startApply = async () => {
    setPhase('applying');
    setPercent(100);
    setStatusText('正在退出并替换程序文件…');
    setError('');
    try {
      const res = await bridge.applyUpdate();
      if (!res?.ok) {
        setPhase('error');
        setError(res?.error || '应用更新失败');
        return;
      }
      setPercent(100);
      setStatusText(res.message || '即将重启…');
    } catch (e: any) {
      setPhase('error');
      setError(String(e?.message || e || '应用更新失败'));
    }
  };

  const api = useMemo(() => ({ openUpdate }), [openUpdate]);

  const notes = formatNotes(info?.release_notes);
  const title =
    phase === 'ready'
      ? '下载完成'
      : phase === 'downloading'
        ? statusText.includes('检查')
          ? '检查更新'
          : '正在下载更新'
        : phase === 'applying'
          ? '正在应用更新'
          : phase === 'uptodate'
            ? '已是最新版本'
            : phase === 'error'
              ? '更新失败'
              : info?.latest_version
                ? `发现新版本 ${info.latest_version}`
                : '检查更新';

  const showProgress =
    phase === 'downloading' || phase === 'ready' || phase === 'applying';

  return (
    <UpdateCtx.Provider value={api}>
      {children}

      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!v) close();
        }}
      >
        <DialogContent
          showClose={!busy}
          className="sm:max-w-md"
          onPointerDownOutside={(e) => {
            if (busy) e.preventDefault();
          }}
          onEscapeKeyDown={(e) => {
            if (busy) e.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-3 text-sm text-[var(--muted-foreground)]">
                {info?.current_version && info?.latest_version && phase !== 'error' && phase !== 'uptodate' ? (
                  <p>
                    当前 <span className="font-mono">{info.current_version}</span>
                    {' → '}
                    <span className="font-mono">{info.latest_version}</span>
                  </p>
                ) : null}

                {phase === 'uptodate' ? (
                  <p>
                    当前版本{' '}
                    <span className="font-mono">{info?.current_version || '?'}</span>
                    ，已是最新。
                  </p>
                ) : null}

                {notes && (phase === 'info' || phase === 'ready') ? (
                  <p className="whitespace-pre-wrap max-h-40 overflow-y-auto rounded-md border border-black/10 dark:border-white/10 p-2 text-xs leading-relaxed">
                    {notes}
                  </p>
                ) : null}

                {showProgress ? (
                  <ProgressBlock
                    statusText={
                      statusText ||
                      (phase === 'ready'
                        ? '下载完成'
                        : phase === 'applying'
                          ? '正在重启…'
                          : '下载中…')
                    }
                    percent={phase === 'downloading' && statusText.includes('检查') ? null : percent}
                    spinning={busy}
                    hint={
                      phase === 'ready'
                        ? '更新包已就绪。请先保存流程，然后点「立即更新」：程序会退出，用新 exe 替换旧文件并自动重启。'
                        : phase === 'applying'
                          ? '请勿手动结束进程。若失败会弹窗提示，日志在程序目录 nexuz_update.log。'
                          : undefined
                    }
                  />
                ) : null}

                {phase === 'error' && error ? (
                  <p className="whitespace-pre-wrap text-sm text-rose-600 dark:text-rose-400">
                    {error}
                  </p>
                ) : null}
              </div>
            </DialogDescription>
          </DialogHeader>

          <DialogFooter className="gap-2 sm:gap-2">
            {phase === 'info' ? (
              <>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  稍后
                </Button>
                <Button type="button" onClick={() => void startDownload()}>
                  下载更新
                </Button>
              </>
            ) : null}

            {phase === 'ready' ? (
              <>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  稍后
                </Button>
                <Button type="button" onClick={() => void startApply()}>
                  立即更新
                </Button>
              </>
            ) : null}

            {(phase === 'error' || phase === 'uptodate') && (
              <>
                {phase === 'error' ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void bridge.openReleasesPage()}
                  >
                    打开 Releases
                  </Button>
                ) : null}
                <Button type="button" onClick={() => setOpen(false)}>
                  关闭
                </Button>
              </>
            )}

            {busy ? (
              <Button type="button" variant="ghost" disabled>
                请稍候…
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <style>{`
        @keyframes nexuz-indeterminate {
          0% { left: -40%; }
          100% { left: 100%; }
        }
        .nexuz-indeterminate-bar {
          animation: nexuz-indeterminate 1.1s ease-in-out infinite;
        }
      `}</style>
    </UpdateCtx.Provider>
  );
}
