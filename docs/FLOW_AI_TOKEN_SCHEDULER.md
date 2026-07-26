# Flow AI Token Scheduler

更新日期：2026-07-26  
关联：[`FLOW_AI_LANGGRAPH.md`](./FLOW_AI_LANGGRAPH.md)

## 一句话

**输入侧装箱（ContextCompiler），输出侧排产（OutputPlanner），由 BudgetScheduler 统一决策。**  
Agent 状态 = 结构化状态 + 可检索记忆 + 动态上下文包——不是「全聊天记录硬塞」。

## 模块

路径：`backend/core/ai/token_scheduler/`

| 模块 | 职责 |
| ---- | ---- |
| `capability.py` | 模型能力表：`context_window_tokens` 显式配置 > preset > local/cloud 默认 |
| `output_planner.py` | 按 `output_profile` 锁定 completion |
| `scheduler.py` | `plan_call`：先锁输出，再算 `available_input` |
| `compiler.py` | 分层优先级装箱 / 工具结果提炼 |
| `guard.py` / `continuation.py` | 截断检测与结构化续写 |
| `memory.py` | Working / Summary / Episodic（磁盘会话关键词召回，无向量库） |
| `generate.py` | `guarded_structured_invoke` 统一入口 |

## 调用约定

```text
budget = plan_call(cfg, profile, system_text=...)
messages = [System(...), Human(compile_layers(layers, budget.available_input))]
result = guarded_structured_invoke(cfg, profile, schema, messages)
```

公式：

```text
available_input =
  max_context_tokens
  - reserved_output_tokens
  - safety_margin
  - system_tokens
  - tool_overhead
```

## 配置字段（AiConfig）

- `context_window_tokens`：上下文窗（可覆盖默认）
- `max_output_tokens`：输出硬顶（可选）

型号子串（kimi / o1…）仅作未配置时的弱默认抬升，不是主路径。

## 三期边界

1. **P1** 调度闭环 + Guard/续写 + flow 接入  
2. **P2** 编译结果进入 understand/plan/repair/tool 真 messages  
3. **P3** MemoryRouter 注入（Working/Summary/Episodic）

本期实现覆盖 P1–P3 代码路径；不做向量库、不做 IR 三次骨架填充。
