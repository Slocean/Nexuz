/**
 * Flow library panel — lists flows in the user data directory.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, FileJson, Pencil, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { bridge } from '@/bridge';
import { Button } from '@/components/ui/button';
import { useAppDialog } from './AppDialogs';
import SaveNameDialog from './SaveNameDialog';

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
  onRenameFlow,
  onNewFlow,
  onImport,
  onExport,
  refreshToken = 0,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
  currentPath?: string | null;
  onOpenFlow: (path: string) => void;
  onRenameFlow?: (path: string, newName: string) => Promise<boolean>;
  onNewFlow: () => void;
  onImport?: () => void;
  onExport?: () => void;
  refreshToken?: number;
}) {
  const { confirm } = useAppDialog();
  const colors = getThemeColors(themeName, themeMode);
  const [flows, setFlows] = useState<FlowListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renameTarget, setRenameTarget] = useState<FlowListItem | null>(null);

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
  }, [refresh, refreshToken]);

  const remove = async (item: FlowListItem) => {
    const ok = await confirm({
      title: '删除流程',
      description: `确定删除流程「${item.name}」？此操作不可恢复。`,
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

  const rename = async (newName: string) => {
    if (!renameTarget || !onRenameFlow) return;
    const ok = await onRenameFlow(renameTarget.path, newName);
    if (!ok) return;
    setRenameTarget(null);
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
      <div className="p-3 border-b border-black/10 dark:border-white/10 space-y-2">
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
          {onImport && (
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onImport} title="导入">
              <Upload className="w-3.5 h-3.5" />
            </Button>
          )}
          {onExport && (
            <Button size="sm" variant="outline" className="h-8 text-xs" onClick={onExport} title="导出当前流程">
              <Download className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
        {error && <p className="text-xs text-rose-400 px-2 py-1">{error}</p>}
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
                title={`应用「${f.name}」`}
              >
                <div className="flex items-center gap-1.5">
                  <FileJson className="w-3.5 h-3.5 shrink-0 opacity-60" />
                  <span className="text-xs font-semibold truncate">{f.name}</span>
                </div>
                <div style={{ color: colors.secondaryText }} className="text-xs mt-0.5 truncate">
                  {fmtTime(f.mtime)}
                </div>
              </button>
              <div className="flex items-center gap-0.5 shrink-0">
                {onRenameFlow && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-70 group-hover:opacity-100"
                    onClick={() => setRenameTarget(f)}
                    title={`重命名「${f.name}」`}
                    aria-label={`重命名流程 ${f.name}`}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100 text-rose-400 focus-visible:opacity-100"
                  onClick={() => remove(f)}
                  title={`删除「${f.name}」`}
                  aria-label={`删除流程 ${f.name}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          );
        })}
      </div>
      <SaveNameDialog
        open={!!renameTarget}
        initialName={renameTarget?.name || ''}
        title="重命名流程"
        description="修改流程在流程管理中的显示名称，不会改变文件路径。"
        confirmText="确认修改"
        onCancel={() => setRenameTarget(null)}
        onConfirm={(name) => void rename(name)}
      />
    </div>
  );
}
