/**
 * Read-only runtime variables while paused — same collapsible JSON tree as Inspector 输出.
 */
import React, { useMemo, useState } from 'react';
import { Check, Copy, Variable } from 'lucide-react';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { getThemeColors } from '../theme';
import type { ThemeMode, ThemeName } from '../types';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import JsonTreeView from './JsonTreeView';

export default function DebugWatchPanel({
  themeName,
  themeMode,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
}) {
  const colors = getThemeColors(themeName, themeMode);
  const execStatus = useFlowStore((s) => s.execStatus);
  const execNodeId = useFlowStore((s) => s.execNodeId);
  const debugContext = useFlowStore((s) => s.debugContext || {});
  const nodeOutputs = useFlowStore((s) => s.nodeOutputs || {});
  const [copied, setCopied] = useState(false);

  const visible = execStatus === 'breakpoint' || execStatus === 'paused';

  const treeData = useMemo(() => {
    const ctx = debugContext && typeof debugContext === 'object' ? debugContext : {};
    if (Object.keys(ctx).length > 0) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(ctx).sort((a, b) => a.localeCompare(b))) {
        sorted[k] = (ctx as Record<string, unknown>)[k];
      }
      return sorted;
    }
    const outs = nodeOutputs && typeof nodeOutputs === 'object' ? nodeOutputs : {};
    if (Object.keys(outs).length > 0) {
      const sorted: Record<string, unknown> = {};
      for (const k of Object.keys(outs).sort((a, b) => a.localeCompare(b))) {
        sorted[k] = (outs as Record<string, unknown>)[k];
      }
      return { __节点输出: sorted };
    }
    return null;
  }, [debugContext, nodeOutputs]);

  if (!visible) return null;

  return (
    <div
      className="pointer-events-auto absolute top-16 right-3 z-30 w-[min(360px,46vw)] max-h-[min(480px,55vh)] rounded-2xl border shadow-lg backdrop-blur-md flex flex-col overflow-hidden"
      style={{
        backgroundColor: colors.surface + 'F5',
        borderColor: colors.border,
        color: colors.text,
      }}
    >
      <div
        className="flex items-center gap-1.5 px-3 py-2 border-b text-xs font-medium shrink-0"
        style={{ borderColor: colors.border }}
      >
        <Variable className="w-3.5 h-3.5 opacity-70" />
        <span>变量监视</span>
        <span className="opacity-40">·</span>
        <span className="opacity-60 truncate flex-1 min-w-0">待执行 {execNodeId || '—'}</span>
        {treeData ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            title="复制全部"
            onClick={async () => {
              try {
                const text = JSON.stringify(treeData, null, 2);
                const res = await bridge.clipboardWrite?.(text);
                if (res?.ok !== false) {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }
              } catch {
                /* ignore */
              }
            }}
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
          </Button>
        ) : null}
      </div>
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2">
          {treeData ? (
            <JsonTreeView
              data={treeData}
              onCopied={() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
              style={{
                backgroundColor: themeMode === 'light' ? '#F1F5F9' : '#05070A',
                borderColor: colors.border,
              }}
              className="p-2 border max-h-[min(400px,48vh)] overflow-y-auto overflow-x-hidden cursor-text min-w-0 w-full"
            />
          ) : (
            <p className="text-[11px] opacity-50 px-1 py-2 leading-relaxed">
              暂无运行时变量。执行过赋值或有输出的节点后，断点处会显示在这里。
            </p>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
