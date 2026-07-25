# Flow AI × LangChain / LangGraph

更新日期：2026-07-25  
状态：已接入（Python 侧）

本文说明 Nexuz 如何用 **LangChain + LangGraph** 做编排，以及和旧自研 tool loop 的概念映射，便于对照官方文档学习。

---

## 1. 分层

| 层 | 路径 | 作用 |
| -- | ---- | ---- |
| Bridge 门面 | `backend/core/ai/session_manager.py` | 对接 `api.ai_*`，会话/草稿持久化不变 |
| LangGraph | `backend/core/ai/graphs/` | 多阶段状态图（chat / flow） |
| LangChain | `backend/core/ai/lc/` | `ChatOpenAI`、Prompt、Tools、`FlowSpec` 结构化输出 |
| 领域 | `draft_builder` / `locate` / `tool_runtime` | 真正改草稿、截图 OCR、坐标门禁 |
| Checkpoint | `backend/core/ai/checkpointer.py` | SqliteSaver → `{data_dir}/ai/checkpoints.db` |

前端仍走 pywebview Bridge，**不引入 JS 侧 LangChain**。

---

## 2. 概念映射（旧 → 新）

| 旧 SessionManager | 新实现 |
| ----------------- | ------ |
| 手写 `httpx` + `/chat/completions` | `lc/models.py` → `ChatOpenAI`（OpenAI 兼容网关） |
| `while steps < 12` tool loop | `graphs/flow_graph.py` StateGraph |
| system prompt 字符串 | `lc/prompts.py` + 节点内 `SystemMessage` |
| 模型自由调 `list_blocks` | `load_context` 注入草稿 + 高频积木；`planner` 出 `FlowSpec` |
| `draft_add_node` 细粒度拼图 | `graphs/recipes.py` 配方优先落图 |
| `strict_coords=False` | 默认 `True`（裸坐标拒绝） |
| 校验只在 apply | `validate` 节点 + `repair` 有界回修 |
| 无图状态 | Sqlite checkpoint，`thread_id=conversation_id` |

---

## 3. Flow 图节点

```
load_context → planner → builder → (locator?) → validate → (repair → builder)* → summarize
```

1. **load_context**：注入草稿摘要 / points / 高频积木说明  
2. **planner**：`with_structured_output(FlowSpec)`，`temperature≈0.2`  
3. **builder**：`apply_flow_spec` 确定性配方落图  
4. **locator**：需要时截图 + OCR（`needs_locate` / `locate_texts`）  
5. **validate**：入口检查 + 可选 `validate_fn`（Bridge 注入 `_validate_flow`）  
6. **repair**：把错误喂回模型修 FlowSpec，最多 2 轮  
7. **summarize**：流式中文总结 → 现有 `ai_progress`  

人机确认：图结束后仍由用户点「应用到画布」→ `ai_apply_draft`。

---

## 4. 如何跑通

1. 设置页启用 AI，填 OpenAI 兼容 Base URL / API Key / Model  
2. 「测试连接」走 `test_chat_model`（LangChain `invoke`）  
3. 对话模式 → `run_chat_graph`  
4. 编排模式 → `run_flow_graph`  

依赖见 `requirements.in`：`langchain-core`、`langchain-openai`、`langgraph`、`langgraph-checkpoint-sqlite`。

---

## 5. 如何加一个配方

编辑 `backend/core/ai/graphs/recipes.py`：

1. 在 `_apply_step` 的 `action == "recipe"` 分支增加名称  
2. 实现 `_recipe_xxx(draft, ...)`：用 `draft_builder.add_node` / `connect`  
3. 在 `FlowSpec` / planner prompt 里写明可用 recipe 名  

示例已有：`ocr_click_chain`、`delay_type`、`type_enter`。

---

## 6. 学习对照清单

- [x] ChatOpenAI + base_url 兼容网关  
- [x] ChatPromptTemplate / SystemMessage  
- [x] StructuredTool（`lc/tools.py`）  
- [x] `with_structured_output(FlowSpec)`  
- [x] StateGraph + TypedDict + 条件边  
- [x] SqliteSaver checkpoint  
- [x] 流式 token → `ai_progress`  
- [ ] （可选后续）InMemoryRetriever 积木说明 RAG  
- [ ] （可选后续）图内 `interrupt` 等人机取点  

---

## 7. 相关文件

- 计划原文：`docs/FLOW_AI_TECHNICAL_PLAN.md`  
- 测试：`backend/test_ai_recipes.py`、`backend/test_ai_lc_models.py`、`backend/test_ai_tools.py`（含 flow graph mock）  
