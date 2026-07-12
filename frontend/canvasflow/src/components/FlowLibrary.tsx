/**
 * Flow library panel — lists flows under project /flows.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { FolderOpen, Plus, RefreshCw, Trash2, FileJson } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import { useAppDialog } from './AppDialogs';

export interface FlowListItem {
  name: string;
  path: string;
  mtime?: number;
  size?: number;
}

export default function FlowLibrary({
  themeName,
  themeMode,
  currentPath,
  onOpenFlow,
  onNewFlow,
  onOpenFromDisk,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
  currentPath?: string | null;
  onOpenFlow: (path: string) => void;
  onNewFlow: () => void;
  onOpenFromDisk?: () => void;
}) {
  const { confirm } = useAppDialog();
  const colors = getThemeColors(themeName, themeMode);
  const [flows, setFlows] = useState<FlowListItem[]>([]);
  const [dir, setDir] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await bridge.listFlows();
      if (res?.ok === false) {
        setError(res.error || '无法读取流程列表');
        setFlows([]);
      } else {
        setFlows(Array.isArray(res?.flows) ? res.flows : []);
        setDir(res?.dir || '');
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setFlows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const remove = async (item: FlowListItem) => {
    const ok = await confirm({
      title: '删除流程',
      description: `确定删除流程「${item.name}」？\n${item.path}`,
      confirmText: '删除',
      destructive: true,
    });
    if (!ok) return;
    const res = await bridge.deleteFlow(item.path);
    if (res?.ok === false) {
      setError(res.error || '删除失败');
      return;
    }
    await refresh();
  };

  const fmtTime = (ms?: number) => {
    if (!ms) return '';
    try {
      return new Date(ms).toLocaleString();
    } catch {
      return '';
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="p-3 border-b border-black/5 dark:border-white/5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-display font-semibold text-sm">流程管理</h3>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={refresh} title="刷新">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" className="flex-1 h-8 text-xs" onClick={onNewFlow}>
            <Plus className="w-3.5 h-3.5" /> 新建
          </Button>
          {onOpenFromDisk && (
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onOpenFromDisk} title="从任意位置打开">
              <FolderOpen className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
        {dir && (
          <p style={{ color: colors.secondaryText }} className="text-[10px] truncate" title={dir}>
            目录: {dir}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {error && <p className="text-[11px] text-rose-400 px-2 py-1">{error}</p>}
        {!loading && flows.length === 0 && !error && (
          <p style={{ color: colors.secondaryText }} className="text-xs px-2 py-6 text-center opacity-70">
            暂无已保存流程
            <br />
            保存后会出现在这里
          </p>
        )}
        {flows.map((f) => {
          const active = currentPath && f.path.replace(/\\/g, '/') === currentPath.replace(/\\/g, '/');
          return (
            <div
              key={f.path}
              style={{
                borderColor: active ? colors.primary : colors.border,
                backgroundColor: active ? colors.primary + '14' : colors.surface,
              }}
              className="group rounded-xl border px-2.5 py-2 flex items-start gap-2"
            >
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => onOpenFlow(f.path)}
                title={f.path}
              >
                <div className="flex items-center gap-1.5">
                  <FileJson className="w-3.5 h-3.5 shrink-0 opacity-60" />
                  <span className="text-[12px] font-semibold truncate">{f.name}</span>
                </div>
                <div style={{ color: colors.secondaryText }} className="text-[10px] mt-0.5 truncate">
                  {fmtTime(f.mtime)}
                </div>
              </button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 text-rose-400"
                onClick={() => remove(f)}
                title="删除"
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
