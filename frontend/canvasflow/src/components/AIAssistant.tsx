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
  Camera,
  Check,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Wrench,
  Brain,
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
import PointConfirmPanel, {
  AiPointPreview,
  AiShotPreview,
} from "./PointConfirmPanel";

interface ProcessStep {
  kind: "think" | "tool" | string;
  label?: string;
  text?: string;
  name?: string;
  ok?: boolean;
  detail?: string;
  summary?: string;
  elapsed_ms?: number;
}

interface OrchestrationCard {
  summary?: DraftSummary;
  diff?: DraftDiff;
  warnings?: string[];
  tool_trace?: { name?: string; ok?: boolean }[];
  points?: AiPointPreview[];
  shot?: AiShotPreview | null;
  status?: string;
  has_result?: boolean;
  result_id?: string;
}

interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  process?: ProcessStep[];
  orchestration?: OrchestrationCard | null;
  streaming?: boolean;
}

interface ConversationItem {
  id: string;
  title: string;
  updated_at?: string;
  message_count?: number;
  model?: string;
  kind?: "chat" | "flow" | string;
}

interface DraftDiff {
  added?: { id: string; type?: string }[];
  removed?: { id: string; type?: string }[];
  changed?: { id: string; type?: string }[];
  entry_changed?: boolean;
}

interface DraftSummary {
  node_count?: number;
  entry?: string | null;
  nodes?: { id: string; type?: string; unverified_coords?: boolean }[];
}

interface AIAssistantProps {
  isOpen: boolean;
  onClose: () => void;
  themeName: ThemeName;
  themeMode: ThemeMode;
  onOpenSettings?: () => void;
  /** Current canvas flow — seeded as base_flow for incremental edits */
  currentFlow?: Record<string, unknown> | null;
  /** Apply canonical flow from ai_apply_draft */
  onApplyFlow?: (flow: Record<string, unknown>, warnings?: string[]) => void;
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

const WELCOME_CHAT =
  "你好！我是 Nexuz Flow AI（对话模式）。可以问积木、取点、流程设计等问题。需要自动生成流程时，请切换到「编排」。";

const WELCOME_FLOW =
  "你好！我是 Nexuz Flow AI（编排模式）。用自然语言描述自动化意图，我会编排积木草稿并在需要时截图 OCR 取点。确认后即可应用到画布。";

const MODE_STORAGE_KEY = "nexuz.ai.mode";

function loadAiMode(): "chat" | "flow" {
  try {
    const v = localStorage.getItem(MODE_STORAGE_KEY);
    if (v === "chat" || v === "flow") return v;
  } catch {
    /* ignore */
  }
  return "chat";
}

function saveAiMode(mode: "chat" | "flow") {
  try {
    localStorage.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    /* ignore */
  }
}

function OrchestrationResultCard({
  card,
  colors,
  themeMode,
  applying,
  onApply,
  onDiscard,
  canApply,
  showDiscard,
}: {
  card: OrchestrationCard;
  colors: ReturnType<typeof getThemeColors>;
  themeMode: ThemeMode;
  applying: boolean;
  onApply: () => void;
  onDiscard: () => void;
  canApply: boolean;
  showDiscard: boolean;
}) {
  const summary = card.summary;
  const diff = card.diff;
  const nodeCount = summary?.node_count || 0;
  const addedCount = diff?.added?.length || 0;
  const warnings = card.warnings || [];
  const toolTrace = card.tool_trace || [];
  const mutedBg =
    themeMode === "light" ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.05)";

  return (
    <div
      className="mt-2 rounded-xl border p-2.5 space-y-1.5"
      style={{ borderColor: colors.border, backgroundColor: mutedBg }}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs" style={{ color: colors.secondaryText }}>
          草稿 {nodeCount} 节点
          {addedCount ? ` · +${addedCount}` : ""}
          {diff?.removed?.length ? ` · -${diff.removed.length}` : ""}
        </p>
        <div className="flex items-center gap-1">
          {showDiscard ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 text-xs px-2"
              onClick={onDiscard}
              disabled={applying}
              title="丢弃当前会话草稿"
            >
              <RotateCcw className="w-3 h-3 mr-1" />
              丢弃
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            className="h-7 text-xs px-2.5"
            style={{ backgroundColor: colors.primary }}
            onClick={onApply}
            disabled={applying || !canApply}
          >
            {applying ? (
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
            ) : (
              <Check className="w-3 h-3 mr-1" />
            )}
            应用到画布
          </Button>
        </div>
      </div>
      {summary?.nodes?.some((n) => n.unverified_coords) || warnings.length ? (
        <p className="text-[11px] text-amber-600 dark:text-amber-300">
          {warnings[0] || "部分节点含未经验证取点的坐标"}
        </p>
      ) : null}
      {toolTrace.length > 0 ? (
        <p className="text-[11px] font-mono break-all" style={{ color: colors.secondaryText }}>
          tools:{" "}
          {toolTrace
            .slice(-10)
            .map((t) => `${t.name}${t.ok === false ? "✗" : "✓"}`)
            .join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

function ProcessTimeline({
  steps,
  themeMode,
  colors,
  defaultOpen = true,
  streaming = false,
}: {
  steps: ProcessStep[];
  themeMode: ThemeMode;
  colors: ReturnType<typeof getThemeColors>;
  defaultOpen?: boolean;
  streaming?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [elapsedSec, setElapsedSec] = useState<number | null>(null);
  const startedAtRef = useRef<number>(Date.now());
  const sawStreamingRef = useRef(streaming);

  useEffect(() => {
    if (streaming) {
      sawStreamingRef.current = true;
      startedAtRef.current = Date.now();
      setElapsedSec(null);
      setOpen(true);
      return;
    }
    if (sawStreamingRef.current) {
      setElapsedSec((prev) =>
        prev != null
          ? prev
          : Math.max(1, Math.round((Date.now() - startedAtRef.current) / 1000))
      );
      setOpen(false);
    }
  }, [streaming]);

  if (!steps.length) return null;

  const thinkMuted =
    themeMode === "light" ? "rgba(0,0,0,0.45)" : "rgba(255,255,255,0.45)";
  const thinkMutedSoft =
    themeMode === "light" ? "rgba(0,0,0,0.38)" : "rgba(255,255,255,0.38)";
  const spine =
    themeMode === "light" ? "rgba(0,0,0,0.12)" : "rgba(255,255,255,0.14)";

  const headerLabel = streaming
    ? "正在思考"
    : elapsedSec != null
      ? `已思考（用时 ${elapsedSec} 秒）`
      : "已思考";

  return (
    <div className="mb-2.5">
      <button
        type="button"
        className="inline-flex items-center gap-1 text-[12px] leading-none select-none"
        style={{ color: thinkMuted }}
        onClick={() => setOpen((v) => !v)}
      >
        <Brain className="w-3.5 h-3.5 shrink-0" style={{ color: colors.primary }} />
        <span>{headerLabel}</span>
        {open ? (
          <ChevronDown className="w-3 h-3 shrink-0 opacity-80" />
        ) : (
          <ChevronRight className="w-3 h-3 shrink-0 opacity-80" />
        )}
      </button>

      {open ? (
        <div className="relative mt-2 pl-3.5">
          <div
            className="absolute left-[6px] top-1 bottom-1 w-px"
            style={{ backgroundColor: spine }}
            aria-hidden
          />
          <div className="space-y-2.5">
            {steps.map((step, idx) => {
              const isThink = step.kind === "think";
              const isLast = idx === steps.length - 1;
              return (
                <div key={`${step.kind}-${idx}`} className="relative pl-2.5">
                  <span
                    className="absolute -left-[9px] top-1.5 h-1.5 w-1.5 rounded-full"
                    style={{
                      backgroundColor:
                        streaming && isLast ? colors.primary : spine,
                      boxShadow:
                        streaming && isLast
                          ? `0 0 6px ${colors.primary}`
                          : undefined,
                    }}
                    aria-hidden
                  />
                  <div className="flex items-start gap-1.5 min-w-0">
                    {isThink ? (
                      <Brain
                        className="w-3 h-3 mt-0.5 shrink-0 opacity-80"
                        style={{ color: thinkMuted }}
                      />
                    ) : (
                      <Wrench
                        className="w-3 h-3 mt-0.5 shrink-0"
                        style={{
                          color: step.ok === false ? "#ef4444" : thinkMuted,
                        }}
                      />
                    )}
                    <div
                      className="min-w-0 flex-1 text-[12px] leading-relaxed"
                      style={{ color: thinkMutedSoft }}
                    >
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span>
                          {step.label || (isThink ? "思考" : step.name || "工具")}
                        </span>
                        {!isThink ? (
                          <span className="font-mono text-[10px] opacity-80">
                            {step.ok === false ? "失败" : "成功"}
                            {step.elapsed_ms != null
                              ? ` · ${step.elapsed_ms}ms`
                              : ""}
                          </span>
                        ) : null}
                      </div>
                      {isThink && step.text ? (
                        <p className="mt-0.5 whitespace-pre-wrap break-words opacity-90">
                          {step.text}
                        </p>
                      ) : null}
                      {!isThink ? (
                        <div className="mt-0.5 space-y-0.5 opacity-90">
                          {step.detail ? (
                            <p className="font-mono text-[11px] break-all">
                              {step.detail}
                            </p>
                          ) : null}
                          {step.summary ? (
                            <p className="break-words">{step.summary}</p>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function AIAssistant({
  isOpen,
  onClose,
  themeName,
  themeMode,
  onOpenSettings,
  currentFlow,
  onApplyFlow,
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
  const [attachShot, setAttachShot] = useState(false);
  const [draftSummary, setDraftSummary] = useState<DraftSummary | null>(null);
  const [draftDiff, setDraftDiff] = useState<DraftDiff | null>(null);
  const [points, setPoints] = useState<AiPointPreview[]>([]);
  const [shot, setShot] = useState<AiShotPreview | null>(null);
  const [toolTrace, setToolTrace] = useState<{ name?: string; ok?: boolean }[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [applying, setApplying] = useState(false);
  const [applyingMsgId, setApplyingMsgId] = useState<string | null>(null);
  const [aiMode, setAiMode] = useState<"chat" | "flow">(loadAiMode);

  const colors = getThemeColors(themeName, themeMode);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isFlowMode = aiMode === "flow";
  const welcomeText = isFlowMode ? WELCOME_FLOW : WELCOME_CHAT;
  const convKind = isFlowMode ? "flow" : "chat";

  const switchMode = useCallback((next: "chat" | "flow") => {
    setAiMode(next);
    saveAiMode(next);
    setAttachShot(false);
    setStatusError("");
    setActiveId(null);
    setMessages([
      {
        id: "welcome",
        role: "assistant",
        content: next === "flow" ? WELCOME_FLOW : WELCOME_CHAT,
        timestamp: formatTs(),
      },
    ]);
    setDraftSummary(null);
    setDraftDiff(null);
    setPoints([]);
    setShot(null);
    setToolTrace([]);
    setWarnings([]);
  }, []);

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

  const applyDraftState = useCallback((res: Record<string, any> | null | undefined) => {
    if (!res) return;
    if (res.draft_summary) setDraftSummary(res.draft_summary);
    if (res.summary && !res.draft_summary) setDraftSummary(res.summary);
    if (res.diff) setDraftDiff(res.diff);
    if (Array.isArray(res.points)) setPoints(res.points);
    if (res.shot) setShot(res.shot);
    if (Array.isArray(res.tool_trace)) setToolTrace(res.tool_trace);
    if (Array.isArray(res.warnings)) setWarnings(res.warnings);
  }, []);

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

  const loadConversation = useCallback(
    async (id: string) => {
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
        process: Array.isArray(m.process) ? m.process : undefined,
        orchestration: m.orchestration && typeof m.orchestration === "object" ? m.orchestration : undefined,
      })) as ChatMsg[];
      setMessages(
        msgs.length
          ? msgs
          : [
              {
                id: "welcome",
                role: "assistant",
                content: welcomeText,
                timestamp: formatTs(),
              },
            ]
      );
      setStatusError("");
      if (isFlowMode) {
        const draftRes = await bridge.aiGetDraft(id);
        if (draftRes?.ok) {
          applyDraftState(draftRes);
        } else {
          setDraftSummary(null);
          setDraftDiff(null);
          setPoints([]);
          setShot(null);
          setToolTrace([]);
          setWarnings([]);
        }
      }
    },
    [applyDraftState, isFlowMode, welcomeText]
  );

  const refreshList = useCallback(async () => {
    const res = await bridge.aiListConversations(convKind);
    if (!res?.ok) {
      setStatusError(res?.error || "加载会话列表失败");
      return [];
    }
    const list = (res.conversations || []) as ConversationItem[];
    setConversations(list);
    return list;
  }, [convKind]);

  const ensureConversation = useCallback(async () => {
    setBootstrapping(true);
    setStatusError("");
    try {
      await loadConfig();
      let list = await refreshList();
      if (!list.length) {
        const created = await bridge.aiCreateConversation(
          isFlowMode ? "新编排" : "新对话",
          convKind
        );
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
  }, [loadConfig, refreshList, loadConversation, isFlowMode, convKind]);

  useEffect(() => {
    if (!isOpen) return;
    void ensureConversation();
  }, [isOpen, ensureConversation, aiMode]);

  // Live stream / process via drain_ui_events → nexuz-ai-progress
  useEffect(() => {
    if (!isOpen) return;
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent).detail || {};
      const cid = detail.conversation_id;
      if (activeId && cid && cid !== activeId) return;
      const aid = detail.assistant_id as string | undefined;
      const typ = detail.type as string;

      if (typ === "start" && aid) {
        setMessages((prev) => {
          if (prev.some((m) => m.id === aid)) return prev;
          const pendingIdx = [...prev]
            .map((m, i) => ({ m, i }))
            .reverse()
            .find(({ m }) => m.streaming && String(m.id).startsWith("pending-"))?.i;
          if (pendingIdx != null) {
            return prev.map((m, i) =>
              i === pendingIdx
                ? {
                    ...m,
                    id: aid,
                    process: m.process || [],
                    streaming: true,
                  }
                : m
            );
          }
          return [
            ...prev.filter((m) => m.id !== "welcome"),
            {
              id: aid,
              role: "assistant",
              content: "",
              timestamp: formatTs(),
              process: [],
              streaming: true,
            },
          ];
        });
        return;
      }

      if (typ === "delta" && aid) {
        const piece = String(detail.text || "");
        const replace = !!detail.replace;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aid
              ? {
                  ...m,
                  content: replace ? piece : (m.content || "") + piece,
                  streaming: true,
                }
              : m
          )
        );
        return;
      }

      if (typ === "reasoning" && aid) {
        const piece = String(detail.text || "");
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== aid) return m;
            const proc = [...(m.process || [])];
            const last = proc[proc.length - 1];
            if (last?.kind === "think" && last.label === "思考") {
              proc[proc.length - 1] = { ...last, text: (last.text || "") + piece };
            } else {
              proc.push({ kind: "think", label: "思考", text: piece });
            }
            return { ...m, process: proc, streaming: true };
          })
        );
        return;
      }

      if (typ === "process" && aid) {
        const steps = Array.isArray(detail.process) ? detail.process : null;
        const step = detail.step;
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== aid) return m;
            if (steps) return { ...m, process: steps, streaming: true };
            if (step) return { ...m, process: [...(m.process || []), step], streaming: true };
            return m;
          })
        );
        return;
      }

      if (typ === "draft") {
        if (detail.draft_summary) setDraftSummary(detail.draft_summary);
        if (detail.diff) setDraftDiff(detail.diff);
        return;
      }

      if (typ === "done" && aid) {
        const am = detail.assistant_message;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === aid
              ? {
                  ...m,
                  content: String(am?.content ?? m.content ?? ""),
                  process: Array.isArray(am?.process) ? am.process : m.process,
                  orchestration: am?.orchestration || detail.orchestration || m.orchestration,
                  streaming: false,
                }
              : m
          )
        );
        if (detail.orchestration) {
          applyDraftState({
            draft_summary: detail.orchestration.summary,
            diff: detail.orchestration.diff,
            points: detail.orchestration.points,
            shot: detail.orchestration.shot,
            tool_trace: detail.orchestration.tool_trace,
            warnings: detail.orchestration.warnings,
          });
        }
        return;
      }

      if (typ === "error") {
        const errText = String(detail.error || "对话失败");
        setStatusError(errText);
        setMessages((prev) => {
          let replaced = false;
          const next = prev.map((m) => {
            if (replaced) return m;
            const isTarget =
              (aid && m.id === aid) ||
              m.streaming ||
              String(m.id).startsWith("pending-");
            if (!isTarget || m.role !== "assistant") return m;
            replaced = true;
            return {
              ...m,
              content: errText,
              streaming: false,
              process: m.process?.length ? m.process : undefined,
            };
          });
          return replaced
            ? next
            : [
                ...next,
                {
                  id: `err-${Date.now()}`,
                  role: "assistant" as const,
                  content: errText,
                  timestamp: formatTs(),
                },
              ];
        });
      }
    };
    window.addEventListener("nexuz-ai-progress", handler as EventListener);
    return () => window.removeEventListener("nexuz-ai-progress", handler as EventListener);
  }, [isOpen, activeId, applyDraftState]);

  // Refresh welcome bubble when mode changes and chat is empty / only welcome
  useEffect(() => {
    setMessages((prev) => {
      if (prev.length === 1 && prev[0]?.id === "welcome") {
        return [{ ...prev[0], content: welcomeText }];
      }
      if (prev.length === 0) {
        return [
          {
            id: "welcome",
            role: "assistant",
            content: welcomeText,
            timestamp: formatTs(),
          },
        ];
      }
      return prev;
    });
  }, [aiMode, welcomeText]);

  const handleNewChat = async () => {
    if (isLoading) return;
    const res = await bridge.aiCreateConversation(
      isFlowMode ? "新编排" : "新对话",
      convKind
    );
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
    if ((!inputValue.trim() && !(isFlowMode && attachShot)) || isLoading || !activeId) return;

    const content = inputValue.trim() || (attachShot && isFlowMode ? "请根据截图帮忙编排/取点" : "");
    setInputValue("");
    setIsLoading(true);
    setStatusError("");

    const optimistic: ChatMsg = {
      id: `local-${Date.now()}`,
      role: "user",
      content: attachShot && isFlowMode ? `${content}\n（附带屏幕截图）` : content,
      timestamp: formatTs(),
    };
    // Placeholder assistant bubble so UI never shows a second "编排中" row.
    const pendingAid = `pending-${Date.now()}`;
    setMessages((prev) => {
      const withoutWelcome = prev.filter((m) => m.id !== "welcome");
      return [
        ...withoutWelcome,
        optimistic,
        {
          id: pendingAid,
          role: "assistant",
          content: "",
          timestamp: formatTs(),
          process: [],
          streaming: true,
        },
      ];
    });

    const useShot = isFlowMode && attachShot;
    setAttachShot(false);

    try {
      const res = await bridge.aiChat(
        activeId,
        content,
        isFlowMode ? currentFlow || null : null,
        useShot,
        aiMode
      );
      if (!res?.ok) {
        const errText = res?.error || "对话失败，请检查设置中的 API Key / Base URL。";
        setStatusError(errText);
        setMessages((prev) => {
          let target = -1;
          for (let i = prev.length - 1; i >= 0; i--) {
            const m = prev[i];
            if (m.role !== "assistant") continue;
            if (
              m.id === pendingAid ||
              m.streaming ||
              String(m.id).startsWith("pending-") ||
              m.content === errText
            ) {
              target = i;
              break;
            }
          }
          if (target < 0) {
            for (let i = prev.length - 1; i >= 0; i--) {
              if (prev[i].role === "assistant") {
                target = i;
                break;
              }
            }
          }
          if (target >= 0) {
            return prev
              .map((m, i) =>
                i === target ? { ...m, content: errText, streaming: false } : m
              )
              .filter(
                (m, i) => i === target || !String(m.id).startsWith("pending-")
              );
          }
          return [
            ...prev.filter((m) => !String(m.id).startsWith("pending-")),
            {
              id: `err-${Date.now()}`,
              role: "assistant" as const,
              content: errText,
              timestamp: formatTs(),
            },
          ];
        });
        return;
      }
      const assistant = res.assistant_message;
      setMessages((prev) => {
        const aid = assistant?.id;
        const userSaved: ChatMsg = res.user_message
          ? {
              id: res.user_message.id || optimistic.id,
              role: "user",
              content: String(res.user_message.content || content),
              timestamp: formatTs(res.user_message.timestamp),
            }
          : optimistic;
        const asst: ChatMsg = {
          id: aid || `a-${Date.now()}`,
          role: "assistant",
          content: String(assistant?.content || ""),
          timestamp: formatTs(assistant?.timestamp),
          process: Array.isArray(assistant?.process)
            ? assistant.process
            : Array.isArray(res.process)
              ? res.process
              : undefined,
          orchestration:
            assistant?.orchestration ||
            res.orchestration ||
            (isFlowMode
              ? {
                  summary: res.draft_summary,
                  diff: res.diff,
                  warnings: res.warnings,
                  tool_trace: res.tool_trace,
                  points: res.points,
                  shot: res.shot,
                  status: res.status,
                  has_result: true,
                  result_id: aid,
                }
              : undefined),
          streaming: false,
        };
        const cleaned = prev.filter(
          (m) => m.id !== optimistic.id && m.id !== pendingAid && m.id !== aid
        );
        const hasStreamed = aid ? prev.some((m) => m.id === aid) : false;
        if (hasStreamed) {
          return prev
            .filter((m) => m.id !== pendingAid)
            .map((m) => {
              if (m.id === optimistic.id) return userSaved;
              if (m.id === aid) return { ...m, ...asst };
              return m;
            });
        }
        return [...cleaned, userSaved, asst];
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
      if (isFlowMode) {
        applyDraftState(res);
      }
      await refreshList();
    } catch (err: any) {
      const errText = String(err?.message || err || "请求失败");
      setStatusError(errText);
      setMessages((prev) => {
        let target = -1;
        for (let i = prev.length - 1; i >= 0; i--) {
          const m = prev[i];
          if (m.role !== "assistant") continue;
          if (
            m.id === pendingAid ||
            m.streaming ||
            String(m.id).startsWith("pending-") ||
            m.content === errText
          ) {
            target = i;
            break;
          }
        }
        if (target < 0) {
          for (let i = prev.length - 1; i >= 0; i--) {
            if (prev[i].role === "assistant") {
              target = i;
              break;
            }
          }
        }
        if (target >= 0) {
          return prev
            .map((m, i) =>
              i === target ? { ...m, content: errText, streaming: false } : m
            )
            .filter((m, i) => i === target || !String(m.id).startsWith("pending-"));
        }
        return [
          ...prev.filter((m) => !String(m.id).startsWith("pending-")),
          {
            id: `err-${Date.now()}`,
            role: "assistant" as const,
            content: errText,
            timestamp: formatTs(),
          },
        ];
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleApply = async (messageId?: string) => {
    if (!activeId || applying) return;
    const mid = (messageId || "").trim();
    setApplying(true);
    setApplyingMsgId(mid || "__latest__");
    setStatusError("");
    try {
      const res = await bridge.aiApplyDraft(activeId, mid);
      if (!res?.ok) {
        setStatusError(res?.error || "应用草稿失败");
        return;
      }
      if (res.flow && onApplyFlow) {
        onApplyFlow(res.flow, res.warnings || []);
      }
      setWarnings(Array.isArray(res.warnings) ? res.warnings : []);
    } catch (e: any) {
      setStatusError(String(e?.message || e || "应用失败"));
    } finally {
      setApplying(false);
      setApplyingMsgId(null);
    }
  };

  const handleCancelDraft = async () => {
    if (!activeId || applying) return;
    const res = await bridge.aiCancelDraft(activeId);
    if (!res?.ok) {
      setStatusError(res?.error || "取消失败");
      return;
    }
    setDraftSummary(res.summary || { node_count: 0, nodes: [] });
    setDraftDiff({ added: [], removed: [], changed: [] });
    setPoints([]);
    setShot(null);
    setToolTrace([]);
    setWarnings([]);
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
          <div
            className="flex items-center rounded-lg p-0.5 shrink-0 ml-1"
            style={{
              backgroundColor:
                themeMode === "light" ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.06)",
            }}
          >
            <button
              type="button"
              className="px-2 py-1 rounded-md text-[11px] font-medium transition-colors"
              style={{
                backgroundColor: !isFlowMode ? colors.primary : "transparent",
                color: !isFlowMode ? "#fff" : colors.secondaryText,
              }}
              onClick={() => switchMode("chat")}
              disabled={isLoading}
            >
              对话
            </button>
            <button
              type="button"
              className="px-2 py-1 rounded-md text-[11px] font-medium transition-colors"
              style={{
                backgroundColor: isFlowMode ? colors.primary : "transparent",
                color: isFlowMode ? "#fff" : colors.secondaryText,
              }}
              onClick={() => switchMode("flow")}
              disabled={isLoading}
            >
              编排
            </button>
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

      {isFlowMode && activeId && (shot || points.length > 0) ? (
        <PointConfirmPanel
          conversationId={activeId}
          shot={shot}
          points={points}
          themeName={themeName}
          themeMode={themeMode}
          onPointsChange={setPoints}
        />
      ) : null}

      <div className="flex flex-1 min-h-0">
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
                        <DropdownMenuContent
                          align="end"
                          className="w-36"
                          onClick={(e) => e.stopPropagation()}
                        >
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
                      {isAi && msg.process && msg.process.length > 0 ? (
                        <ProcessTimeline
                          steps={msg.process}
                          themeMode={themeMode}
                          colors={colors}
                          defaultOpen={!!msg.streaming}
                          streaming={!!msg.streaming}
                        />
                      ) : null}
                      <p className="whitespace-pre-wrap select-text break-words">
                        {msg.content}
                        {msg.streaming && !msg.content && !(msg.process && msg.process.length) ? (
                          <span
                            className="inline-flex items-center gap-1.5 italic"
                            style={{ color: colors.secondaryText }}
                          >
                            <Loader2
                              className="w-3.5 h-3.5 animate-spin inline"
                              style={{ color: colors.primary }}
                            />
                            {isFlowMode ? "编排中…" : "思考中…"}
                          </span>
                        ) : null}
                        {msg.streaming && msg.content ? (
                          <span
                            className="inline-block w-1.5 h-3.5 ml-0.5 align-middle animate-pulse rounded-sm"
                            style={{ backgroundColor: colors.primary }}
                          />
                        ) : null}
                      </p>
                      {isAi && msg.orchestration ? (
                        <OrchestrationResultCard
                          card={msg.orchestration}
                          colors={colors}
                          themeMode={themeMode}
                          applying={
                            applying &&
                            applyingMsgId ===
                              (msg.orchestration.result_id || msg.id)
                          }
                          canApply={!!onApplyFlow}
                          showDiscard={
                            !!msg.orchestration.result_id &&
                            messages.filter((m) => m.orchestration).at(-1)?.id ===
                              msg.id
                          }
                          onApply={() =>
                            void handleApply(
                              msg.orchestration?.result_id || msg.id
                            )
                          }
                          onDiscard={() => void handleCancelDraft()}
                        />
                      ) : null}
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

            {isLoading && !messages.some((m) => m.streaming) ? (
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
                  <span className="italic">{isFlowMode ? "编排中…" : "思考中…"}</span>
                </div>
              </div>
            ) : null}
          </div>

          <form
            onSubmit={handleSend}
            className="p-4 border-t shrink-0"
            style={{ borderColor: colors.border }}
          >
            <div className="relative flex items-center gap-2">
              {isFlowMode ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  title={attachShot ? "将附带截图" : "附带屏幕截图"}
                  style={attachShot ? { color: colors.primary } : { color: colors.secondaryText }}
                  onClick={() => setAttachShot((v) => !v)}
                  disabled={isLoading || !activeId}
                >
                  <Camera className="w-4 h-4" />
                </Button>
              ) : null}
              <Input
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder={
                  isFlowMode
                    ? attachShot
                      ? "描述意图（将附带截图）…"
                      : "描述自动化意图…"
                    : "输入消息…"
                }
                className="pr-11 h-11 rounded-2xl text-sm"
                disabled={isLoading || !activeId}
              />
              <Button
                type="submit"
                size="icon"
                disabled={
                  (!inputValue.trim() && !(isFlowMode && attachShot)) ||
                  isLoading ||
                  !activeId
                }
                className="absolute right-1.5 h-8 w-8"
                style={{
                  backgroundColor:
                    (inputValue.trim() || (isFlowMode && attachShot)) && !isLoading
                      ? colors.primary
                      : undefined,
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
