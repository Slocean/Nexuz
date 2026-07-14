/**
 * Flow templates tab — builtin + user-saved templates (add / delete / load).
 * Card chrome matches CatalogCard; title / description stack as two lines.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw, Trash2, ChevronDown, ChevronRight } from 'lucide-react';
import { ThemeMode, ThemeName } from '../types';
import { getThemeColors } from '../theme';
import { bridge } from '@/bridge';
import { useFlowStore } from '@/store/flowModelStore';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useAppDialog } from './AppDialogs';
import SaveNameDialog from './SaveNameDialog';

export type BuiltinTemplate = {
  id: string;
  name: string;
  description: string;
};

export type CustomTemplate = {
  id: string;
  name: string;
  description?: string;
  path: string;
  mtime?: number;
  builtin?: boolean;
};

const BUILTIN_TEMPLATES: BuiltinTemplate[] = [
  {
    id: 'click-loop',
    name: '点击循环模板',
    description: '延时 → 固定次数循环 → 点击',
  },
  {
    id: 'color-branch',
    name: '颜色分支模板',
    description: '颜色匹配条件分支',
  },
];

function TemplateCard({
  themeMode,
  borderColor,
  accentColor,
  secondaryText,
  title,
  subtitle,
  onClick,
  onDelete,
}: {
  themeMode: ThemeMode;
  borderColor: string;
  accentColor: string;
  secondaryText: string;
  title: string;
  subtitle: string;
  onClick: () => void;
  onDelete?: () => void;
}) {
  return (
    <div className="relative group">
      <button
        type="button"
        onClick={onClick}
        style={{
          backgroundColor:
            themeMode === 'light' ? 'rgba(255, 255, 255, 0.4)' : 'rgba(255, 255, 255, 0.02)',
          borderColor,
          color: 'inherit',
        }}
        className={cn(
          'w-full text-left px-3 py-2 rounded-2xl border transition-all duration-200',
          'hover:scale-[1.02] active:scale-[0.98] hover:shadow-md hover:border-emerald-400',
          'cursor-pointer',
        )}
        title={`${title} · ${subtitle}`}
      >
        <div className="flex items-center gap-2 w-full min-w-0">
          <div className="flex-1 min-w-0 space-y-0.5">
            <span className="block font-semibold text-sm group-hover:text-emerald-500 transition-colors truncate">
              {title}
            </span>
            <span className="block text-xs font-normal truncate" style={{ color: secondaryText }}>
              {subtitle}
            </span>
          </div>
          <div
            style={{ backgroundColor: accentColor + '1A' }}
            className={cn(
              'h-7 w-7 rounded-lg shrink-0 flex items-center justify-center',
              onDelete && 'group-hover:opacity-0',
            )}
          >
            <Plus className="w-3.5 h-3.5" style={{ color: accentColor }} />
          </div>
        </div>
      </button>
      {onDelete ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7 text-rose-500 opacity-0 group-hover:opacity-100 transition-opacity"
          title="删除模板"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          <Trash2 className="w-3.5 h-3.5" />
        </Button>
      ) : null}
    </div>
  );
}

export default function TemplatesPanel({
  themeName,
  themeMode,
  onLoadBuiltin,
}: {
  themeName: ThemeName;
  themeMode: ThemeMode;
  onLoadBuiltin: (templateId: string) => void;
}) {
  const { confirm, alert } = useAppDialog();
  const colors = getThemeColors(themeName, themeMode);
  const flow = useFlowStore((s) => s.flow);
  const setFlow = useFlowStore((s) => s.setFlow);
  const appendLog = useFlowStore((s) => s.appendLog);

  const [custom, setCustom] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [builtinOpen, setBuiltinOpen] = useState(true);
  const [mineOpen, setMineOpen] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await bridge.listFlowTemplates();
      if (res?.ok === false) {
        setError(res.error || '无法读取模板列表');
        setCustom([]);
      } else {
        setCustom(Array.isArray(res?.templates) ? res.templates : []);
      }
    } catch (e: any) {
      setError(String(e?.message || e));
      setCustom([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const nodeCount = Object.keys(flow?.nodes || {}).length;

  const saveCurrentAsTemplate = async (name: string) => {
    setSaveOpen(false);
    if (!nodeCount) {
      await alert({ title: '无法保存', description: '当前画布没有节点，请先编排流程再保存为模板' });
      return;
    }
    const description = `${nodeCount} 个节点`;
    const res = await bridge.saveFlowTemplate(
      {
        ...flow,
        flow_id: flow.flow_id || `tpl_${Date.now()}`,
        name,
        description,
      },
      name,
      description,
    );
    if (!res?.ok) {
      await alert({ title: '保存失败', description: res?.error || '无法保存模板' });
      return;
    }
    appendLog({ level: 'ok', message: `已保存流程模板「${name}」` });
    await refresh();
  };

  const remove = async (item: CustomTemplate) => {
    const ok = await confirm({
      title: '删除模板',
      description: `确定删除模板「${item.name}」？此操作不可恢复。`,
      confirmText: '删除',
      destructive: true,
    });
    if (!ok) return;
    const res = await bridge.deleteFlowTemplate(item.path);
    if (res?.ok === false) {
      setError(res.error || '删除失败');
      return;
    }
    appendLog({ level: 'info', message: `已删除模板「${item.name}」` });
    await refresh();
  };

  const loadCustom = async (item: CustomTemplate) => {
    const res = await bridge.loadFlowTemplate(item.path);
    if (!res?.ok || !res.flow) {
      await alert({ title: '加载失败', description: res?.error || '无法加载模板' });
      return;
    }
    const loaded = res.flow;
    setFlow(
      {
        ...loaded,
        flow_id: `flow_${Date.now()}`,
        name: loaded.name || item.name,
        version: loaded.version || 1,
      },
      null,
    );
    appendLog({ level: 'info', message: `已加载模板「${item.name}」` });
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-display font-semibold text-sm opacity-80 mb-1">流程模板</h3>
          <p style={{ color: colors.secondaryText }} className="text-xs">
            选择模板清空画布并填充节点。
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          onClick={refresh}
          title="刷新"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </Button>
      </div>

      <Button
        size="sm"
        className="w-full h-8 text-xs gap-1"
        onClick={() => setSaveOpen(true)}
        disabled={!nodeCount}
        title={nodeCount ? '将当前画布保存为模板' : '画布为空，无法保存'}
      >
        <Plus className="w-3.5 h-3.5" /> 新增模板
      </Button>

      {error && <p className="text-xs text-rose-400">{error}</p>}

      <div className="space-y-2">
        <button
          type="button"
          className="flex w-full items-center gap-1 text-xs font-medium opacity-60 hover:opacity-100 transition-opacity"
          onClick={() => setBuiltinOpen((v) => !v)}
          title={builtinOpen ? '折叠' : '展开'}
        >
          {builtinOpen ? (
            <ChevronDown className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 shrink-0" />
          )}
          <span>内置</span>
          <span className="opacity-70">({BUILTIN_TEMPLATES.length})</span>
        </button>
        {builtinOpen ? (
          <div className="space-y-3">
            {BUILTIN_TEMPLATES.map((tpl) => (
              <TemplateCard
                key={tpl.id}
                themeMode={themeMode}
                borderColor={colors.border}
                accentColor="#34C759"
                secondaryText={colors.secondaryText}
                title={tpl.name}
                subtitle={tpl.description}
                onClick={() => onLoadBuiltin(tpl.id)}
              />
            ))}
          </div>
        ) : null}
      </div>

      <div className="space-y-2">
        <button
          type="button"
          className="flex w-full items-center gap-1 text-xs font-medium opacity-60 hover:opacity-100 transition-opacity"
          onClick={() => setMineOpen((v) => !v)}
          title={mineOpen ? '折叠' : '展开'}
        >
          {mineOpen ? (
            <ChevronDown className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 shrink-0" />
          )}
          <span>我的模板</span>
          <span className="opacity-70">({custom.length})</span>
        </button>
        {mineOpen ? (
          !loading && custom.length === 0 ? (
            <p
              style={{ color: colors.secondaryText }}
              className="text-xs text-center py-6 border border-dashed rounded-xl opacity-70"
            >
              暂无自定义模板
              <br />
              点击上方「新增模板」保存当前流程
            </p>
          ) : (
            <div className="space-y-3">
              {custom.map((tpl) => (
                <TemplateCard
                  key={tpl.path}
                  themeMode={themeMode}
                  borderColor={colors.border}
                  accentColor="#34C759"
                  secondaryText={colors.secondaryText}
                  title={tpl.name}
                  subtitle={tpl.description || '自定义流程模板'}
                  onClick={() => void loadCustom(tpl)}
                  onDelete={() => void remove(tpl)}
                />
              ))}
            </div>
          )
        ) : null}
      </div>

      <SaveNameDialog
        open={saveOpen}
        initialName={flow?.name || '我的模板'}
        title="新增模板"
        description="将当前画布流程保存为可复用模板，出现在「我的模板」中。"
        label="模板名称"
        confirmText="保存模板"
        placeholder="例如：登录流程模板"
        onCancel={() => setSaveOpen(false)}
        onConfirm={(name) => void saveCurrentAsTemplate(name)}
      />
    </div>
  );
}
