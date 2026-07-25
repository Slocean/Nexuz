# Flow AI × LangChain / LangGraph

更新日期：2026-07-26  
状态：已接入（Python 侧）— **Compact IR → 解释器编译** 主路径

本文说明 Nexuz 如何用 **LangChain + LangGraph** 做编排，以及和旧自研 tool loop 的概念映射。

---

## 1. 分层

| 层 | 路径 | 作用 |
| -- | ---- | ---- |
| Bridge 门面 | `backend/core/ai/session_manager.py` | 对接 `api.ai_*`，会话/草稿/`agent_state` 持久化 |
| LangGraph | `backend/core/ai/graphs/` | 多阶段状态图（chat / flow） |
| Compact IR | `graphs/agent_ir.py` + `graphs/ir_compile.py` | LLM 瘦输出 → 确定性编译为草稿 |
| LangChain | `backend/core/ai/lc/` | `ChatOpenAI`、Prompt、Tools、`invoke_structured` |
| 领域 | `draft_builder` / `locate` / `tool_runtime` / `outline_build` / `recipes` | 改草稿、OCR/Vision、坐标门禁、宏展开 |
| Checkpoint | `backend/core/ai/checkpointer.py` | SqliteSaver → `{data_dir}/ai/checkpoints.db` |

前端仍走 pywebview Bridge，**不引入 JS 侧 LangChain**。

---

## 2. 概念映射（旧 → 新）

| 旧 SessionManager / 宏路径 | 新实现 |
| -------------------------- | ------ |
| 手写 `httpx` + `/chat/completions` | `lc/models.py` → `ChatOpenAI` |
| `planner(FlowSpec) → apply_flow_spec` | `UnderstandIR → PlanIR → compile_ir` |
| 完整 OutlineStep / ToolActionBatch 主路径 | LLM 只填闭集 op + 短槽位；代码解释展开 |
| 配方/技能当主路径 | `recipes` / `call_skill` 作为编译后端与补洞 |
| `strict_coords=False` | 默认 `True`（裸坐标拒绝） |
| 校验只在 apply | `validate` + 有界 `repair`（代码优先补入口） |

---

## 3. Flow 图节点（主路径）

```
load_context → understand → clarify? → plan_outline → gap_check ↔ plan
           → build_loop(compile_ir) → validate ↔ repair → summarize
```

1. **load_context**：草稿摘要 / points / 积木卡  
2. **understand**：`UnderstandIR`（`intent_tag` / `slots` / `missing`）；澄清文案由代码生成  
3. **clarify**：`missing` 槽位 id → UI；用户作答后 `resume_clarify`  
4. **plan_outline**：`PlanIR`（`steps[{op,a}]` 闭集 opcode）；失败则 `plan_ir_from_slots`  
5. **gap_check**：**代码优先** `gap_from_ir`（不默认喂长 JSON 调 LLM）  
6. **build_loop**：**`compile_ir` 主路径**；仅编译无产出时才短 prompt 补洞（`ToolActionBatch` / tools）  
7. **validate / repair**：入口与坐标门禁；repair 先确定性补 entry  
8. **summarize**：仅陈述事实；`node_count==0` 禁止「已准备好」

人机确认：图结束后仍由用户点「应用到画布」→ `ai_apply_draft`。

### Compact IR 要点

- 槽位键：`window_title|contact|message|run_at|…`（别名如 platform/recipient/content 会归一化）  
- opcode：`activate|ocr_click|type|key|wait|send_im|…`  
- 禁止解释器编造 slots 中未出现的联系人/窗口  
- 结构化调用：`lc/structured_call.invoke_structured`（`json_schema` 优先）

### 感知策略（写在编译/recipe 规则）

- 有明确文字目标 → `ocr_recognize` → click 绑定 `{{id.x/y}}`  
- 无字/图标且支持 vision → 补洞工具链（非 IR 主路径）  
- 禁止裸坐标（`strict_coords=True`）

---

## 4. 如何跑通

1. 设置页启用 AI，填 OpenAI 兼容 Base URL / API Key / Model  
2. 「测试连接」走 `test_chat_model`  
3. 对话模式 → `run_chat_graph`  
4. 编排模式 → `run_flow_graph`  

依赖见 `requirements.in`：`langchain-core`、`langchain-openai`、`langgraph`、`langgraph-checkpoint-sqlite`。

---

## 5. 技能 / 配方 / 评测

技能包仍在 `backend/core/ai/skills/packs/`。  
Offline 评测：`eval_runner` 默认仍走 `heuristic_plan_from_text` + `apply_flow_spec`；带 `expected_ops` / `use_ir` 的用例走 `plan_ir_from_slots` + `compile_ir`。

---

## 6. 学习对照清单

| 想学的概念 | 看哪里 |
| ---------- | ------ |
| StateGraph / 条件边 | `graphs/flow_graph.py` |
| Compact IR | `graphs/agent_ir.py` |
| IR 编译 | `graphs/ir_compile.py` + `outline_build.py` |
| Structured output 网关适配 | `lc/structured_call.py` |
| Tools 补洞 | `lc/tools.py`（非主路径） |
| Checkpoint / agent_state | `checkpointer.py` + `session_manager` |
| 坐标门禁 | `tool_runtime.py` `strict_coords` |
