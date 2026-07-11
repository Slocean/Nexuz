import React, { useState } from "react";
import { 
  Play, 
  Save, 
  Sun, 
  Moon, 
  Sparkles, 
  Palette, 
  Workflow, 
  RefreshCw,
  Check,
  Cpu
} from "lucide-react";
import { ThemeName, ThemeMode } from "../types";
import { getThemeColors } from "../theme";

interface ToolbarProps {
  workflowName: string;
  setWorkflowName: (name: string) => void;
  themeName: ThemeName;
  setThemeName: (name: ThemeName) => void;
  themeMode: ThemeMode;
  setThemeMode: (mode: ThemeMode) => void;
  onRunWorkflow: () => void;
  isExecuting: boolean;
  onToggleAssistant: () => void;
  isAssistantOpen: boolean;
  onClearCanvas: () => void;
}

export default function Toolbar({
  workflowName,
  setWorkflowName,
  themeName,
  setThemeName,
  themeMode,
  setThemeMode,
  onRunWorkflow,
  isExecuting,
  onToggleAssistant,
  isAssistantOpen,
  onClearCanvas,
}: ToolbarProps) {
  const [isSaved, setIsSaved] = useState(false);
  const [showThemeMenu, setShowThemeMenu] = useState(false);

  const colors = getThemeColors(themeName, themeMode);

  const themes: ThemeName[] = ["Ocean", "Mint", "Purple", "Rose", "Orange"];

  const handleSave = () => {
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  return (
    <header 
      style={{ 
        backgroundColor: colors.surface, 
        borderColor: colors.border,
        color: colors.text 
      }}
      className="h-16 px-6 border-b flex items-center justify-between backdrop-blur-xl transition-all duration-300 z-40 shrink-0"
    >
      {/* Brand & Title */}
      <div className="flex items-center space-x-4">
        <div 
          style={{ backgroundColor: colors.primary + "1A" }}
          className="p-2.5 rounded-2xl flex items-center justify-center transition-all duration-300 hover:rotate-12"
        >
          <Workflow style={{ color: colors.primary }} className="w-6 h-6 animate-pulse" />
        </div>
        <div className="flex items-center space-x-2">
          <input
            type="text"
            value={workflowName}
            onChange={(e) => setWorkflowName(e.target.value)}
            style={{ color: colors.text }}
            className="font-display font-semibold text-lg bg-transparent border-b border-transparent hover:border-white/20 focus:border-blue-500 focus:outline-none transition-all px-1 py-0.5 rounded"
            placeholder="Untitled Flow"
          />
          <span 
            style={{ backgroundColor: colors.primary + "12", color: colors.primary }}
            className="text-xs px-2 py-0.5 rounded-full font-mono font-medium tracking-wide uppercase"
          >
            v1.0
          </span>
        </div>
      </div>

      {/* Center Actions - Execution Controls */}
      <div className="flex items-center space-x-3 bg-black/5 dark:bg-white/5 p-1.5 rounded-2xl border border-white/5">
        <button
          onClick={onRunWorkflow}
          disabled={isExecuting}
          style={{ 
            backgroundColor: isExecuting ? colors.secondaryText + "20" : colors.primary,
            color: "#FFFFFF"
          }}
          className="flex items-center space-x-2 px-4 py-1.5 rounded-xl font-medium text-sm shadow-sm hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 transition-all cursor-pointer"
        >
          {isExecuting ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Running Node Pipe...</span>
            </>
          ) : (
            <>
              <Play className="w-4 h-4 fill-current" />
              <span>Run Pipeline</span>
            </>
          )}
        </button>

        <button
          onClick={handleSave}
          style={{ color: colors.text }}
          className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl hover:bg-black/5 dark:hover:bg-white/5 text-sm transition-all cursor-pointer"
        >
          {isSaved ? (
            <>
              <Check className="w-4 h-4 text-emerald-500" />
              <span className="text-emerald-500 font-medium">Saved!</span>
            </>
          ) : (
            <>
              <Save className="w-4 h-4 opacity-80" />
              <span>Save</span>
            </>
          )}
        </button>

        <button
          onClick={onClearCanvas}
          style={{ color: colors.danger }}
          className="px-3 py-1.5 text-sm font-medium rounded-xl hover:bg-red-500/10 transition-all cursor-pointer"
        >
          Clear Workspace
        </button>
      </div>

      {/* Right Controls - Theme and Assistant */}
      <div className="flex items-center space-x-3">
        {/* Theme Settings Trigger */}
        <div className="relative">
          <button
            onClick={() => setShowThemeMenu(!showThemeMenu)}
            style={{ color: colors.text }}
            className="p-2.5 rounded-2xl hover:bg-black/5 dark:hover:bg-white/5 transition-all border border-transparent hover:border-white/10 flex items-center justify-center cursor-pointer"
            title="Switch Workspace Theme"
          >
            <Palette className="w-5 h-5 opacity-80" />
          </button>

          {showThemeMenu && (
            <>
              <div 
                className="fixed inset-0 z-40" 
                onClick={() => setShowThemeMenu(false)} 
              />
              <div 
                style={{ 
                  backgroundColor: themeMode === "light" ? "rgba(255, 255, 255, 0.95)" : "rgba(18, 22, 35, 0.95)",
                  borderColor: colors.border,
                  color: colors.text 
                }}
                className="absolute right-0 mt-2.5 w-48 rounded-2xl border p-3 shadow-2xl backdrop-blur-2xl z-50 flex flex-col space-y-2 animate-in fade-in slide-in-from-top-3 duration-200"
              >
                <div className="text-xs font-semibold px-2 py-1 text-slate-400 uppercase tracking-wider font-display">
                  Color Theme
                </div>
                {themes.map((t) => (
                  <button
                    key={t}
                    onClick={() => {
                      setThemeName(t);
                      setShowThemeMenu(false);
                    }}
                    className="flex items-center justify-between px-3 py-2 rounded-xl text-sm text-left transition-all hover:bg-black/5 dark:hover:bg-white/5"
                  >
                    <div className="flex items-center space-x-2">
                      <span 
                        style={{ backgroundColor: getThemeColors(t, themeMode).primary }}
                        className="w-3.5 h-3.5 rounded-full border border-white/20"
                      />
                      <span>{t}</span>
                    </div>
                    {themeName === t && (
                      <Check className="w-4 h-4 text-emerald-500" />
                    )}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Light/Dark Mode Toggler */}
        <button
          onClick={() => setThemeMode(themeMode === "light" ? "dark" : "light")}
          style={{ color: colors.text }}
          className="p-2.5 rounded-2xl hover:bg-black/5 dark:hover:bg-white/5 transition-all border border-transparent hover:border-white/10 flex items-center justify-center cursor-pointer"
          title={themeMode === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
        >
          {themeMode === "light" ? (
            <Moon className="w-5 h-5 opacity-80" />
          ) : (
            <Sun className="w-5 h-5 opacity-80" />
          )}
        </button>

        {/* Workspace Assistant Toggle */}
        <button
          onClick={onToggleAssistant}
          style={{ 
            backgroundColor: isAssistantOpen ? colors.primary : colors.primary + "15",
            borderColor: colors.primary + "30",
            color: isAssistantOpen ? "#FFFFFF" : colors.primary
          }}
          className={`flex items-center space-x-2 px-4 py-2 rounded-2xl border font-medium text-sm shadow-sm transition-all duration-300 cursor-pointer ${
            !isAssistantOpen ? "animate-pulse" : ""
          }`}
        >
          <Sparkles className="w-4 h-4" />
          <span>Flow AI AI Helper</span>
        </button>

        {/* Avatar badge */}
        <div 
          style={{ borderColor: colors.primary + "40" }}
          className="w-9 h-9 rounded-2xl border overflow-hidden shrink-0 flex items-center justify-center bg-gradient-to-tr from-indigo-500 via-blue-500 to-emerald-500 p-[1.5px]"
        >
          <div className="w-full h-full bg-slate-900 rounded-[14px] flex items-center justify-center text-[11px] text-white font-mono font-bold tracking-tight">
            AI
          </div>
        </div>
      </div>
    </header>
  );
}
