import React from 'react';
import { GitBranch } from 'lucide-react';
import type { NodeConnection, ThemeMode, ThemeName, WorkflowNode } from '../types';
import { getThemeColors } from '../theme';
import FlowThumbnail from './FlowThumbnail';

type Props = {
  nodes: WorkflowNode[];
  connections: NodeConnection[];
  activeNodeId?: string | null;
  entryId?: string | null;
  execStatus?: string;
  themeName: ThemeName;
  themeMode: ThemeMode;
};

/** Full-page engineering flowchart view (toolbar viewMode === 'flowchart'). */
export default function FlowchartView({
  nodes,
  connections,
  activeNodeId = null,
  entryId = null,
  execStatus = 'idle',
  themeName,
  themeMode,
}: Props) {
  const colors = getThemeColors(themeName, themeMode);

  return (
    <div
      className="h-full w-full flex flex-col min-h-0 overflow-hidden"
      style={{ backgroundColor: colors.background, color: colors.text }}
    >
      <div
        className="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b"
        style={{ borderColor: colors.border, backgroundColor: colors.surface }}
      >
        <GitBranch className="w-4 h-4" style={{ color: colors.primary }} />
        <span className="text-sm font-semibold">流程图</span>
        <span className="text-xs opacity-50">
          由节点连线自动生成 · {nodes.length} 节点
        </span>
      </div>
      <div className="flex-1 min-h-0 p-3">
        <FlowThumbnail
          nodes={nodes}
          connections={connections}
          activeNodeId={activeNodeId}
          entryId={entryId}
          execStatus={execStatus}
          themeMode={themeMode}
          className="h-full w-full rounded-xl"
          fill
        />
      </div>
    </div>
  );
}
