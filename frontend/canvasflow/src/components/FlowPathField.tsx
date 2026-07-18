/**
 * Subflow picker: choose from saved library, or browse a .flow.json on disk.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { FolderOpen, RefreshCw } from 'lucide-react';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useAppDialog } from './AppDialogs';

type FlowItem = { name: string; path: string };

export default function FlowPathField({
  value,
  onChange,
}: {
  value: string;
  onChange: (path: string) => void;
}) {
  const { alert } = useAppDialog();
  const currentPath = useFlowStore((s) => s.filePath);
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await bridge.listFlows();
      if (res?.ok === false) {
        setError(res.error || '无法读取流程列表');
        setFlows([]);
      } else {
        const list = Array.isArray(res?.flows) ? res.flows : [];
        setFlows(
          list
            .filter((f: any) => f?.path)
            .map((f: any) => ({
              name: String(f.name || f.path),
              path: String(f.path),
            })),
        );
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setFlows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const options = flows.filter((f) => !currentPath || f.path !== currentPath);
  const matched = options.find((f) => f.path === value);
  const selectValue = matched ? value : undefined;

  const handleBrowse = async () => {
    setBrowsing(true);
    setError('');
    try {
      // libraryOnly=false: allow any .flow.json; dialog still opens in library folder
      const picked = await bridge.pickFlowFile?.(false);
      if (picked?.ok && picked.path) {
        onChange(String(picked.path));
        await refresh();
        return;
      }
      if (picked?.cancelled) return;
      await alert({
        title: '选择失败',
        description: picked?.error || '无法打开文件对话框',
      });
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setBrowsing(false);
    }
  };

  return (
    <div className="flex-1 min-w-0 space-y-2">
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-medium opacity-60 leading-none">流程库</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 px-1.5 text-[10px] opacity-70"
            title="刷新流程列表"
            disabled={loading}
            onClick={() => void refresh()}
          >
            <RefreshCw className={`w-3 h-3 mr-1 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </div>
        <Select
          value={selectValue}
          onValueChange={(v) => onChange(v)}
          disabled={loading || options.length === 0}
        >
          <SelectTrigger className="h-8 text-xs w-full">
            <SelectValue
              placeholder={
                loading
                  ? '加载中…'
                  : options.length
                    ? '选择已保存的流程'
                    : '暂无已保存流程'
              }
            />
          </SelectTrigger>
          <SelectContent className="z-[200]">
            {options.map((f) => (
              <SelectItem key={f.path} value={f.path} className="text-xs">
                {f.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <div className="h-px flex-1 bg-black/10 dark:bg-white/10" />
        <span className="text-[10px] opacity-40 shrink-0">或</span>
        <div className="h-px flex-1 bg-black/10 dark:bg-white/10" />
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="h-8 w-full text-xs justify-center"
        disabled={browsing}
        title="从磁盘选择 .flow.json"
        onClick={() => void handleBrowse()}
      >
        <FolderOpen className="w-3.5 h-3.5" />
        {browsing ? '选择中…' : '浏览文件'}
      </Button>

      {value ? (
        <div className="rounded-md border px-2 py-1.5 space-y-0.5" style={{ borderColor: 'var(--border)' }}>
          <p className="text-[10px] opacity-50 leading-none">
            {matched ? `已选：${matched.name}` : '已选路径'}
          </p>
          <p className="text-[10px] font-mono opacity-70 break-all leading-snug" title={value}>
            {value}
          </p>
        </div>
      ) : null}

      {error ? <p className="text-[10px] text-rose-500">{error}</p> : null}
      {!loading && !error && options.length === 0 && !value ? (
        <p className="text-[10px] opacity-50 leading-relaxed">
          流程库为空时，可先在左侧保存流程，或点「浏览文件」选择 .flow.json。
        </p>
      ) : null}
    </div>
  );
}
