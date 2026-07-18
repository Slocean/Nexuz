import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Cpu, HardDrive, Timer, Waves } from 'lucide-react';
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

function Meter({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: number;
  hint?: string;
  accent: string;
}) {
  const pct = clampPct(value);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="tracking-wide opacity-70">{label}</span>
        <span className="font-mono tabular-nums" style={{ color: accent }}>
          {pct.toFixed(1)}%
          {hint ? <span className="ml-1.5 opacity-50">{hint}</span> : null}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden relative">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out relative"
          style={{
            width: `${pct}%`,
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

type Props = {
  open: boolean;
  pinned?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
};

export default function ResourceMonitorHud({
  open,
  pinned = false,
  onMouseEnter,
  onMouseLeave,
}: Props) {
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
    if (!open) return undefined;
    void refresh();
    // Warm CPU percent (psutil first sample is often 0)
    const warm = window.setTimeout(() => void refresh(), 400);
    const id = window.setInterval(() => void refresh(), 1000);
    return () => {
      alive.current = false;
      window.clearTimeout(warm);
      window.clearInterval(id);
    };
  }, [open, refresh]);

  if (!open) return null;

  const appMem = (stats?.private_bytes || stats?.rss_bytes || 0) + (stats?.children_rss_bytes || 0);
  const cpu = clampPct(stats?.cpu_percent);
  const sysCpu = clampPct(stats?.system_cpu_percent);
  const sysMem = clampPct(stats?.system_mem_percent);

  return (
    <div
      className="absolute left-0 top-[calc(100%+6px)] z-[120] w-[19.5rem] select-none"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <style>{`
        @keyframes nexuz-hud-shine {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes nexuz-hud-pulse {
          0%, 100% { opacity: 0.45; }
          50% { opacity: 1; }
        }
        @keyframes nexuz-hud-scan {
          0% { transform: translateY(-100%); }
          100% { transform: translateY(220%); }
        }
        @keyframes nexuz-hud-ring {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>

      <div
        className="relative overflow-hidden rounded-2xl border shadow-2xl backdrop-blur-xl"
        style={{
          background: 'rgba(12, 14, 20, 0.96)',
          borderColor: 'rgba(255, 255, 255, 0.12)',
          boxShadow: '0 18px 50px rgba(0,0,0,0.55)',
          color: '#e8eef8',
        }}
      >
        <div className="relative p-3.5 space-y-3">
          {/* Brand header: both logos */}
          <div className="flex items-center gap-3">
            <img
              src={`${import.meta.env.BASE_URL}logo.png`}
              alt=""
              className="h-12 w-12 object-contain shrink-0"
              draggable={false}
            />
            <div className="min-w-0 flex-1">
              <img
                src={`${import.meta.env.BASE_URL}logo2.png`}
                alt="Nexuz"
                className="h-6 w-auto max-w-[9rem] object-contain object-left"
                draggable={false}
              />
              <div className="mt-1 flex items-center gap-2 text-[10px] tracking-[0.18em] uppercase text-slate-400">
                <Activity className="w-3 h-3" />
                Resource Link
                {pinned ? (
                  <span className="ml-auto normal-case tracking-normal text-slate-300">
                    已固定
                  </span>
                ) : (
                  <span className="ml-auto normal-case tracking-normal opacity-50">
                    点击固定
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="h-px w-full bg-white/10" />

          {err ? (
            <p className="text-xs text-rose-300/90">{err}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-2">
                  <div className="flex items-center gap-1.5 text-[10px] opacity-60">
                    <Cpu className="w-3 h-3 text-cyan-300" /> 进程 CPU
                  </div>
                  <div className="mt-0.5 font-mono text-lg tabular-nums text-cyan-200">
                    {cpu.toFixed(1)}
                    <span className="text-xs opacity-60">%</span>
                  </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-white/[0.03] px-2.5 py-2">
                  <div className="flex items-center gap-1.5 text-[10px] opacity-60">
                    <HardDrive className="w-3 h-3 text-fuchsia-300" /> 进程内存
                  </div>
                  <div className="mt-0.5 font-mono text-lg tabular-nums text-fuchsia-200">
                    {formatBytes(appMem).replace(' ', '')}
                  </div>
                </div>
              </div>

              <div className="space-y-2.5">
                <Meter label="系统 CPU" value={sysCpu} accent="#38bdf8" />
                <Meter
                  label="系统内存"
                  value={sysMem}
                  hint={formatBytes(stats?.system_mem_used_bytes)}
                  accent="#d946ef"
                />
              </div>

              <div className="grid grid-cols-3 gap-1.5 text-[10px]">
                <div className="rounded-lg bg-white/[0.04] px-2 py-1.5 border border-white/8">
                  <div className="opacity-50">线程</div>
                  <div className="font-mono tabular-nums text-sm">{stats?.threads ?? '—'}</div>
                </div>
                <div className="rounded-lg bg-white/[0.04] px-2 py-1.5 border border-white/8">
                  <div className="opacity-50">子进程</div>
                  <div className="font-mono tabular-nums text-sm">{stats?.child_count ?? '—'}</div>
                </div>
                <div className="rounded-lg bg-white/[0.04] px-2 py-1.5 border border-white/8">
                  <div className="opacity-50 flex items-center gap-1">
                    <Timer className="w-2.5 h-2.5" /> 运行
                  </div>
                  <div className="font-mono tabular-nums text-sm">{formatUptime(stats?.uptime_s)}</div>
                </div>
              </div>

              <div className="flex items-center justify-between text-[10px] opacity-70">
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
