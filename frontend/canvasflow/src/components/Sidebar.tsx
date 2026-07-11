import React, { useMemo, useState } from 'react';
import { Plus, Trash2, FolderSync, Search } from 'lucide-react';
import { NodeType, ThemeName, ThemeMode, WorkflowNode } from '../types';
import { getThemeColors } from '../theme';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import VariablesPanel from './VariablesPanel';
import SchedulePanel from './SchedulePanel';

interface SidebarProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
  onAddNode: (subType: string, customProps?: Partial<WorkflowNode>) => void;
  onAddNexuzNode?: (blockType: string) => void;
  nexuzSchemas?: { type: string; label: string; category?: string }[];
  onLoadTemplate: (templateId: string) => void;
  runHistory: { id: string; timestamp: string; status: string; workflowName: string }[];
  onClearHistory: () => void;
  /** Disable catalog clicks while a flow is running */
  interactionLocked?: boolean;
}

const componentsList = [
  {
    category: 'AI Engines',
    color: '#4F8CFF',
    items: [
      {
        name: 'ChatGPT Agent',
        subType: 'chatgpt',
        type: 'AI' as NodeType,
        description: 'Generates natural language using server-side Gemini.',
      },
      {
        name: 'AI Translator',
        subType: 'translator',
        type: 'AI' as NodeType,
        description: 'Translates inputs into targeted languages.',
      },
      {
        name: 'AI Summarizer',
        subType: 'summarizer',
        type: 'AI' as NodeType,
        description: 'Condenses bulk inputs into brief summaries.',
      },
    ],
  },
  {
    category: 'Data Integrations',
    color: '#34C759',
    items: [
      {
        name: 'Key-Value Store',
        subType: 'kv-store',
        type: 'Database' as NodeType,
        description: 'Read or write key-value records.',
      },
    ],
  },
  {
    category: 'Connectivity',
    color: '#AF52DE',
    items: [
      {
        name: 'HTTP API Webhook',
        subType: 'api-request',
        type: 'HTTP' as NodeType,
        description: 'Fetches JSON from an API endpoint.',
      },
    ],
  },
  {
    category: 'Logic & Routing',
    color: '#FF9500',
    items: [
      {
        name: 'If-Else Switch',
        subType: 'if-else',
        type: 'Condition' as NodeType,
        description: 'Branches execution on conditions.',
      },
      {
        name: 'User Text Input',
        subType: 'user-input',
        type: 'Logic' as NodeType,
        description: 'Hardcoded text source node.',
      },
    ],
  },
  {
    category: 'Publishing',
    color: '#FF5E57',
    items: [
      {
        name: 'Log Terminal',
        subType: 'log-viewer',
        type: 'End' as NodeType,
        description: 'Renders execution output.',
      },
    ],
  },
];

const templatesList = [
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
  {
    id: 'translator-pipe',
    name: 'Translation Pipeline',
    description: 'User text → translate → log',
  },
  {
    id: 'news-summary',
    name: 'Auto-Summarizer DB Sync',
    description: 'API fetch → summarize → store',
  },
  {
    id: 'conditional-agent',
    name: 'Conditional Chat Branching',
    description: 'Condition → ChatGPT → report',
  },
];

const nexuzCatColor: Record<string, string> = {
  动作类: '#FF9500',
  识别类: '#4F8CFF',
  控制类: '#AF52DE',
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
        'w-full text-left p-3 rounded-2xl border transition-all duration-200',
        'hover:scale-[1.02] active:scale-[0.98] hover:shadow-md group cursor-grab active:cursor-grabbing',
        hoverBorderClass,
      )}
      title={dragType ? '点击添加，或拖到画布' : undefined}
    >
      <div className="flex justify-between items-center mb-1 gap-2">
        <span className="font-semibold text-sm group-hover:text-blue-500 transition-colors truncate">
          {title}
        </span>
        <div
          style={{ backgroundColor: accentColor + '1A' }}
          className="p-1 rounded-lg shrink-0"
        >
          <Plus className="w-3.5 h-3.5" style={{ color: accentColor }} />
        </div>
      </div>
      <p className="text-xs leading-relaxed opacity-90 line-clamp-2" style={{ color: secondaryText }}>
        {subtitle}
      </p>
    </button>
  );
}

export default function Sidebar({
  themeName,
  themeMode,
  onAddNode,
  onAddNexuzNode,
  nexuzSchemas = [],
  onLoadTemplate,
  runHistory,
  onClearHistory,
  interactionLocked = false,
}: SidebarProps) {
  const colors = getThemeColors(themeName, themeMode);
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();

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
    const order = ['动作类', '识别类', '控制类'];
    const sorted: Record<string, typeof nexuzSchemas> = {};
    for (const cat of order) {
      if (grouped[cat]?.length) sorted[cat] = grouped[cat];
    }
    for (const [cat, items] of Object.entries(grouped)) {
      if (!sorted[cat]) sorted[cat] = items;
    }
    return sorted;
  }, [nexuzSchemas, q]);

  const filteredComponents = useMemo(() => {
    if (!q) return componentsList;
    return componentsList
      .map((cat) => ({
        ...cat,
        items: cat.items.filter(
          (item) =>
            item.name.toLowerCase().includes(q) ||
            item.subType.toLowerCase().includes(q) ||
            item.description.toLowerCase().includes(q) ||
            cat.category.toLowerCase().includes(q),
        ),
      }))
      .filter((cat) => cat.items.length > 0);
  }, [q]);

  return (
    <aside
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      className={`w-80 border-r flex flex-col h-full backdrop-blur-xl z-30 shrink-0 ${
        interactionLocked ? 'pointer-events-none opacity-60' : ''
      }`}
    >
      <Tabs defaultValue="components" className="flex flex-col h-full min-h-0">
        <TabsList
          className="shrink-0"
          style={{ borderColor: colors.border }}
        >
          <TabsTrigger value="components">Nodes</TabsTrigger>
          <TabsTrigger value="variables">Vars</TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
          <TabsTrigger value="history">Runs</TabsTrigger>
        </TabsList>

        <div className="flex-1 min-h-0 overflow-y-auto">
          <TabsContent value="components" className="p-4 space-y-5 m-0 data-[state=inactive]:hidden">
            <div>
              <h3 className="font-display font-semibold text-sm opacity-80 mb-1">
                Library Catalogue
              </h3>
              <p style={{ color: colors.secondaryText }} className="text-xs mb-3">
                点击添加，或拖到画布；下方设计稿节点保留未接入。
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

            {Object.entries(nexuzGrouped).map(([cat, items]) => (
              <div key={`nexuz-${cat}`} className="space-y-2">
                <div className="flex items-center gap-2 px-1">
                  <span
                    style={{ backgroundColor: nexuzCatColor[cat] || colors.primary }}
                    className="w-2 h-2 rounded-full shadow-sm"
                  />
                  <span
                    style={{ color: colors.secondaryText }}
                    className="text-xs font-bold uppercase tracking-wider"
                  >
                    Nexuz · {cat}
                  </span>
                </div>
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
                </div>
              </div>
            ))}

            {filteredComponents.map((cat) => (
              <div key={cat.category} className="space-y-2">
                <div className="flex items-center gap-2 px-1">
                  <span style={{ backgroundColor: cat.color }} className="w-2 h-2 rounded-full shadow-sm" />
                  <span
                    style={{ color: colors.secondaryText }}
                    className="text-xs font-bold uppercase tracking-wider"
                  >
                    {cat.category}
                  </span>
                </div>
                <div className="space-y-2">
                  {cat.items.map((item) => (
                    <CatalogCard
                      key={item.subType}
                      themeMode={themeMode}
                      borderColor={colors.border}
                      accentColor={cat.color}
                      secondaryText={colors.secondaryText}
                      title={item.name}
                      subtitle={item.description}
                      onClick={() => onAddNode(item.subType)}
                    />
                  ))}
                </div>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="variables" className="m-0 data-[state=inactive]:hidden overflow-y-auto">
            <VariablesPanel themeName={themeName} themeMode={themeMode} />
            <SchedulePanel themeName={themeName} themeMode={themeMode} />
          </TabsContent>

          <TabsContent value="templates" className="p-4 space-y-4 m-0 data-[state=inactive]:hidden">
            <div>
              <h3 className="font-display font-semibold text-sm opacity-80 mb-1">
                Pre-built Pipelines
              </h3>
              <p style={{ color: colors.secondaryText }} className="text-xs">
                选择模板清空画布并填充节点。
              </p>
            </div>
            <div className="space-y-3">
              {templatesList.map((tpl) => (
                <CatalogCard
                  key={tpl.id}
                  themeMode={themeMode}
                  borderColor={colors.border}
                  accentColor="#34C759"
                  secondaryText={colors.secondaryText}
                  title={tpl.name}
                  subtitle={tpl.description}
                  onClick={() => onLoadTemplate(tpl.id)}
                  hoverBorderClass="hover:border-emerald-400"
                />
              ))}
            </div>
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
                      className="flex justify-between font-mono text-[10px]"
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
    </aside>
  );
}
