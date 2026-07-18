import React, { useMemo, useState } from 'react';
import {
  Plus,
  Trash2,
  FolderSync,
  Search,
  Workflow,
  Boxes,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { ThemeName, ThemeMode, WorkflowNode } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import VariablesPanel from './VariablesPanel';
import SchedulePanel from './SchedulePanel';
import FlowLibrary from './FlowLibrary';
import TemplatesPanel from './TemplatesPanel';
import UserBlockCreateDialog from './UserBlockCreateDialog';

interface SidebarProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
  onAddNode?: (subType: string, customProps?: Partial<WorkflowNode>) => void;
  onAddNexuzNode?: (blockType: string) => void;
  nexuzSchemas?: { type: string; label: string; category?: string }[];
  onLoadTemplate: (templateId: string) => void;
  runHistory: { id: string; timestamp: string; status: string; workflowName: string }[];
  onClearHistory: () => void;
  interactionLocked?: boolean;
  currentFlowPath?: string | null;
  onOpenFlowPath?: (path: string) => void;
  onRenameFlow?: (path: string, newName: string) => Promise<boolean>;
  onNewFlow?: () => void;
  onImportFlow?: () => void;
  onExportFlow?: () => void;
  flowsRefreshToken?: number;
}

const nexuzCatColor: Record<string, string> = {
  动作类: '#FF9500',
  识别类: '#4F8CFF',
  控制类: '#AF52DE',
  系统类: '#0D9488',
  自定义: '#64748B',
};

function CatalogCard({
  themeMode,
  borderColor,
  accentColor,
  secondaryText,
  title,
  subtitle,
  onClick,
  dragType,
  hoverBorderClass = 'hover:border-blue-400',
}: {
  themeMode: ThemeMode;
  borderColor: string;
  accentColor: string;
  secondaryText: string;
  title: string;
  subtitle: string;
  onClick: () => void;
  /** When set, card can be dragged onto the canvas */
  dragType?: string;
  hoverBorderClass?: string;
}) {
  const dragStarted = React.useRef(false);
  return (
    <button
      type="button"
      draggable={!!dragType}
      onDragStart={(e) => {
        if (!dragType) return;
        dragStarted.current = true;
        e.dataTransfer.setData('application/nexuz-block', dragType);
        e.dataTransfer.setData('text/plain', dragType);
        e.dataTransfer.effectAllowed = 'copy';
      }}
      onDragEnd={() => {
        // Avoid click-add after a drag
        setTimeout(() => {
          dragStarted.current = false;
        }, 0);
      }}
      onClick={() => {
        if (dragStarted.current) return;
        onClick();
      }}
      style={{
        backgroundColor:
          themeMode === 'light' ? 'rgba(255, 255, 255, 0.4)' : 'rgba(255, 255, 255, 0.02)',
        borderColor,
        color: 'inherit',
      }}
      className={cn(
        'w-full text-left px-3 py-2 rounded-2xl border transition-all duration-200',
        'hover:scale-[1.02] active:scale-[0.98] hover:shadow-md group cursor-grab active:cursor-grabbing',
        hoverBorderClass,
      )}
      title={dragType ? '点击添加，或拖到画布' : `${title} · ${subtitle}`}
    >
      <div className="flex items-center gap-2 w-full min-w-0">
        <div className="flex-1 min-w-0 flex items-center gap-2">
          <span className="font-semibold text-sm group-hover:text-blue-500 transition-colors truncate shrink-0 max-w-[55%]">
            {title}
          </span>
          <span
            className="text-xs font-normal truncate min-w-0"
            style={{ color: secondaryText }}
          >
            {subtitle}
          </span>
        </div>
        <div
          style={{ backgroundColor: accentColor + '1A' }}
          className="h-7 w-7 rounded-lg shrink-0 flex items-center justify-center"
        >
          <Plus className="w-3.5 h-3.5" style={{ color: accentColor }} />
        </div>
      </div>
    </button>
  );
}

export default function Sidebar({
  themeName,
  themeMode,
  onAddNexuzNode,
  nexuzSchemas = [],
  onLoadTemplate,
  runHistory,
  onClearHistory,
  interactionLocked = false,
  currentFlowPath = null,
  onOpenFlowPath,
  onRenameFlow,
  onNewFlow,
  onImportFlow,
  onExportFlow,
  flowsRefreshToken = 0,
}: SidebarProps) {
  const colors = getThemeColors(themeName, themeMode);
  const [query, setQuery] = useState('');
  const [panel, setPanel] = useState<'flows' | 'nodes'>('nodes');
  const [collapsedCats, setCollapsedCats] = useState<Record<string, boolean>>(() => {
    try {
      const raw = localStorage.getItem('nexuz.sidebarCollapsedCats');
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const q = query.trim().toLowerCase();

  const toggleCat = (cat: string) => {
    setCollapsedCats((prev) => {
      const next = { ...prev, [cat]: !prev[cat] };
      try {
        localStorage.setItem('nexuz.sidebarCollapsedCats', JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const [createBlockOpen, setCreateBlockOpen] = useState(false);

  const nexuzGrouped = useMemo(() => {
    const filtered = q
      ? nexuzSchemas.filter(
          (s) =>
            s.type.toLowerCase().includes(q) ||
            (s.label || '').toLowerCase().includes(q) ||
            (s.category || '').toLowerCase().includes(q),
        )
      : nexuzSchemas;
    const grouped = filtered.reduce((acc: Record<string, typeof nexuzSchemas>, s) => {
      const cat = s.category || '其他';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(s);
      return acc;
    }, {});
    const order = ['动作类', '识别类', '控制类', '系统类', '自定义'];
    const sorted: Record<string, typeof nexuzSchemas> = {};
    for (const cat of order) {
      if (grouped[cat]?.length) sorted[cat] = grouped[cat];
      // Always show 自定义 so users can hit (+) even with zero custom blocks
      else if (cat === '自定义' && !q) sorted[cat] = [];
    }
    for (const [cat, items] of Object.entries(grouped)) {
      if (!sorted[cat]) sorted[cat] = items;
    }
    return sorted;
  }, [nexuzSchemas, q]);

  return (
    <aside
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      className={`flex h-full backdrop-blur-xl z-30 shrink-0 border-r ${
        interactionLocked ? 'pointer-events-none opacity-60' : ''
      }`}
    >
      {/* Left rail: Nodes / Flows */}
      <nav
        style={{ borderColor: colors.border }}
        className="w-14 shrink-0 border-r flex flex-col items-center gap-2.5 py-4 px-2"
      >
        <button
          type="button"
          title="积木节点"
          onClick={() => setPanel('nodes')}
          className={cn(
            'w-9 h-9 rounded-xl flex items-center justify-center transition-colors',
            panel !== 'nodes' && 'hover:bg-black/5 dark:hover:bg-white/10 opacity-70 hover:opacity-100',
          )}
          style={
            panel === 'nodes'
              ? {
                  backgroundColor: colors.primary + '33',
                  color: colors.primary,
                }
              : undefined
          }
        >
          <Boxes className="w-4 h-4" />
        </button>
        <button
          type="button"
          title="流程管理"
          onClick={() => setPanel('flows')}
          className={cn(
            'w-9 h-9 rounded-xl flex items-center justify-center transition-colors',
            panel !== 'flows' && 'hover:bg-black/5 dark:hover:bg-white/10 opacity-70 hover:opacity-100',
          )}
          style={
            panel === 'flows'
              ? {
                  backgroundColor: colors.primary + '33',
                  color: colors.primary,
                }
              : undefined
          }
        >
          <Workflow className="w-4 h-4" />
        </button>
      </nav>

      <div className="w-[17.5rem] flex flex-col h-full min-h-0 min-w-0">
        {panel === 'flows' ? (
          <FlowLibrary
            themeName={themeName}
            themeMode={themeMode}
            currentPath={currentFlowPath}
            onOpenFlow={(path) => onOpenFlowPath?.(path)}
            onRenameFlow={onRenameFlow}
            onNewFlow={() => onNewFlow?.()}
            onImport={onImportFlow}
            onExport={onExportFlow}
            refreshToken={flowsRefreshToken}
          />
        ) : (
      <Tabs defaultValue="components" className="flex flex-col h-full min-h-0">
        <TabsList
          className="shrink-0"
          style={{ borderColor: colors.border }}
        >
          <TabsTrigger value="components" className="normal-case tracking-normal">
            节点
          </TabsTrigger>
          <TabsTrigger value="variables" className="normal-case tracking-normal">
            变量
          </TabsTrigger>
          <TabsTrigger value="templates" className="normal-case tracking-normal">
            模板
          </TabsTrigger>
          <TabsTrigger value="history" className="normal-case tracking-normal">
            运行
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 min-h-0 overflow-y-auto">
          <TabsContent value="components" className="p-4 space-y-5 m-0 data-[state=inactive]:hidden">
            <div>
              <h3 className="font-display font-semibold text-sm opacity-80 mb-1">
                积木节点
              </h3>
              <p style={{ color: colors.secondaryText }} className="text-xs mb-3">
                点击添加，或拖到画布。
              </p>
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 opacity-40" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索积木，如 OCR / 找图…"
                  className="h-8 pl-8 text-xs"
                />
              </div>
            </div>

            {Object.entries(nexuzGrouped).map(([cat, items]) => {
              const closed = !!collapsedCats[cat];
              return (
                <div key={`nexuz-${cat}`} className="space-y-2">
                  <button
                    type="button"
                    onClick={() => toggleCat(cat)}
                    className="flex items-center gap-1.5 px-1 w-full text-left rounded-md hover:bg-black/5 dark:hover:bg-white/5 py-0.5"
                    title={closed ? '展开分组' : '折叠分组'}
                  >
                    {closed ? (
                      <ChevronRight className="w-3.5 h-3.5 opacity-50 shrink-0" />
                    ) : (
                      <ChevronDown className="w-3.5 h-3.5 opacity-50 shrink-0" />
                    )}
                    <span
                      style={{ backgroundColor: nexuzCatColor[cat] || colors.primary }}
                      className="w-2 h-2 rounded-full shadow-sm shrink-0"
                    />
                    <span
                      style={{ color: colors.secondaryText }}
                      className="text-xs font-bold uppercase tracking-wider flex-1 min-w-0 truncate"
                    >
                      Nexuz · {cat}
                    </span>
                    <span
                      style={{ color: colors.secondaryText }}
                      className="text-[10px] opacity-50 tabular-nums shrink-0"
                    >
                      {items.length}
                    </span>
                  </button>
                  {!closed && (
                    <div className="space-y-2">
                      {items.map((item) => (
                        <CatalogCard
                          key={item.type}
                          themeMode={themeMode}
                          borderColor={colors.border}
                          accentColor={nexuzCatColor[cat] || colors.primary}
                          secondaryText={colors.secondaryText}
                          title={item.label}
                          subtitle={item.type}
                          dragType={item.type}
                          onClick={() => onAddNexuzNode?.(item.type)}
                        />
                      ))}
                      {cat === '自定义' && (
                        <button
                          type="button"
                          onClick={() => setCreateBlockOpen(true)}
                          title="新建自定义积木"
                          style={{
                            backgroundColor:
                              themeMode === 'light'
                                ? 'rgba(255, 255, 255, 0.4)'
                                : 'rgba(255, 255, 255, 0.02)',
                            borderColor: colors.border,
                          }}
                          className={cn(
                            'w-full px-3 py-2 rounded-2xl border transition-all duration-200',
                            'hover:scale-[1.02] active:scale-[0.98] hover:shadow-md',
                            'hover:border-emerald-400',
                            'flex items-center justify-center gap-2',
                          )}
                        >
                          <Plus className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                          <span className="font-semibold text-sm text-emerald-600 dark:text-emerald-400">
                            新建积木
                          </span>
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            <UserBlockCreateDialog
              open={createBlockOpen}
              onOpenChange={setCreateBlockOpen}
              themeMode={themeMode}
            />

          </TabsContent>

          <TabsContent value="variables" className="m-0 data-[state=inactive]:hidden overflow-y-auto">
            <VariablesPanel themeName={themeName} themeMode={themeMode} />
            <SchedulePanel themeName={themeName} themeMode={themeMode} />
          </TabsContent>

          <TabsContent value="templates" className="m-0 data-[state=inactive]:hidden overflow-y-auto">
            <TemplatesPanel
              themeName={themeName}
              themeMode={themeMode}
              onLoadBuiltin={onLoadTemplate}
            />
          </TabsContent>

          <TabsContent value="history" className="p-4 space-y-4 m-0 data-[state=inactive]:hidden">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-display font-semibold text-sm opacity-80">Execution Runs</h3>
                <p style={{ color: colors.secondaryText }} className="text-xs">
                  当前会话执行记录
                </p>
              </div>
              {runHistory.length > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onClearHistory}
                  className="text-red-500 hover:text-red-400"
                >
                  <Trash2 className="w-3 h-3" />
                  Clear
                </Button>
              )}
            </div>

            {runHistory.length === 0 ? (
              <div
                style={{ color: colors.secondaryText }}
                className="text-center py-12 text-xs border border-dashed rounded-2xl"
              >
                <FolderSync className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <span>暂无执行记录</span>
              </div>
            ) : (
              <div className="space-y-2.5">
                {runHistory.map((run) => (
                  <div
                    key={run.id}
                    style={{
                      backgroundColor:
                        themeMode === 'light'
                          ? 'rgba(255, 255, 255, 0.35)'
                          : 'rgba(255, 255, 255, 0.02)',
                      borderColor: colors.border,
                    }}
                    className="p-3 rounded-2xl border text-xs space-y-1.5"
                  >
                    <div className="flex justify-between items-center gap-2">
                      <span className="font-semibold truncate">{run.workflowName}</span>
                      <Badge
                        variant={run.status === 'completed' ? 'secondary' : 'destructive'}
                        style={
                          run.status === 'completed'
                            ? {
                                backgroundColor: 'rgba(52, 199, 89, 0.12)',
                                color: '#34C759',
                              }
                            : undefined
                        }
                      >
                        {run.status}
                      </Badge>
                    </div>
                    <div
                      style={{ color: colors.secondaryText }}
                      className="flex justify-between font-mono text-xs"
                    >
                      <span>{run.timestamp}</span>
                      <span className="opacity-60">ID: {run.id.substring(0, 6)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
        </div>
      </Tabs>
        )}
      </div>
    </aside>
  );
}
