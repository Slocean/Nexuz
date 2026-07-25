# Flow AI × LangChain / LangGraph

更新日期：2026-07-25  
状态：已接入（Python 侧）— **分步编排主路径**

本文说明 Nexuz 如何用 **LangChain + LangGraph** 做编排，以及和旧自研 tool loop 的概念映射。

---

## 1. 分层

| 层 | 路径 | 作用 |
| -- | ---- | ---- |
| Bridge 门面 | `backend/core/ai/session_manager.py` | 对接 `api.ai_*`，会话/草稿/`agent_state` 持久化 |
| LangGraph | `backend/core/ai/graphs/` | 多阶段状态图（chat / flow） |
| LangChain | `backend/core/ai/lc/` | `ChatOpenAI`、Prompt、Tools、结构化输出 |
| 领域 | `draft_builder` / `locate` / `tool_runtime` / `outline_build` | 改草稿、截图 OCR/Vision、坐标门禁、大纲展开 |
| Checkpoint | `backend/core/ai/checkpointer.py` | SqliteSaver → `{data_dir}/ai/checkpoints.db` |

前端仍走 pywebview Bridge，**不引入 JS 侧 LangChain**。

---

## 2. 概念映射（旧 → 新）

| 旧 SessionManager / 宏路径 | 新实现 |
| -------------------------- | ------ |
| 手写 `httpx` + `/chat/completions` | `lc/models.py` → `ChatOpenAI` |
| `planner(FlowSpec) → apply_flow_spec` 一次宏展开 | `understand → outline → gap → build_loop(tools)` |
| 配方/技能当主路径 | 可选工具 `call_skill`（内部仍可走 recipes） |
| `strict_coords=False` | 默认 `True`（裸坐标拒绝） |
| 校验只在 apply | `validate` + 有界 `repair` |
| 无图状态 | Sqlite checkpoint + 会话 `agent_state`（澄清续跑） |

---

## 3. Flow 图节点（主路径）

```
load_context → understand → clarify? → plan_outline → gap_check ↔ outline
           → build_loop → validate ↔ repair → summarize
```

1. **load_context**：草稿摘要 / points / 积木卡 / 可选技能列表  
2. **understand**：`IntentUnderstanding`（intent、known_slots、真 ambiguities）  
3. **clarify**：有歧义且未答 → `needs_clarify` 中断；用户作答后同会话 `resume_clarify` 续跑  
4. **plan_outline**：有序 `steps[]`（goal / block_hint / needs_sense），**不是**完整 Flow JSON  
5. **gap_check**：查漏补缺；缺则有界回 `plan_outline`（最多 2 次）  
6. **build_loop**：优先 **JSON `ToolActionBatch` 动作协议**落图（不依赖 chat-template tools）；无产出时再试原生 `bind_tools`；再失败才 `outline_build`。理解/大纲等结构化调用走 `lc/structured_call.invoke_structured`（`json_mode` 优先 + 触顶压缩重试）
7. **validate / repair**：入口与坐标门禁；repair 用工具最小修补，最多 2 轮  
8. **summarize**：仅陈述事实；`node_count==0` 禁止「已准备好」

人机确认：图结束后仍由用户点「应用到画布」→ `ai_apply_draft`。

### 感知策略（写死在 build 规则）

- 有明确文字目标 → `ocr_recognize` → click 绑定 `{{id.x/y}}`
- 无字/图标且支持 vision → `capture_screen` → `locate_on_screenshot_vision` → `bind_point_to_node`
- 禁止裸坐标（`strict_coords=True`）

---

## 4. 如何跑通

1. 设置页启用 AI，填 OpenAI 兼容 Base URL / API Key / Model  
2. 「测试连接」走 `test_chat_model`  
3. 对话模式 → `run_chat_graph`  
4. 编排模式 → `run_flow_graph`  

依赖见 `requirements.in`：`langchain-core`、`langchain-openai`、`langgraph`、`langgraph-checkpoint-sqlite`。

---

## 5. 技能 / 配方（可选）

技能包仍在 `backend/core/ai/skills/packs/`；主路径不再自动 `planner → apply_flow_spec`。  
模型可在 `build_loop` 中调用 `call_skill`；评测与 offline 仍可用 `heuristic_plan_from_text` + `apply_flow_spec`。

---

## 6. 学习对照清单

| 想学的概念 | 看哪里 |
| ---------- | ------ |
| StateGraph / 条件边 | `graphs/flow_graph.py` |
| Structured output | `lc/structured.py` + understand/outline 节点 |
| Tools / bind_tools | `lc/tools.py` + `build_loop` |
| Checkpoint thread | `checkpointer.py` + `session_manager` `agent_state` |
| 坐标门禁 | `tool_runtime.py` `strict_coords` |
