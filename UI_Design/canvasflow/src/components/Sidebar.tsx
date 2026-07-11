import React, { useState } from "react";
import { 
  Plus, 
  Cpu, 
  Database, 
  Globe, 
  Split, 
  Type, 
  Terminal, 
  Play, 
  Trash2,
  Bookmark,
  History,
  FolderSync
} from "lucide-react";
import { NodeType, ThemeName, ThemeMode, WorkflowNode } from "../types";
import { getThemeColors } from "../theme";

interface SidebarProps {
  themeName: ThemeName;
  themeMode: ThemeMode;
  onAddNode: (subType: string, customProps?: Partial<WorkflowNode>) => void;
  onLoadTemplate: (templateId: string) => void;
  runHistory: { id: string; timestamp: string; status: string; workflowName: string }[];
  onClearHistory: () => void;
}

export default function Sidebar({
  themeName,
  themeMode,
  onAddNode,
  onLoadTemplate,
  runHistory,
  onClearHistory,
}: SidebarProps) {
  const [activeTab, setActiveTab] = useState<"components" | "templates" | "history">("components");

  const colors = getThemeColors(themeName, themeMode);

  // Component definition catalog
  const componentsList = [
    {
      category: "AI Engines",
      color: "#4F8CFF",
      items: [
        {
          name: "🤖 ChatGPT Agent",
          subType: "chatgpt",
          type: "AI" as NodeType,
          description: "Generates natural language using server-side Gemini 3.5 Flash.",
        },
        {
          name: "✨ AI Translator",
          subType: "translator",
          type: "AI" as NodeType,
          description: "Translates inputs into targeted global languages.",
        },
        {
          name: "📝 AI Summarizer",
          subType: "summarizer",
          type: "AI" as NodeType,
          description: "Condenses bulk inputs into brief bullet point summaries.",
        }
      ]
    },
    {
      category: "Data Integrations",
      color: "#34C759",
      items: [
        {
          name: "🗄️ Key-Value Store",
          subType: "kv-store",
          type: "Database" as NodeType,
          description: "Simulates reading or writing records in a key-value store.",
        }
      ]
    },
    {
      category: "Connectivity",
      color: "#AF52DE",
      items: [
        {
          name: "🌐 HTTP API Webhook",
          subType: "api-request",
          type: "HTTP" as NodeType,
          description: "Fetches structured JSON payloads from a specified API endpoint.",
        }
      ]
    },
    {
      category: "Logic & Routing",
      color: "#FF9500",
      items: [
        {
          name: "🔀 If-Else Switch",
          subType: "if-else",
          type: "Condition" as NodeType,
          description: "Branches execution sequences based on conditional inputs.",
        },
        {
          name: "✍️ User Text Input",
          subType: "user-input",
          type: "Logic" as NodeType,
          description: "Provides a custom hardcoded text input field for execution.",
        }
      ]
    },
    {
      category: "Publishing",
      color: "#FF5E57",
      items: [
        {
          name: "📺 Log Terminal",
          subType: "log-viewer",
          type: "End" as NodeType,
          description: "Renders intermediate execution logs and output data feeds.",
        }
      ]
    }
  ];

  const templatesList = [
    {
      id: "translator-pipe",
      name: "Global Translation Pipeline",
      description: "Inputs user text, automatically translates to Spanish, and logs the response.",
      icon: "🌍"
    },
    {
      id: "news-summary",
      name: "Auto-Summarizer DB Sync",
      description: "Fetches the latest news feed from an API, summarizes, and backs up key points.",
      icon: "📰"
    },
    {
      id: "conditional-agent",
      name: "Conditional Chat Branching",
      description: "Checks if parameters are met, running ChatGPT logic to print reports.",
      icon: "⚙️"
    }
  ];

  return (
    <aside 
      style={{ 
        backgroundColor: colors.surface, 
        borderColor: colors.border,
        color: colors.text 
      }}
      className="w-80 border-r flex flex-col h-full backdrop-blur-xl transition-all duration-300 z-30 shrink-0"
    >
      {/* Drawer tabs */}
      <div className="flex border-b border-black/5 dark:border-white/5 p-2 gap-1 shrink-0">
        {(["components", "templates", "history"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{ 
              backgroundColor: activeTab === tab ? colors.primary + "1E" : "transparent",
              color: activeTab === tab ? colors.primary : colors.secondaryText
            }}
            className="flex-1 py-2 rounded-xl text-xs font-semibold uppercase tracking-wider transition-all duration-200 hover:bg-black/5 dark:hover:bg-white/5 cursor-pointer"
          >
            {tab === "components" && "Nodes"}
            {tab === "templates" && "Templates"}
            {tab === "history" && "Runs"}
          </button>
        ))}
      </div>

      {/* Drawer body scroll container */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {activeTab === "components" && (
          <div className="space-y-5 animate-in fade-in duration-200">
            <div>
              <h3 className="font-display font-semibold text-sm opacity-80 mb-1">
                Library Catalogue
              </h3>
              <p style={{ color: colors.secondaryText }} className="text-xs">
                Click a card below to dynamically deploy a node directly onto the canvas grid.
              </p>
            </div>

            {componentsList.map((cat, idx) => (
              <div key={idx} className="space-y-2">
                <div className="flex items-center space-x-2 px-1">
                  <span 
                    style={{ backgroundColor: cat.color }} 
                    className="w-2 h-2 rounded-full shadow-sm"
                  />
                  <span style={{ color: colors.secondaryText }} className="text-xs font-bold uppercase tracking-wider">
                    {cat.category}
                  </span>
                </div>

                <div className="space-y-2">
                  {cat.items.map((item, itemIdx) => (
                    <button
                      key={itemIdx}
                      onClick={() => onAddNode(item.subType)}
                      style={{ 
                        backgroundColor: themeMode === "light" ? "rgba(255, 255, 255, 0.4)" : "rgba(255, 255, 255, 0.02)",
                        borderColor: colors.border
                      }}
                      className="w-full text-left p-3 rounded-2xl border transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] hover:shadow-md hover:border-blue-400 group cursor-pointer"
                    >
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-semibold text-sm group-hover:text-blue-500 transition-colors">
                          {item.name}
                        </span>
                        <div 
                          style={{ backgroundColor: cat.color + "1A" }}
                          className="p-1 rounded-lg group-hover:bg-blue-500 group-hover:text-white transition-all duration-300"
                        >
                          <Plus className="w-3.5 h-3.5" style={{ color: cat.color }} />
                        </div>
                      </div>
                      <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed opacity-90 line-clamp-2">
                        {item.description}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {activeTab === "templates" && (
          <div className="space-y-4 animate-in fade-in duration-200">
            <div>
              <h3 className="font-display font-semibold text-sm opacity-80 mb-1">
                Pre-built Pipelines
              </h3>
              <p style={{ color: colors.secondaryText }} className="text-xs">
                Choose a pre-configured template to clear your workspace and populate nodes.
              </p>
            </div>

            <div className="space-y-3">
              {templatesList.map((tpl) => (
                <button
                  key={tpl.id}
                  onClick={() => onLoadTemplate(tpl.id)}
                  style={{ 
                    backgroundColor: themeMode === "light" ? "rgba(255, 255, 255, 0.4)" : "rgba(255, 255, 255, 0.02)",
                    borderColor: colors.border
                  }}
                  className="w-full text-left p-4 rounded-2xl border transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] hover:shadow-md hover:border-emerald-400 flex items-start space-x-3 cursor-pointer"
                >
                  <div className="text-2xl p-2 bg-black/5 dark:bg-white/5 rounded-xl shrink-0">
                    {tpl.icon}
                  </div>
                  <div>
                    <h4 className="font-semibold text-sm mb-1 text-slate-800 dark:text-slate-100">
                      {tpl.name}
                    </h4>
                    <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed opacity-90">
                      {tpl.description}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTab === "history" && (
          <div className="space-y-4 animate-in fade-in duration-200">
            <div className="flex justify-between items-center">
              <div>
                <h3 className="font-display font-semibold text-sm opacity-80">
                  Execution Runs
                </h3>
                <p style={{ color: colors.secondaryText }} className="text-xs">
                  A history of current session pipeline builds.
                </p>
              </div>
              {runHistory.length > 0 && (
                <button
                  onClick={onClearHistory}
                  className="text-xs text-red-500 hover:underline flex items-center space-x-1 cursor-pointer"
                >
                  <Trash2 className="w-3 h-3" />
                  <span>Clear</span>
                </button>
              )}
            </div>

            {runHistory.length === 0 ? (
              <div 
                style={{ color: colors.secondaryText }}
                className="text-center py-12 text-xs border border-dashed border-white/10 rounded-2xl"
              >
                <FolderSync className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <span>No pipeline executions recorded yet.</span>
              </div>
            ) : (
              <div className="space-y-2.5">
                {runHistory.map((run) => (
                  <div
                    key={run.id}
                    style={{ 
                      backgroundColor: "rgba(255, 255, 255, 0.02)",
                      borderColor: colors.border
                    }}
                    className="p-3 rounded-2xl border text-xs space-y-1.5"
                  >
                    <div className="flex justify-between items-center">
                      <span className="font-semibold text-slate-700 dark:text-slate-200 truncate max-w-[130px]">
                        {run.workflowName}
                      </span>
                      <span 
                        className={`px-1.5 py-0.5 rounded-full text-[10px] font-mono font-medium tracking-wide uppercase ${
                          run.status === "completed" 
                            ? "bg-emerald-500/10 text-emerald-500" 
                            : "bg-red-500/10 text-red-500"
                        }`}
                      >
                        {run.status}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-slate-400 font-mono text-[10px]">
                      <span>{run.timestamp}</span>
                      <span className="opacity-60">ID: {run.id.substring(0, 6)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
