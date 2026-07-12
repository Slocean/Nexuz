import React, { useState, useRef, useEffect } from "react";
import { 
  Sparkles, 
  Send, 
  X, 
  Plus, 
  Loader2, 
  Bot, 
  User, 
  Cpu 
} from "lucide-react";
import { AIAssistantMessage, ThemeName, ThemeMode, WorkflowNode } from "../types";
import { getThemeColors } from "../theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

interface AIAssistantProps {
  isOpen: boolean;
  onClose: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  workflowContext: WorkflowNode[];
  onAddCustomNode: (nodeData: any) => void;
}

export default function AIAssistant({
  isOpen,
  onClose,
  themeName,
  themeMode,
  workflowContext,
  onAddCustomNode,
}: AIAssistantProps) {
  const [messages, setMessages] = useState<AIAssistantMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content: "Hello! I am your CanvasFlow AI Orchestrator. Tell me what pipeline you want to build (e.g., 'Make an AI translator from a user text prompt' or 'Fetch web API news and summarize it'), and I will automatically design the node connections for you!",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const colors = getThemeColors(themeName, themeMode);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  if (!isOpen) return null;

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading) return;

    const userMsg: AIAssistantMessage = {
      id: Math.random().toString(),
      role: "user",
      content: inputValue,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");
    setIsLoading(true);

    try {
      const response = await fetch("/api/ai-assistant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg.content,
          workflowContext: workflowContext.map(n => ({ id: n.id, type: n.type, name: n.name, subType: n.subType }))
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to contact workspace AI assistant.");
      }

      const data = await response.json();

      const assistantMsg: AIAssistantMessage = {
        id: Math.random().toString(),
        role: "assistant",
        content: data.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        suggestedAction: data.suggestNodes ? {
          type: "create_nodes",
          payload: data.suggestNodes
        } : undefined
      };

      setMessages((prev) => [...prev, assistantMsg]);

    } catch (err: any) {
      console.error(err);
      setMessages((prev) => [...prev, {
        id: Math.random().toString(),
        role: "assistant",
        content: "Sorry, I had trouble running your query through server-side Gemini. Let's try another request!",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const executeAction = (payload: any[]) => {
    payload.forEach((node) => {
      onAddCustomNode(node);
    });
    // Add success feedback message
    setMessages((prev) => [...prev, {
      id: Math.random().toString(),
      role: "assistant",
      content: "✨ Success! I've placed the suggested node cards onto your workspace grid. You can wire up their input/output sockets now!",
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }]);
  };

  return (
    <div 
      style={{ 
        backgroundColor: themeMode === "light" ? "rgba(255, 255, 255, 0.96)" : "rgba(15, 20, 32, 0.98)",
        borderColor: colors.border,
        color: colors.text 
      }}
      className="w-96 border-l h-full flex flex-col backdrop-blur-3xl z-40 relative shadow-2xl animate-in slide-in-from-right duration-300"
    >
      {/* Header */}
      <div className="p-4 border-b border-black/10 dark:border-white/10 flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2.5">
          <div className="p-1.5 bg-blue-500/10 rounded-xl">
            <Sparkles className="w-5 h-5 text-blue-500 animate-pulse" />
          </div>
          <div>
            <h3 className="font-display font-semibold text-sm">Flow AI Orchestrator</h3>
            <p className="text-[11px] text-emerald-500 font-mono tracking-wider uppercase">Active Gemini model</p>
          </div>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Messages Scroll Panel */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => {
          const isAi = msg.role === "assistant";
          return (
            <div 
              key={msg.id}
              className={`flex items-start space-x-2.5 max-w-[90%] ${!isAi ? "ml-auto flex-row-reverse space-x-reverse" : ""}`}
            >
              {/* Profile Bubble */}
              <div 
                className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-white ${
                  isAi 
                    ? "bg-gradient-to-tr from-blue-500 to-indigo-500" 
                    : "bg-slate-700"
                }`}
              >
                {isAi ? <Bot className="w-4 h-4" /> : <User className="w-4 h-4" />}
              </div>

              {/* Message Payload */}
              <div className="space-y-1">
                <div 
                  style={{ 
                    backgroundColor: isAi 
                      ? (themeMode === "light" ? "rgba(0, 0, 0, 0.03)" : "rgba(255, 255, 255, 0.03)") 
                      : colors.primary,
                    color: isAi ? colors.text : "#FFFFFF"
                  }}
                  className={`p-3 rounded-2xl text-xs leading-relaxed border ${
                    isAi 
                      ? "border-black/10 dark:border-white/10 rounded-tl-none" 
                      : "border-transparent rounded-tr-none"
                  }`}
                >
                  <p className="whitespace-pre-wrap select-text">{msg.content}</p>

                  {/* Nodes Suggestion Button Action */}
                  {isAi && msg.suggestedAction && (
                    <div className="mt-3 pt-3 border-t border-black/10 dark:border-white/10 space-y-2">
                      <div className="flex items-center space-x-1 text-[11px] text-blue-400 font-bold uppercase tracking-wider">
                        <Cpu className="w-3.5 h-3.5" />
                        <span>Recommended Workspace Nodes:</span>
                      </div>
                      
                      <div className="flex flex-wrap gap-1.5">
                        {msg.suggestedAction.payload.map((node: any, nidx: number) => (
                          <Badge key={nidx} variant="secondary">
                            {node.name} ({node.subType})
                          </Badge>
                        ))}
                      </div>

                      <Button
                        size="sm"
                        className="w-full mt-2"
                        style={{ backgroundColor: colors.primary }}
                        onClick={() => executeAction(msg.suggestedAction!.payload)}
                      >
                        <Plus className="w-4 h-4" />
                        Deploy AI Nodes to Canvas
                      </Button>
                    </div>
                  )}
                </div>
                
                <div 
                  className={`text-[10px] font-mono text-slate-400 px-1 ${
                    !isAi ? "text-right" : ""
                  }`}
                >
                  {msg.timestamp}
                </div>
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="flex items-start space-x-2.5">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-blue-500 to-indigo-500 flex items-center justify-center text-white shrink-0 animate-bounce">
              <Bot className="w-4 h-4" />
            </div>
            <div className="bg-black/5 dark:bg-white/5 p-3 rounded-2xl rounded-tl-none border border-black/10 dark:border-white/10 flex items-center space-x-2 text-xs">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
              <span className="text-slate-400 italic">Thinking up workflow node configurations...</span>
            </div>
          </div>
        )}
      </div>

      {/* Message input footer form */}
      <form onSubmit={handleSend} className="p-4 border-t border-black/10 dark:border-white/10 shrink-0">
        <div className="relative flex items-center gap-2">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type 'Make a summary chatbot'..."
            className="pr-11 h-11 rounded-2xl text-xs"
          />
          <Button
            type="submit"
            size="icon"
            disabled={!inputValue.trim() || isLoading}
            className="absolute right-1.5 h-8 w-8"
            style={{
              backgroundColor: inputValue.trim() && !isLoading ? colors.primary : undefined,
            }}
          >
            <Send className="w-3.5 h-3.5" />
          </Button>
        </div>
      </form>
    </div>
  );
}
