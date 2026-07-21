import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  Send,
  X,
  Plus,
  Loader2,
  User,
  Trash2,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { ThemeName, ThemeMode } from "../types";
import { getThemeColors } from "../theme";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { bridge } from "@/bridge";

interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

interface ConversationItem {
  id: string;
  title: string;
  updated_at?: string;
  message_count?: number;
  model?: string;
}

interface AIAssistantProps {
  isOpen: boolean;
  onClose: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  onOpenSettings?: () => void;
}

function formatTs(isoOrLocal?: string): string {
  if (!isoOrLocal) {
    return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  try {
    const d = new Date(isoOrLocal);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
  } catch {
    /* ignore */
  }
  return isoOrLocal;
}

const WELCOME =
  "你好！我是 Nexuz Flow AI。配置好 API Key 后即可多轮对话。当前版本支持对话与会话管理；流程编排将在后续版本提供。";

export default function AIAssistant({
  isOpen,
  onClose,
  themeName,
  themeMode,
  onOpenSettings,
}: AIAssistantProps) {
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [modelLabel, setModelLabel] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [bootstrapping, setBootstrapping] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(true);

  const colors = getThemeColors(themeName, themeMode);
  const scrollRef = useRef<HTMLDivElement>(null);

  const sidebarBg =
    themeMode === "light" ? "rgba(0, 0, 0, 0.02)" : "rgba(255, 255, 255, 0.03)";
  const activeItemBg = `${colors.primary}22`;
  const hoverItemBg =
    themeMode === "light" ? "rgba(0, 0, 0, 0.04)" : "rgba(255, 255, 255, 0.05)";

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  const loadConfig = useCallback(async () => {
    try {
      const res = await bridge.aiGetConfig();
      if (res?.ok && res.config) {
        setHasKey(!!res.config.has_api_key);
        setModelLabel(res.config.model || "");
        return res.config;
      }
    } catch {
      /* ignore */
    }
    return null;
  }, []);

  const loadConversation = useCallback(async (id: string) => {
    const res = await bridge.aiGetConversation(id);
    if (!res?.ok) {
      setStatusError(res?.error || "加载会话失败");
      return;
    }
    setActiveId(id);
    const msgs = (res.messages || []).map((m: any) => ({
      id: m.id || String(Math.random()),
      role: m.role === "assistant" ? "assistant" : "user",
      content: String(m.content || ""),
      timestamp: formatTs(m.timestamp),
    })) as ChatMsg[];
    setMessages(
      msgs.length
        ? msgs
        : [
            {
              id: "welcome",
              role: "assistant",
              content: WELCOME,
              timestamp: formatTs(),
            },
          ]
    );
    setStatusError("");
  }, []);

  const refreshList = useCallback(async () => {
    const res = await bridge.aiListConversations();
    if (!res?.ok) {
      setStatusError(res?.error || "加载会话列表失败");
      return [];
    }
    const list = (res.conversations || []) as ConversationItem[];
    setConversations(list);
    return list;
  }, []);

  const ensureConversation = useCallback(async () => {
    setBootstrapping(true);
    setStatusError("");
    try {
      await loadConfig();
      let list = await refreshList();
      if (!list.length) {
        const created = await bridge.aiCreateConversation("新对话");
        if (!created?.ok) {
          setStatusError(created?.error || "创建会话失败");
          return;
        }
        list = await refreshList();
      }
      const first = list[0];
      if (first?.id) {
        await loadConversation(first.id);
      }
    } catch (e: any) {
      setStatusError(String(e?.message || e || "初始化失败"));
    } finally {
      setBootstrapping(false);
    }
  }, [loadConfig, refreshList, loadConversation]);

  useEffect(() => {
    if (!isOpen) return;
    void ensureConversation();
  }, [isOpen, ensureConversation]);

  const handleNewChat = async () => {
    if (isLoading) return;
    const res = await bridge.aiCreateConversation("新对话");
    if (!res?.ok) {
      setStatusError(res?.error || "新建失败");
      return;
    }
    await refreshList();
    if (res.conversation?.id) {
      await loadConversation(res.conversation.id);
    }
  };

  const handleDeleteChat = async (id: string) => {
    if (isLoading) return;
    setMenuOpenId(null);
    const res = await bridge.aiDeleteConversation(id);
    if (!res?.ok) {
      setStatusError(res?.error || "删除失败");
      return;
    }
    const list = await refreshList();
    if (activeId === id) {
      if (list[0]?.id) {
        await loadConversation(list[0].id);
      } else {
        await handleNewChat();
      }
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading || !activeId) return;

    const content = inputValue.trim();
    setInputValue("");
    setIsLoading(true);
    setStatusError("");

    const optimistic: ChatMsg = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      timestamp: formatTs(),
    };
    setMessages((prev) => {
      const withoutWelcome = prev.filter((m) => m.id !== "welcome");
      return [...withoutWelcome, optimistic];
    });

    try {
      const res = await bridge.aiChat(activeId, content);
      if (!res?.ok) {
        setStatusError(res?.error || "对话失败");
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: "assistant",
            content: res?.error || "对话失败，请检查设置中的 API Key / Base URL。",
            timestamp: formatTs(),
          },
        ]);
        return;
      }
      const assistant = res.assistant_message;
      setMessages((prev) => {
        const withoutOptimistic = prev.filter((m) => m.id !== optimistic.id);
        const userSaved = res.user_message
          ? {
              id: res.user_message.id || optimistic.id,
              role: "user" as const,
              content: String(res.user_message.content || content),
              timestamp: formatTs(res.user_message.timestamp),
            }
          : optimistic;
        const asst: ChatMsg = {
          id: assistant?.id || `a-${Date.now()}`,
          role: "assistant",
          content: String(assistant?.content || ""),
          timestamp: formatTs(assistant?.timestamp),
        };
        return [...withoutOptimistic, userSaved, asst];
      });
      if (res.meta?.title) {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeId
              ? { ...c, title: res.meta.title, message_count: res.meta.message_count }
              : c
          )
        );
      }
      await refreshList();
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: String(err?.message || err || "请求失败"),
          timestamp: formatTs(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div
      style={{
        backgroundColor: colors.surface,
        borderColor: colors.border,
        color: colors.text,
      }}
      className="w-[40rem] max-w-[92vw] border-l h-full flex flex-col backdrop-blur-3xl z-40 relative shadow-2xl animate-in slide-in-from-right duration-300"
    >
      <div
        className="px-4 py-3 border-b flex items-center justify-between shrink-0"
        style={{ borderColor: colors.border }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex items-center gap-1.5 min-w-0">
            <img
              src={`${import.meta.env.BASE_URL}logo2.png`}
              alt="Nexuz"
              className="h-5 w-auto max-w-[5.5rem] object-contain select-none pointer-events-none"
              draggable={false}
            />
            <span className="font-display font-semibold text-base tracking-wide shrink-0">AI</span>
          </div>
          <p
            className="text-xs font-mono tracking-wider truncate ml-1"
            style={{ color: colors.secondaryText }}
            title={modelLabel || "未配置模型"}
          >
            {modelLabel || "未配置模型"}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setListOpen((v) => !v)}
            title={listOpen ? "收起对话列表" : "展开对话列表"}
            style={listOpen ? { color: colors.primary } : undefined}
          >
            {listOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => void handleNewChat()}
            title="新建对话"
          >
            <Plus className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
            <X className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {!hasKey ? (
        <div className="px-4 py-2 text-xs border-b border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
          尚未配置 API Key，请先在设置中填写后再对话。
          {onOpenSettings ? (
            <button
              type="button"
              className="ml-1 underline font-medium"
              onClick={onOpenSettings}
            >
              前往设置
            </button>
          ) : null}
        </div>
      ) : null}

      {statusError ? (
        <div className="px-4 py-2 text-xs border-b border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-300">
          {statusError}
        </div>
      ) : null}

      <div className="flex flex-1 min-h-0">
        {/* Conversation list — ChatGPT-like */}
        {listOpen ? (
        <aside
          className="w-[11.5rem] shrink-0 overflow-y-auto py-3 px-2"
          style={{
            backgroundColor: sidebarBg,
            borderRight: `1px solid ${colors.border}`,
          }}
        >
          {bootstrapping ? (
            <div
              className="px-3 py-2 text-xs flex items-center gap-1.5"
              style={{ color: colors.secondaryText }}
            >
              <Loader2 className="w-3 h-3 animate-spin" />
              加载中
            </div>
          ) : conversations.length === 0 ? (
            <p className="px-3 py-2 text-xs" style={{ color: colors.secondaryText }}>
              暂无对话
            </p>
          ) : (
            <div className="flex flex-col gap-0.5">
              {conversations.map((c) => {
                const active = activeId === c.id;
                const showMenu = active || menuOpenId === c.id;
                return (
                  <div
                    key={c.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => void loadConversation(c.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        void loadConversation(c.id);
                      }
                    }}
                    className="group relative flex items-center gap-1 rounded-xl px-3 py-2.5 cursor-pointer outline-none transition-colors"
                    style={{
                      backgroundColor: active ? activeItemBg : "transparent",
                      color: active ? colors.primary : colors.text,
                    }}
                    onMouseEnter={(e) => {
                      if (!active) e.currentTarget.style.backgroundColor = hoverItemBg;
                    }}
                    onMouseLeave={(e) => {
                      if (!active) e.currentTarget.style.backgroundColor = "transparent";
                    }}
                  >
                    <span className="flex-1 min-w-0 truncate text-[13px] leading-snug font-medium">
                      {c.title || "新对话"}
                    </span>

                    <DropdownMenu
                      open={menuOpenId === c.id}
                      onOpenChange={(open) => setMenuOpenId(open ? c.id : null)}
                    >
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          className={`shrink-0 h-6 w-6 inline-flex items-center justify-center rounded-md transition-opacity ${
                            showMenu
                              ? "opacity-70"
                              : "opacity-0 group-hover:opacity-70"
                          }`}
                          style={{ color: colors.secondaryText }}
                          onClick={(e) => e.stopPropagation()}
                          title="更多"
                          aria-label="更多"
                        >
                          <MoreHorizontal className="w-4 h-4" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-36" onClick={(e) => e.stopPropagation()}>
                        <DropdownMenuItem
                          className="text-red-600 dark:text-red-400 focus:text-red-600"
                          onClick={() => void handleDeleteChat(c.id)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                          删除对话
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                );
              })}
            </div>
          )}
        </aside>
        ) : null}

        <div className="flex-1 flex flex-col min-w-0">
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.map((msg) => {
              const isAi = msg.role === "assistant";
              return (
                <div
                  key={msg.id}
                  className={`flex items-start space-x-2.5 max-w-[92%] ${
                    !isAi ? "ml-auto flex-row-reverse space-x-reverse" : ""
                  }`}
                >
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden">
                    {isAi ? (
                      <img
                        src={`${import.meta.env.BASE_URL}logo.png`}
                        alt="Nexuz"
                        className="h-10 w-10 object-contain select-none pointer-events-none"
                        draggable={false}
                      />
                    ) : (
                      <User className="w-6 h-6" style={{ color: colors.secondaryText }} />
                    )}
                  </div>
                  <div className="space-y-1 min-w-0">
                    <div
                      style={{
                        backgroundColor: isAi
                          ? themeMode === "light"
                            ? "rgba(0, 0, 0, 0.03)"
                            : "rgba(255, 255, 255, 0.03)"
                          : colors.primary,
                        color: isAi ? colors.text : "#FFFFFF",
                        borderColor: colors.border,
                      }}
                      className={`p-3 rounded-2xl text-sm leading-relaxed border ${
                        isAi ? "rounded-tl-none" : "border-transparent rounded-tr-none"
                      }`}
                    >
                      <p className="whitespace-pre-wrap select-text break-words">{msg.content}</p>
                    </div>
                    <div
                      className={`text-[11px] font-mono px-1 ${!isAi ? "text-right" : ""}`}
                      style={{ color: colors.secondaryText }}
                    >
                      {msg.timestamp}
                    </div>
                  </div>
                </div>
              );
            })}

            {isLoading && (
              <div className="flex items-start space-x-2.5">
                <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden">
                  <img
                    src={`${import.meta.env.BASE_URL}logo.png`}
                    alt="Nexuz"
                    className="h-10 w-10 object-contain select-none pointer-events-none"
                    draggable={false}
                  />
                </div>
                <div
                  className="p-3 rounded-2xl rounded-tl-none border flex items-center space-x-2 text-sm"
                  style={{
                    borderColor: colors.border,
                    backgroundColor:
                      themeMode === "light" ? "rgba(0,0,0,0.03)" : "rgba(255,255,255,0.03)",
                    color: colors.secondaryText,
                  }}
                >
                  <Loader2 className="w-3.5 h-3.5 animate-spin" style={{ color: colors.primary }} />
                  <span className="italic">思考中…</span>
                </div>
              </div>
            )}
          </div>

          <form
            onSubmit={handleSend}
            className="p-4 border-t shrink-0"
            style={{ borderColor: colors.border }}
          >
            <div className="relative flex items-center gap-2">
              <Input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="输入消息…"
                className="pr-11 h-11 rounded-2xl text-sm"
                disabled={isLoading || !activeId}
              />
              <Button
                type="submit"
                size="icon"
                disabled={!inputValue.trim() || isLoading || !activeId}
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
      </div>
    </div>
  );
}
