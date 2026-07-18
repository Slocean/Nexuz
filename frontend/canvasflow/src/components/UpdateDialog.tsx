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
import { Button } from '@/components/ui/button';
import { bridge } from '@/bridge';
import { ArrowUpCircle, CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import { useFlowStore } from '@/store/flowModelStore';
import BrandDialog from './BrandDialog';

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
  asset_ready?: boolean;
  asset_pending?: boolean;
  asset_error?: string | null;
};

type Phase = 'checking' | 'info' | 'downloading' | 'ready' | 'applying' | 'uptodate' | 'error';

type UpdateDialogApi = {
  /** Opens the dialog immediately. Without preset, shows loading then fetches. Returns check result. */
  openUpdate: (info?: UpdateCheckInfo | null) => Promise<UpdateCheckInfo | null>;
};

const UpdateCtx = createContext<UpdateDialogApi | null>(null);

export function useUpdateDialog(): UpdateDialogApi {
  const ctx = useContext(UpdateCtx);
  if (!ctx) {
    return {
      openUpdate: async () => {
        console.warn('UpdateDialogProvider missing');
        return null;
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
  dark,
}: {
  statusText: string;
  percent: number | null;
  spinning: boolean;
  hint?: string;
  dark: boolean;
}) {
  const showIndeterminate = spinning && percent == null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-sm">
        {spinning ? <Loader2 className="w-4 h-4 animate-spin shrink-0 text-sky-400" /> : null}
        <span className={dark ? 'text-slate-200' : 'text-slate-700'}>{statusText}</span>
        {percent != null ? (
          <span className="font-mono ml-auto text-sky-400 tabular-nums">{percent}%</span>
        ) : null}
      </div>
      <div
        className={`h-1.5 w-full rounded-full overflow-hidden relative ${
          dark ? 'bg-white/10' : 'bg-slate-200/80'
        }`}
      >
        {showIndeterminate ? (
          <div className="absolute inset-y-0 w-2/5 rounded-full bg-[var(--primary)] nexuz-indeterminate-bar" />
        ) : (
          <div
            className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
            style={{ width: `${percent ?? 0}%` }}
          />
        )}
      </div>
      {hint ? (
        <p className={`text-xs leading-relaxed ${dark ? 'text-slate-400' : 'text-slate-500'}`}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function UpdateDialogProvider({ children }: { children: React.ReactNode }) {
  const themeMode = useFlowStore((s) => s.themeMode);
  const dark = themeMode === 'dark';

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

  const busy = phase === 'checking' || phase === 'downloading' || phase === 'applying';

  const close = useCallback(() => {
    if (busy) return;
    setOpen(false);
  }, [busy]);

  const openUpdate = useCallback(async (preset?: UpdateCheckInfo | null): Promise<UpdateCheckInfo | null> => {
    setError('');
    setPercent(null);
    setStatusText('');
    setInfo(null);

    let data = preset || null;
    if (!data) {
      setOpen(true);
      setPhase('checking');
      setStatusText('正在检查更新…');
      try {
        const res = await bridge.checkForUpdate();
        if (!res?.ok) {
          setPhase('error');
          setError(res?.error || '检查更新失败');
          return res || { ok: false, error: '检查更新失败' };
        }
        if (!res.update_available) {
          const uptodate: UpdateCheckInfo = {
            ok: true,
            update_available: false,
            current_version: res.current_version,
            latest_version: res.latest_version,
            message: res.message || '已是最新版本',
          };
          setInfo(uptodate);
          setPhase('uptodate');
          return uptodate;
        }
        data = res;
      } catch (e: any) {
        const err = String(e?.message || e || '检查更新失败');
        setPhase('error');
        setError(err);
        return { ok: false, error: err };
      }
    } else if (data.update_available === false) {
      setInfo(data);
      setPhase('uptodate');
      setOpen(true);
      return data;
    } else if (data.ok === false) {
      setInfo(data);
      setPhase('error');
      setError(data.error || '检查更新失败');
      setOpen(true);
      return data;
    }

    setInfo(data);
    setPhase('info');
    setOpen(true);
    return data;
  }, []);

  const startDownload = async () => {
    if (!info) return;
    if (info.asset_ready === false || (!info.download_url && info.asset_pending)) {
      setPhase('error');
      setError(
        info.asset_error ||
          info.message ||
          `新版本 ${info.latest_version || ''} 的安装包尚未上传完成，请稍后再试。`,
      );
      return;
    }
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
      : phase === 'checking'
        ? '检查更新'
        : phase === 'downloading'
          ? '正在下载更新'
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
    phase === 'checking' || phase === 'downloading' || phase === 'ready' || phase === 'applying';

  const ghostOutline = dark
    ? 'border-white/15 bg-white/5 hover:bg-white/10 text-slate-100'
    : undefined;

  const footer = (
    <>
      {phase === 'info' ? (
        <>
          <Button type="button" variant="outline" className={ghostOutline} onClick={() => setOpen(false)}>
            稍后
          </Button>
          {info?.asset_ready === false ? (
            <Button
              type="button"
              variant="outline"
              className={ghostOutline}
              onClick={() => void bridge.openReleasesPage()}
            >
              打开 Releases
            </Button>
          ) : (
            <Button type="button" onClick={() => void startDownload()}>
              下载更新
            </Button>
          )}
        </>
      ) : null}

      {phase === 'ready' ? (
        <>
          <Button type="button" variant="outline" className={ghostOutline} onClick={() => setOpen(false)}>
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
              className={ghostOutline}
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
        <Button type="button" variant="ghost" disabled className="opacity-60">
          请稍候…
        </Button>
      ) : null}
    </>
  );

  return (
    <UpdateCtx.Provider value={api}>
      {children}

      <BrandDialog
        open={open}
        onOpenChange={(v) => {
          if (!v) close();
        }}
        dismissLocked={busy}
        a11yTitle={title}
        a11yDescription={statusText || title}
        eyebrow="Update Channel"
        icon={<ArrowUpCircle className="w-3 h-3" />}
        footer={footer}
      >
        <div className="flex items-start gap-2">
          {phase === 'uptodate' ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          ) : phase === 'error' ? null : (
            <Sparkles className="w-5 h-5 text-sky-400 shrink-0 mt-0.5" />
          )}
          <h3 className="text-base font-semibold tracking-tight leading-snug">{title}</h3>
        </div>

        {info?.current_version && info?.latest_version && phase !== 'error' && phase !== 'uptodate' ? (
          <div
            className={`inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5 font-mono text-xs ${
              dark ? 'border-white/10 bg-white/[0.04] text-slate-200' : 'border-slate-200 bg-white/80 text-slate-700'
            }`}
          >
            <span className="opacity-60">{info.current_version}</span>
            <span className="text-sky-400">→</span>
            <span className="text-fuchsia-400">{info.latest_version}</span>
          </div>
        ) : null}

        {phase === 'uptodate' ? (
          <p className={`text-sm leading-relaxed ${dark ? 'text-slate-300' : 'text-slate-600'}`}>
            当前版本{' '}
            <span className="font-mono text-sky-500">{info?.current_version || '?'}</span>
            ，已是最新。
          </p>
        ) : null}

        {notes && (phase === 'info' || phase === 'ready') ? (
          <div
            className={`whitespace-pre-wrap max-h-40 overflow-y-auto rounded-xl border px-3 py-2.5 text-xs leading-relaxed ${
              dark
                ? 'border-white/10 bg-black/25 text-slate-300'
                : 'border-slate-200/80 bg-white/70 text-slate-600'
            }`}
          >
            {notes}
          </div>
        ) : null}

        {phase === 'info' && info?.update_available && info.asset_ready === false ? (
          <p className="text-amber-500 text-xs leading-relaxed">
            {info.asset_error ||
              '安装包还在发布中（或上次发版失败）。此时下载会拿到旧包，请等 Release 上传完成后再更新。'}
          </p>
        ) : null}

        {showProgress ? (
          <div
            className={`rounded-xl border px-3 py-2.5 ${
              dark ? 'border-white/10 bg-white/[0.04]' : 'border-slate-200/80 bg-white/70'
            }`}
          >
            <ProgressBlock
              dark={dark}
              statusText={
                statusText ||
                (phase === 'checking'
                  ? '正在检查更新…'
                  : phase === 'ready'
                    ? '下载完成'
                    : phase === 'applying'
                      ? '正在重启…'
                      : '下载中…')
              }
              percent={phase === 'checking' ? null : percent}
              spinning={busy}
              hint={
                phase === 'ready'
                  ? '更新包已就绪。请先保存流程，然后点「立即更新」：程序会退出，用新 exe 替换旧文件并自动重启。'
                  : phase === 'applying'
                    ? '请勿手动结束进程。若失败会弹窗提示，日志在程序目录 nexuz_update.log。'
                    : undefined
              }
            />
          </div>
        ) : null}

        {phase === 'error' && error ? (
          <p className="whitespace-pre-wrap text-sm text-rose-400 leading-relaxed">{error}</p>
        ) : null}
      </BrandDialog>

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
