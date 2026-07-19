import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Boxes, Cpu, HardDrive, Layers, Timer, Waves } from 'lucide-react';
import { bridge } from '@/bridge';

export type ResourceStats = {
  ok?: boolean;
  error?: string;
  pid?: number;
  cpu_percent?: number;
  rss_bytes?: number;
  private_bytes?: number;
  child_count?: number;
  children_rss_bytes?: number;
  threads?: number;
  uptime_s?: number;
  system_cpu_percent?: number;
  system_mem_percent?: number;
  system_mem_total_bytes?: number;
  system_mem_used_bytes?: number;
  ui_queue?: number;
  exec_running?: boolean;
  ts?: number;
};

function formatBytes(n?: number): string {
  const v = Number(n) || 0;
  if (v < 1024) return `${v} B`;
  if (v < 1024 ** 2) return `${(v / 1024).toFixed(1)} KB`;
  if (v < 1024 ** 3) return `${(v / 1024 ** 2).toFixed(1)} MB`;
  return `${(v / 1024 ** 3).toFixed(2)} GB`;
}

function formatUptime(s?: number): string {
  const t = Math.max(0, Math.floor(Number(s) || 0));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function clampPct(n?: number): number {
  const v = Number(n) || 0;
  return Math.max(0, Math.min(100, v));
}

/** System = full gray track; process = accent fill by process/system ratio; right = xx/xx */
function RatioMeter({
  label,
  icon,
  processValue,
  systemValue,
  processText,
  systemText,
  accent,
}: {
  label: string;
  icon: React.ReactNode;
  processValue: number;
  systemValue: number;
  processText: string;
  systemText: string;
  accent: string;
}) {
  const sys = Math.max(0, Number(systemValue) || 0);
  const proc = Math.max(0, Number(processValue) || 0);
  const ratio = sys > 0 ? Math.max(0, Math.min(100, (proc / sys) * 100)) : 0;
  return (
    <div className="space-y-1 min-w-0">
      <div className="flex items-center justify-between gap-2 text-[12.5px]">
        <div className="flex items-center gap-1.5 opacity-60 min-w-0">
          {icon}
          <span className="tracking-wide truncate">{label}</span>
        </div>
        <span
          className="shrink-0 font-mono tabular-nums leading-none"
          style={{ color: accent }}
        >
          {processText}/{systemText}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-white/15 overflow-hidden relative">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out relative"
          style={{
            width: `${ratio}%`,
            background: `linear-gradient(90deg, ${accent}88, ${accent})`,
            boxShadow: `0 0 12px ${accent}66`,
          }}
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-30"
          style={{
            background:
              'linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent)',
            backgroundSize: '200% 100%',
            animation: 'nexuz-hud-shine 2.4s linear infinite',
          }}
        />
      </div>
    </div>
  );
}

const HUD_STYLES = `
  @keyframes nexuz-hud-shine {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  @keyframes nexuz-hud-pulse {
    0%, 100% { opacity: 0.45; }
    50% { opacity: 1; }
  }
`;

export type ResourceMonitorPanelProps = {
  variant?: 'popover' | 'page';
  headerRight?: React.ReactNode;
  subtitle?: string;
  className?: string;
  polling?: boolean;
  /** When true, skip logo / brand row (e.g. brand already rendered above). */
  hideBrand?: boolean;
};

/** Shared resource meters — used by run monitor page (and formerly logo popover). */
export function ResourceMonitorPanel({
  variant = 'page',
  headerRight,
  subtitle = 'Resource Link',
  className = '',
  polling = true,
  hideBrand = false,
}: ResourceMonitorPanelProps) {
  const [stats, setStats] = useState<ResourceStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const alive = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const res = await bridge.getResourceStats?.();
      if (!alive.current) return;
      if (res?.ok) {
        setStats(res);
        setErr(null);
      } else {
        setErr(res?.error || '无法读取资源状态');
      }
    } catch (e: any) {
      if (!alive.current) return;
      setErr(String(e?.message || e || '读取失败'));
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    if (!polling) return undefined;
    void refresh();
    const warm = window.setTimeout(() => void refresh(), 400);
    const id = window.setInterval(() => void refresh(), 1000);
    return () => {
      alive.current = false;
      window.clearTimeout(warm);
      window.clearInterval(id);
    };
  }, [polling, refresh]);

  const appMem = (stats?.private_bytes || stats?.rss_bytes || 0) + (stats?.children_rss_bytes || 0);
  const cpu = clampPct(stats?.cpu_percent);
  const sysCpu = clampPct(stats?.system_cpu_percent);

  const shellCls =
    variant === 'page'
      ? `relative w-full select-none ${className}`
      : `absolute left-0 top-[calc(100%+6px)] z-[120] w-[19.5rem] select-none ${className}`;

  return (
    <div className={shellCls}>
      <style>{HUD_STYLES}</style>
      <div
        className={
          variant === 'page'
            ? 'relative overflow-hidden rounded-none border-0'
            : 'relative overflow-hidden rounded-2xl border shadow-2xl backdrop-blur-xl'
        }
        style={{
          background: 'rgba(12, 14, 20, 0.96)',
          borderColor: 'rgba(255, 255, 255, 0.12)',
          boxShadow: variant === 'page' ? 'none' : '0 18px 50px rgba(0,0,0,0.55)',
          color: '#e8eef8',
        }}
      >
        <div
          className={`relative space-y-3 ${variant === 'page' ? 'py-3' : 'py-3.5'}`}
          style={{ paddingLeft: 15, paddingRight: 15 }}
        >
          {!hideBrand ? (
            <>
              <div className="flex items-center gap-3">
                <img
                  src={`${import.meta.env.BASE_URL}logo.png`}
                  alt=""
                  className="h-12 w-12 object-contain shrink-0"
                  draggable={false}
                />
                <div className="min-w-0 flex-1 flex items-center gap-2">
                  <img
                    src={`${import.meta.env.BASE_URL}logo2.png`}
                    alt="Nexuz"
                    className="h-6 w-auto max-w-[7rem] object-contain object-left shrink-0"
                    draggable={false}
                  />
                  <div className="min-w-0 flex items-center gap-1.5 text-[12.5px] tracking-[0.14em] uppercase text-slate-400">
                    <Activity className="w-3 h-3 shrink-0" />
                    <span className="truncate">{subtitle}</span>
                  </div>
                  {headerRight ? (
                    <span className="ml-auto shrink-0 normal-case tracking-normal text-[12.5px] text-slate-300">
                      {headerRight}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="h-px w-full bg-white/10" />
            </>
          ) : null}

          {err ? (
            <p className="text-[12.5px] text-rose-300/90">{err}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3">
                <RatioMeter
                  label="CPU"
                  icon={<Cpu className="w-3 h-3 text-cyan-300" />}
                  processValue={cpu}
                  systemValue={sysCpu}
                  processText={cpu.toFixed(1)}
                  systemText={sysCpu.toFixed(1)}
                  accent="#38bdf8"
                />
                <RatioMeter
                  label="内存"
                  icon={<HardDrive className="w-3 h-3 text-fuchsia-300" />}
                  processValue={appMem}
                  systemValue={stats?.system_mem_total_bytes || 0}
                  processText={formatBytes(appMem).replace(' ', '')}
                  systemText={formatBytes(stats?.system_mem_total_bytes).replace(' ', '')}
                  accent="#d946ef"
                />
              </div>

              <div className="grid grid-cols-3 gap-2 text-[12.5px]">
                <div
                  className="min-w-0 space-y-0.5 text-center rounded-lg px-2 py-1.5"
                  style={{
                    background: 'rgba(251, 191, 36, 0.1)',
                    border: '1px solid rgba(251, 191, 36, 0.18)',
                  }}
                >
                  <div className="flex items-center justify-center gap-1 opacity-60">
                    <Layers className="w-3 h-3 text-amber-300" /> 线程
                  </div>
                  <div className="font-mono tabular-nums text-sm text-amber-200">
                    {stats?.threads ?? '—'}
                  </div>
                </div>
                <div
                  className="min-w-0 space-y-0.5 text-center rounded-lg px-2 py-1.5"
                  style={{
                    background: 'rgba(167, 139, 250, 0.1)',
                    border: '1px solid rgba(167, 139, 250, 0.18)',
                  }}
                >
                  <div className="flex items-center justify-center gap-1 opacity-60">
                    <Boxes className="w-3 h-3 text-violet-300" /> 子进程
                  </div>
                  <div className="font-mono tabular-nums text-sm text-violet-200">
                    {stats?.child_count ?? '—'}
                  </div>
                </div>
                <div
                  className="min-w-0 space-y-0.5 text-center rounded-lg px-2 py-1.5"
                  style={{
                    background: 'rgba(52, 211, 153, 0.1)',
                    border: '1px solid rgba(52, 211, 153, 0.18)',
                  }}
                >
                  <div className="flex items-center justify-center gap-1 opacity-60">
                    <Timer className="w-3 h-3 text-emerald-300" /> 运行
                  </div>
                  <div className="font-mono tabular-nums text-sm text-emerald-200">
                    {formatUptime(stats?.uptime_s)}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between text-[12.5px] opacity-70">
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor: stats?.exec_running ? '#34d399' : '#64748b',
                      boxShadow: stats?.exec_running ? '0 0 8px #34d399' : 'none',
                      animation: stats?.exec_running
                        ? 'nexuz-hud-pulse 1.2s ease-in-out infinite'
                        : undefined,
                    }}
                  />
                  {stats?.exec_running ? '流程执行中' : '空闲'}
                </span>
                <span className="inline-flex items-center gap-1 font-mono">
                  <Waves className="w-3 h-3 opacity-60" />
                  Q {stats?.ui_queue ?? 0}
                  <span className="opacity-40">·</span>
                  PID {stats?.pid ?? '—'}
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** @deprecated Logo popover removed — kept as thin wrapper for any leftover imports. */
export default function ResourceMonitorHud({
  open,
}: {
  open: boolean;
  pinned?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}) {
  if (!open) return null;
  return <ResourceMonitorPanel variant="popover" />;
}
