import React from "react";
import { 
  Settings, 
  Play, 
  Terminal, 
  Database, 
  X, 
  Layers, 
  HelpCircle,
  Copy,
  Check,
  ChevronRight
} from "lucide-react";
import { WorkflowNode, ThemeName, ThemeMode, ExecutionLog } from "../types";
import { getThemeColors } from "../theme";

interface InspectorProps {
  selectedNode: WorkflowNode | null;
  onUpdateNodeConfig: (nodeId: string, updatedConfig: any) => void;
  onRunSingleNode: (nodeId: string) => void;
  onDeselect: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  logs: ExecutionLog[];
}

export default function Inspector({
  selectedNode,
  onUpdateNodeConfig,
  onRunSingleNode,
  onDeselect,
  themeName,
  themeMode,
  logs,
}: InspectorProps) {
  const [copied, setCopied] = React.useState(false);

  const colors = getThemeColors(themeName, themeMode);

  if (!selectedNode) {
    return (
      <aside 
        style={{ 
          backgroundColor: colors.surface, 
          borderColor: colors.border,
          color: colors.text 
        }}
        className="w-80 border-l flex flex-col h-full backdrop-blur-xl transition-all duration-300 z-30 shrink-0 p-6 items-center justify-center text-center"
      >
        <div className="space-y-3 opacity-60">
          <div 
            style={{ backgroundColor: colors.primary + "1A" }}
            className="w-12 h-12 rounded-2xl mx-auto flex items-center justify-center"
          >
            <Settings style={{ color: colors.primary }} className="w-6 h-6 animate-spin-slow" />
          </div>
          <h3 className="font-display font-semibold text-sm">No node selected</h3>
          <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed max-w-[200px] mx-auto">
            Click on any node card in the workspace canvas to adjust parameters, check API endpoints, or view execution logs.
          </p>
        </div>
      </aside>
    );
  }

  // Handle parameter field updates
  const handleFieldChange = (key: string, value: any) => {
    onUpdateNodeConfig(selectedNode.id, {
      ...selectedNode.config,
      [key]: value
    });
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderParametersForm = () => {
    const { subType, config } = selectedNode;

    switch (subType) {
      case "chatgpt":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                AI Instruction
              </label>
              <input
                type="text"
                value={config.systemInstruction || "You are a helpful assistant."}
                onChange={(e) => handleFieldChange("systemInstruction", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="e.g. You are a translation expert."
              />
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Prompt Template
              </label>
              <textarea
                rows={4}
                value={config.prompt || ""}
                onChange={(e) => handleFieldChange("prompt", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors resize-none font-sans"
                placeholder="Enter AI core prompt. Reference input variables if needed."
              />
            </div>

            <div className="flex flex-col space-y-1.5">
              <div className="flex justify-between items-center text-[11px] font-bold uppercase tracking-wider opacity-75">
                <span>Temperature</span>
                <span className="font-mono">{config.temperature ?? 0.7}</span>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={config.temperature ?? 0.7}
                onChange={(e) => handleFieldChange("temperature", parseFloat(e.target.value))}
                className="w-full accent-blue-500 cursor-pointer h-1 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none"
              />
            </div>
          </div>
        );

      case "translator":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Target Language
              </label>
              <select
                value={config.targetLanguage || "Spanish"}
                onChange={(e) => handleFieldChange("targetLanguage", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(255,255,255,0.9)" : "#131826",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
              >
                <option value="Spanish">Spanish 🇪🇸</option>
                <option value="French">French 🇫🇷</option>
                <option value="German">German 🇩🇪</option>
                <option value="Japanese">Japanese 🇯🇵</option>
                <option value="Chinese">Chinese 🇨🇳</option>
                <option value="Arabic">Arabic 🇸🇦</option>
              </select>
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Fallback Input Text
              </label>
              <textarea
                rows={3}
                value={config.text || ""}
                onChange={(e) => handleFieldChange("text", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors resize-none"
                placeholder="Text to translate if no upstream input is wired."
              />
            </div>
          </div>
        );

      case "summarizer":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Maximum Word Limit
              </label>
              <input
                type="number"
                value={config.wordLimit || 30}
                onChange={(e) => handleFieldChange("wordLimit", parseInt(e.target.value) || 30)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Fallback Content
              </label>
              <textarea
                rows={3}
                value={config.text || ""}
                onChange={(e) => handleFieldChange("text", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors resize-none"
                placeholder="Enter raw article / document text."
              />
            </div>
          </div>
        );

      case "kv-store":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Database Operation
              </label>
              <select
                value={config.operation || "write"}
                onChange={(e) => handleFieldChange("operation", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(255,255,255,0.9)" : "#131826",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
              >
                <option value="write">Write/Store Record</option>
                <option value="read">Read Record</option>
              </select>
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Storage Key Name
              </label>
              <input
                type="text"
                value={config.key || ""}
                onChange={(e) => handleFieldChange("key", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="e.g. summary_data_v1"
              />
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Default Value
              </label>
              <input
                type="text"
                value={config.value || ""}
                onChange={(e) => handleFieldChange("value", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="Value if no input is wired"
              />
            </div>
          </div>
        );

      case "api-request":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                REST Method
              </label>
              <select
                value={config.method || "GET"}
                onChange={(e) => handleFieldChange("method", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(255,255,255,0.9)" : "#131826",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
              >
                <option value="GET">GET (Retrieve)</option>
                <option value="POST">POST (Create)</option>
                <option value="PUT">PUT (Replace)</option>
              </select>
            </div>

            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Target Endpoint URL
              </label>
              <input
                type="text"
                value={config.url || "https://api.example.com/feed"}
                onChange={(e) => handleFieldChange("url", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>
        );

      case "if-else":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Branching Rule / Condition
              </label>
              <select
                value={config.condition || "true"}
                onChange={(e) => handleFieldChange("condition", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(255,255,255,0.9)" : "#131826",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors cursor-pointer"
              >
                <option value="true">Condition IS Met (TRUE branch)</option>
                <option value="false">Condition NOT Met (FALSE branch)</option>
              </select>
            </div>
          </div>
        );

      case "user-input":
        return (
          <div className="space-y-4">
            <div className="flex flex-col space-y-1.5">
              <label className="text-[11px] font-bold uppercase tracking-wider opacity-75">
                Custom Text Payload
              </label>
              <textarea
                rows={5}
                value={config.value || ""}
                onChange={(e) => handleFieldChange("value", e.target.value)}
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                  borderColor: colors.border 
                }}
                className="p-2.5 rounded-xl border text-xs focus:outline-none focus:border-blue-500 transition-colors font-sans"
                placeholder="Enter string content to serve as source."
              />
            </div>
          </div>
        );

      default:
        return (
          <div className="text-center py-6 text-xs text-slate-400 border border-dashed border-white/10 rounded-2xl">
            This node prints workflow output data. No configurable parameters required.
          </div>
        );
    }
  };

  const nodeLogs = logs.filter(l => l.nodeId === selectedNode.id);

  return (
    <aside 
      style={{ 
        backgroundColor: colors.surface, 
        borderColor: colors.border,
        color: colors.text 
      }}
      className="w-80 border-l flex flex-col h-full backdrop-blur-xl transition-all duration-300 z-30 shrink-0"
    >
      {/* 1. Header Row */}
      <div className="p-4 border-b border-black/5 dark:border-white/5 flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2">
          <Settings className="w-4 h-4 text-slate-400" />
          <h3 className="font-display font-semibold text-sm">Node Settings</h3>
        </div>
        <button
          onClick={onDeselect}
          className="p-1.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/5 transition-all text-slate-400 hover:text-slate-200 cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* 2. Scrollable Body Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Node description */}
        <div className="bg-black/5 dark:bg-white/5 rounded-2xl p-3.5 border border-white/5">
          <div className="flex justify-between items-center mb-1.5">
            <span className="font-bold text-xs uppercase tracking-wide opacity-90 text-blue-400">
              {selectedNode.type}
            </span>
            <span className="text-[10px] opacity-50 font-mono">ID: {selectedNode.id.substring(0,6)}</span>
          </div>
          <h4 className="font-display font-semibold text-sm mb-1">{selectedNode.name}</h4>
          <p style={{ color: colors.secondaryText }} className="text-xs leading-relaxed">
            Configure dynamic fields below. These will propagate to connected downstream nodes during runtime execution.
          </p>
        </div>

        {/* Dynamic Form */}
        <div className="space-y-4">
          <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
            Node Parameters
          </h4>
          {renderParametersForm()}
        </div>

        {/* Executed Results Output Console */}
        <div className="space-y-3.5 pt-4 border-t border-black/5 dark:border-white/5">
          <div className="flex justify-between items-center">
            <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
              Terminal Output
            </h4>
            {selectedNode.outputData && (
              <button
                onClick={() => copyToClipboard(typeof selectedNode.outputData === 'string' ? selectedNode.outputData : JSON.stringify(selectedNode.outputData, null, 2))}
                className="text-xs text-blue-500 hover:underline flex items-center space-x-1 cursor-pointer"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3 text-emerald-500" />
                    <span className="text-emerald-500">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    <span>Copy</span>
                  </>
                )}
              </button>
            )}
          </div>

          <div 
            style={{ 
              backgroundColor: themeMode === "light" ? "#F1F5F9" : "#05070A",
              borderColor: colors.border
            }}
            className="rounded-2xl p-3 border font-mono text-[11px] h-36 overflow-y-auto leading-relaxed relative flex flex-col justify-between"
          >
            <div className="text-slate-400 select-text overflow-x-hidden break-all">
              {selectedNode.outputData ? (
                typeof selectedNode.outputData === 'string' ? (
                  <span className="text-slate-800 dark:text-slate-300">{selectedNode.outputData}</span>
                ) : (
                  <pre className="text-slate-800 dark:text-slate-300 whitespace-pre-wrap">{JSON.stringify(selectedNode.outputData, null, 2)}</pre>
                )
              ) : (
                <span className="text-slate-400 italic">No execution payload found. Trigger "Run Pipeline" to compute values.</span>
              )}
            </div>
            
            {/* Run node individually button inside console */}
            <button
              onClick={() => onRunSingleNode(selectedNode.id)}
              className="mt-3 w-full py-1.5 rounded-xl bg-slate-200 dark:bg-white/5 hover:bg-slate-300 dark:hover:bg-white/10 text-slate-800 dark:text-slate-200 transition-all font-sans font-medium text-xs flex items-center justify-center space-x-1 border border-white/5 cursor-pointer"
            >
              <Play className="w-3 h-3 fill-current text-blue-500" />
              <span>Compute Node Solo</span>
            </button>
          </div>
        </div>

        {/* Localized node error logs */}
        {nodeLogs.length > 0 && (
          <div className="space-y-2 pt-3 border-t border-black/5 dark:border-white/5">
            <h4 className="font-display font-bold text-xs uppercase tracking-wider opacity-60">
              Debug Console
            </h4>
            <div className="space-y-1.5 max-h-32 overflow-y-auto">
              {nodeLogs.map((log) => (
                <div 
                  key={log.id} 
                  className={`text-[10px] font-mono leading-relaxed p-2 rounded-xl flex items-start space-x-1.5 border ${
                    log.type === "error" 
                      ? "bg-rose-500/10 border-rose-500/20 text-rose-400" 
                      : log.type === "warning"
                      ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
                      : "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                  }`}
                >
                  <ChevronRight className="w-3 h-3 shrink-0 mt-0.5" />
                  <span className="break-all">{log.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
