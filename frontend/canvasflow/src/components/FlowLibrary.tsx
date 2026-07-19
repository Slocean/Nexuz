/**
 * Flow library panel — lists flows in the user data directory.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Copy, FileJson, Pencil, Plus, RefreshCw, Search, Trash2 } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { useAppDialog } from './AppDialogs';
import SaveNameDialog from './SaveNameDialog';

export interface FlowListItem {
  name: string;
  path: string;
  mtime?: number;
  size?: number;
}

const normalizePath = (value: string) => value.replace(/\\/g, '/').toLowerCase();

export default function FlowLibrary({
  themeName,
  themeMode,
  currentPath,
  onOpenFlow,
  onRenameFlow,
  onNewFlow,
  refreshToken = 0,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
  currentPath?: string | null;
  onOpenFlow: (path: string) => void;
  onRenameFlow?: (path: string, newName: string) => Promise<boolean>;
  onNewFlow: () => void;
  refreshToken?: number;
}) {
  const { confirm } = useAppDialog();
  const colors = getThemeColors(themeName, themeMode);
  const appendAuditLog = useFlowStore((s) => s.appendAuditLog);
  const appendLog = useFlowStore((s) => s.appendLog);
  const panelRef = useRef<HTMLDivElement>(null);
  const [flows, setFlows] = useState<FlowListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [renameTarget, setRenameTarget] = useState<FlowListItem | null>(null);
  /** Multi-select paths (raw path strings from list). */
  const [selectedPaths, setSelectedPaths] = useState<string[]>([]);
  /** Keyboard focus target for Ctrl+C; not a separate visual highlight. */
  const [focusPath, setFocusPath] = useState<string | null>(null);
  /** Source path for Ctrl+V. */
  const [clipboardPath, setClipboardPath] = useState<string | null>(null);
  /** Dashed border only after Ctrl+C and before Ctrl+V (not for button duplicate). */
  const [pendingPastePath, setPendingPastePath] = useState<string | null>(null);

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

  useEffect(() => {
    if (!flows.length) {
      setSelectedPaths([]);
      return;
    }
    const alive = new Set(flows.map((f) => normalizePath(f.path)));
    setSelectedPaths((prev) => prev.filter((p) => alive.has(normalizePath(p))));
  }, [flows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return flows;
    return flows.filter((f) => f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q));
  }, [flows, query]);

  const selectedSet = useMemo(
    () => new Set(selectedPaths.map((p) => normalizePath(p))),
    [selectedPaths],
  );

  const filteredSelectedCount = useMemo(
    () => filtered.filter((f) => selectedSet.has(normalizePath(f.path))).length,
    [filtered, selectedSet],
  );

  const allFilteredSelected = filtered.length > 0 && filteredSelectedCount === filtered.length;

  const isSelected = useCallback(
    (path: string) => selectedSet.has(normalizePath(path)),
    [selectedSet],
  );

  const toggleSelect = useCallback((path: string, checked: boolean) => {
    setSelectedPaths((prev) => {
      const key = normalizePath(path);
      if (checked) {
        if (prev.some((p) => normalizePath(p) === key)) return prev;
        return [...prev, path];
      }
      return prev.filter((p) => normalizePath(p) !== key);
    });
  }, []);

  const toggleSelectAllFiltered = useCallback(() => {
    if (allFilteredSelected) {
      const drop = new Set(filtered.map((f) => normalizePath(f.path)));
      setSelectedPaths((prev) => prev.filter((p) => !drop.has(normalizePath(p))));
      return;
    }
    setSelectedPaths((prev) => {
      const next = [...prev];
      const have = new Set(prev.map((p) => normalizePath(p)));
      for (const f of filtered) {
        const key = normalizePath(f.path);
        if (!have.has(key)) {
          next.push(f.path);
          have.add(key);
        }
      }
      return next;
    });
  }, [allFilteredSelected, filtered]);

  const clearSelectionRefs = useCallback(
    (paths: string[]) => {
      const keys = new Set(paths.map((p) => normalizePath(p)));
      if (focusPath && keys.has(normalizePath(focusPath))) setFocusPath(null);
      if (clipboardPath && keys.has(normalizePath(clipboardPath))) setClipboardPath(null);
      if (pendingPastePath && keys.has(normalizePath(pendingPastePath))) setPendingPastePath(null);
      setSelectedPaths((prev) => prev.filter((p) => !keys.has(normalizePath(p))));
    },
    [clipboardPath, focusPath, pendingPastePath],
  );

  const removeMany = async (items: FlowListItem[]) => {
    if (!items.length) return;
    const names = items.map((i) => i.name);
    const ok = await confirm({
      title: items.length === 1 ? '删除流程' : '删除多个流程',
      description:
        items.length === 1
          ? `确定删除流程「${names[0]}」？此操作不可恢复。`
          : `确定删除选中的 ${items.length} 个流程？此操作不可恢复。\n${names.slice(0, 5).join('、')}${
              names.length > 5 ? ` 等` : ''
            }`,
      confirmText: '删除',
      destructive: true,
    });
    if (!ok) return;

    const failed: string[] = [];
    const deleted: FlowListItem[] = [];
    for (const item of items) {
      const res = await bridge.deleteFlow(item.path);
      if (res?.ok === false) {
        failed.push(`${item.name}: ${res.error || '删除失败'}`);
      } else {
        deleted.push(item);
      }
    }

    if (deleted.length) {
      clearSelectionRefs(deleted.map((d) => d.path));
      if (deleted.length === 1) {
        appendAuditLog?.(`删除流程: ${deleted[0].name}`, { path: deleted[0].path });
      } else {
        appendAuditLog?.(`删除流程 ×${deleted.length}`, {
          paths: deleted.map((d) => d.path),
          names: deleted.map((d) => d.name),
        });
      }
    }
    if (failed.length) {
      const message = failed.join('；');
      setError(message);
      appendLog?.({ level: 'error', category: 'system', message });
    }
    await refresh();
  };

  const remove = async (item: FlowListItem) => {
    await removeMany([item]);
  };

  const removeSelected = async () => {
    const items = flows.filter((f) => selectedSet.has(normalizePath(f.path)));
    await removeMany(items);
  };

  const rename = async (newName: string) => {
    if (!renameTarget || !onRenameFlow) return;
    const ok = await onRenameFlow(renameTarget.path, newName);
    if (!ok) return;
    setRenameTarget(null);
    await refresh();
  };

  const resolveSourceName = useCallback(
    (path: string) => flows.find((f) => normalizePath(f.path) === normalizePath(path))?.name || path,
    [flows],
  );

  const copyToClipboard = useCallback((item: FlowListItem) => {
    setFocusPath(item.path);
    setClipboardPath(item.path);
    setPendingPastePath(item.path);
    panelRef.current?.focus();
  }, []);

  const pasteFlow = useCallback(
    async (sourcePath?: string, opts?: { fromShortcut?: boolean }) => {
      const path = sourcePath || clipboardPath;
      if (!path) return;
      const srcName = resolveSourceName(path);
      const res = await bridge.duplicateFlow(path);
      if (res?.ok === false) {
        const message = res.error || '粘贴失败';
        setError(message);
        appendLog?.({ level: 'error', category: 'system', message });
        return;
      }
      if (opts?.fromShortcut) {
        setPendingPastePath(null);
      }
      setFocusPath(path);
      panelRef.current?.focus();
      appendAuditLog?.(`复制流程: ${srcName} → ${res.name || '新流程'}`, {
        source_path: path,
        path: res.path,
        name: res.name,
      });
      await refresh();
    },
    [appendAuditLog, appendLog, clipboardPath, refresh, resolveSourceName],
  );

  /** 按钮：立即生成副本，不进入「待粘贴」虚线状态 */
  const duplicateNow = useCallback(
    (item: FlowListItem) => {
      setFocusPath(item.path);
      void pasteFlow(item.path, { fromShortcut: false });
    },
    [pasteFlow],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      return;
    }
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    const key = e.key.toLowerCase();
    if (key === 'c') {
      const item =
        filtered.find((f) => focusPath && normalizePath(f.path) === normalizePath(focusPath)) ||
        filtered.find(
          (f) => currentPath && normalizePath(f.path) === normalizePath(currentPath),
        );
      if (!item) return;
      e.preventDefault();
      copyToClipboard(item);
    } else if (key === 'v') {
      if (!clipboardPath) return;
      e.preventDefault();
      void pasteFlow(undefined, { fromShortcut: true });
    }
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
    <div
      ref={panelRef}
      className="flex flex-col h-full min-h-0 outline-none"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className="p-3 border-b border-black/10 dark:border-white/10 space-y-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <h3 className="font-display font-semibold text-sm shrink-0">流程管理</h3>
          {filtered.length > 0 && (
            <label
              className="flex items-center gap-1 text-[11px] cursor-pointer select-none shrink-0 ml-0.5"
              title="全选当前列表"
            >
              <Checkbox
                checked={allFilteredSelected ? true : filteredSelectedCount > 0 ? 'indeterminate' : false}
                onCheckedChange={() => toggleSelectAllFiltered()}
                aria-label="全选当前列表"
              />
              <span style={{ color: colors.secondaryText }} className="whitespace-nowrap">
                {selectedPaths.length > 0 ? `${selectedPaths.length}` : '全选'}
              </span>
            </label>
          )}
          <div className="flex-1 min-w-0" />
          <div className="flex items-center gap-0.5 shrink-0">
            {selectedPaths.length > 0 && (
              <Button
                size="icon"
                variant="ghost"
                className="h-7 w-7 text-rose-500 hover:text-rose-600"
                onClick={() => void removeSelected()}
                title={`删除选中的 ${selectedPaths.length} 个流程`}
                aria-label="删除选中流程"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            )}
            <Button
              size="icon"
              className="h-7 w-7 text-white hover:opacity-90"
              style={{ backgroundColor: colors.primary }}
              onClick={onNewFlow}
              title="新建流程"
            >
              <Plus className="w-3.5 h-3.5" />
            </Button>
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={refresh} title="刷新">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 opacity-40" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索流程…"
            className="h-8 pl-8 text-xs"
          />
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
        {!loading && flows.length > 0 && filtered.length === 0 && (
          <p style={{ color: colors.secondaryText }} className="text-xs px-2 py-6 text-center opacity-70">
            没有匹配「{query.trim()}」的流程
          </p>
        )}
        {filtered.map((f) => {
          const active = !!(currentPath && normalizePath(f.path) === normalizePath(currentPath));
          const awaitingPaste = !!(
            pendingPastePath && normalizePath(f.path) === normalizePath(pendingPastePath)
          );
          const checked = isSelected(f.path);
          const emphasized = active || awaitingPaste || checked;
          return (
            <div
              key={f.path}
              style={{
                borderColor: emphasized ? colors.primary : colors.border,
                borderStyle: awaitingPaste ? 'dashed' : 'solid',
                backgroundColor: active
                  ? colors.primary + '14'
                  : checked
                    ? colors.primary + '0A'
                    : colors.surface,
              }}
              className="group rounded-xl border px-2.5 py-2 flex items-center gap-2"
            >
              <Checkbox
                checked={checked}
                onCheckedChange={(v) => toggleSelect(f.path, v === true)}
                aria-label={`选择流程 ${f.name}`}
                onClick={(e) => e.stopPropagation()}
              />
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                onClick={() => {
                  setFocusPath(f.path);
                  onOpenFlow(f.path);
                  panelRef.current?.focus();
                }}
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
              <div className="flex items-center self-center gap-0.5 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 opacity-70 group-hover:opacity-100"
                  onClick={() => duplicateNow(f)}
                  title={`复制「${f.name}」并立即创建副本（也可 Ctrl+C / Ctrl+V）`}
                  aria-label={`复制流程 ${f.name}`}
                >
                  <Copy className="w-3.5 h-3.5" />
                </Button>
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
                  onClick={() => void remove(f)}
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
