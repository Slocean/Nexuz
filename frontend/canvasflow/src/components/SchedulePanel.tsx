import React, { useCallback, useEffect, useState } from 'react';
import { Clock, RefreshCw, Trash2 } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import { useAppDialog } from './AppDialogs';

interface ScheduleJob {
  id?: string;
  job_id?: string;
  name?: string;
  next_run?: string;
  next_run_time?: string;
  trigger?: string;
  trigger_type?: string;
  file_path?: string;
}

export default function SchedulePanel({
  themeName,
  themeMode,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
}) {
  const { confirm } = useAppDialog();
  const colors = getThemeColors(themeName, themeMode);
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await bridge.listScheduleJobs();
      if (res?.ok === false) {
        setError(res.error || '无法读取定时任务');
        setJobs([]);
      } else {
        const list = res?.jobs || res?.data || (Array.isArray(res) ? res : []);
        setJobs(Array.isArray(list) ? list : []);
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const remove = async (jobId: string) => {
    const ok = await confirm({
      title: '移除定时任务',
      description: `确定移除定时任务 ${jobId}？`,
      confirmText: '移除',
      destructive: true,
    });
    if (!ok) return;
    const res = await bridge.removeScheduleJob(jobId);
    if (res?.ok === false) {
      setError(res.error || '移除失败');
      return;
    }
    await refresh();
  };

  return (
    <div className="p-4 space-y-3 border-t border-black/10 dark:border-white/10">
      <div className="flex items-center justify-between">
        <h4
          style={{ color: colors.text }}
          className="font-display font-bold text-xs uppercase tracking-wider flex items-center gap-1.5"
        >
          <Clock className="w-3.5 h-3.5" /> 定时任务
        </h4>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={refresh}
          disabled={loading}
          title="刷新"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>
      <p style={{ color: colors.secondaryText }} className="text-[11px] leading-relaxed">
        由 schedule_trigger 节点注册。运行含该节点的流程后会出现在此列表。
      </p>
      {error && <p className="text-[11px] text-rose-400">{error}</p>}
      {jobs.length === 0 && !error && (
        <p style={{ color: colors.secondaryText }} className="text-[12px] opacity-60 py-2">
          暂无定时任务
        </p>
      )}
      <div className="space-y-2">
        {jobs.map((job) => {
          const id = String(job.id || job.job_id || '');
          return (
            <div
              key={id}
              style={{ borderColor: colors.border, backgroundColor: colors.surface }}
              className="rounded-xl border px-2.5 py-2 flex items-start justify-between gap-2"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold truncate">{job.name || id}</div>
                <div style={{ color: colors.secondaryText }} className="text-[11px] mt-0.5 truncate">
                  {job.trigger || job.trigger_type || '—'}
                </div>
                <div style={{ color: colors.secondaryText }} className="text-[11px] opacity-70">
                  下次: {job.next_run || job.next_run_time || '—'}
                </div>
                {job.file_path && (
                  <div style={{ color: colors.secondaryText }} className="text-[10px] opacity-50 truncate">
                    {job.file_path}
                  </div>
                )}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 text-rose-400 hover:text-rose-500"
                onClick={() => remove(id)}
                title="移除"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
