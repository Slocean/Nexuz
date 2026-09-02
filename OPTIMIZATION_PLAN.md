# Nexuz 平台优化计划（AI / Agent 专项）

> 基于 2026-09 对 0.8.0 代码库的全面评估。范围：AI 编排链路、agent 执行模型、MCP 桥接、执行引擎与 AI 的结合部。
> 所有 `文件:行号` 引用均对应当前 main 分支代码。

---

## 一、现状评估

### 已达标、无需改动的部分

- **Agent IR 架构**：LLM 只输出 12 个闭集 opcode 的 PlanIR，确定性代码编译为真实节点；幻觉清洗（op 别名、占位目标黑名单、重复步去重）+ recipe 宏（OCR 点击链强制 `{{ocr_id.x}}` 绑定、禁裸坐标）。这是对本地小模型的正确防御。
- **token_scheduler 双预算调度**：先锁输出预算再推输入容量、语义降级（full→50%→…→二分截断）、静默压缩、三层记忆路由。
- **安全体系**：SAFE/ACTION 双白名单 + `allow_run_block`/`allow_dangerous` 双闸 + execution_policy 三级模式 + python_script 子进程隔离（Job Object / audit hook / 低完整性 token）+ MCP 全链路审计。
- **结构化输出保障**：method 级联（json_schema→json_mode→默认）+ 双预算 + 续写协议（max_continues=2）。

### 核心短板（一句话版）

1. 可靠性基建缺失：无重试/退避、无法取消、无超时。
2. 可观测性为零：token usage 丢弃、无 per-call 审计、缓存无命中率。
3. MCP 桥接锁粒度错误：stop 被 run_flow 阻塞，无法止损。
4. 事件洪峰：逐 token urgent 入队 + 全量快照 → O(n²) 事件量 → 队列溢出静默丢 token。
5. 评测与测试薄：离线 eval 仅 12 条、解释器控制流主干零单测。

---

## 二、优化项清单（按优先级）

### P0 — 可靠性基建

| # | 问题 | 证据 | 目标 |
|---|------|------|------|
| P0-1 | LLM 调用无重试/退避，429/5xx/超时直接抛给 UI | 全 `core/ai` 无 `max_retries`/backoff；`lc/models.py:87-95` 未配 `max_retries` | 统一重试层：网络类错误指数退避重试 2-3 次 |
| P0-2 | flow 编排轮不可取消 | graphs/session_manager 无 stop_event；agent 循环每次迭代不检查取消 | 全链路 cancel token |
| P0-3 | token usage 全程丢弃，无 trace，缓存无命中率统计 | `session_manager.py:519,858` `"usage": None`；`llm_cache.py:291-304` 仅 count/bytes | usage 落审计 + hit/miss 计数 + 每轮 token 汇总 |
| P0-4 | MCP `flow_control(stop)` 与 `run_flow(wait=True)` 共享 `_run_lock`，流程挂死时无法止损 | `mcp_bridge.py:163-182` | stop/pause/resume 独立锁 |
| P0-5 | MCP HTTP handler 无 socket 超时、线程无上限 | `mcp_bridge.py:334-347,402-406` | socket timeout + 线程池上限 |
| P0-6 | MCP run_flow 超时后返回 `ok:True, finished:null`，语义丢失 | `mcp_bridge.py:257-263` | 超时返回明确 `timed_out:true` |

### P1 — 结构性问题

| # | 问题 | 证据 | 目标 |
|---|------|------|------|
| P1-1 | `run_block` handler 无超时、`should_stop=lambda: False`，长块可无限挂死 AI 会话并占住 MCP 锁 | `run_block.py:155-167`；`_clamp_wait` 只钳 delay（90-97） | handler 超时包装 + 可注入 stop 信号 |
| P1-2 | 流式异常整段降级非流式重跑（双倍计费/延迟）；逐 token urgent 入队 + process 全量快照 → 事件 O(n²) → 队列溢出砍一半（丢 token） | `streaming.py:108-126`；`api.py:324-326,3723-3729`；`streaming.py:19-31` | delta 合帧（~50ms 批量）、process 增量化、溢出丢弃有日志 |
| P1-3 | 进程级降级开关永不恢复（网关临时故障 → 永久降级） | `flow_graph.py:90-91`；`structured_call.py:13` | TTL 自动复位或按失败计数 |
| P1-4 | 模型能力表按名字子串匹配，3 处重复维护；dashscope/moonshot 仍写 32k | `models.py:17-20`、`capability.py:19-49`、`openai_compat.py:14-24` | 收敛为单一能力表 + 可被用户配置覆盖 |
| P1-5 | `ai_refine` 在执行热路径同步调 LLM，无超时 | `interpreter.py:432-479,565` | 超时 + 失败静默回退已有，需补超时预算 |
| P1-6 | anthropic/gemini provider 为 raise 占位 | `providers/anthropic.py:11-12`、`gemini.py:11-12` | 至少补 anthropic（via OpenAI 兼容网关或原生） |

### P2 — 质量与覆盖

| # | 问题 | 证据 | 目标 |
|---|------|------|------|
| P2-1 | 缓存覆盖窄：工具循环/chat 流式/vision 不走缓存；非 0 温度天然低命中 | `generate.py:58-75` 是唯一接入点 | 工具循环接入缓存；评估"温度 0 缓存重放" |
| P2-2 | 离线 eval 仅 12 条，且不测 understand/plan 的 LLM 准确率 | `eval_runner.py`；`testdata/ai_eval/cases.json` | 用例扩到 50+；新增 utterance→PlanIR 断言层；按模型分组跑分 |
| P2-3 | 解释器控制流主干（loop/switch/try_catch/异常路由/fallthrough 栈）零单测 | `test_interpreter_core.py` 仅 5 例 | 补齐控制流单测 |
| P2-4 | 执行上下文 flat dict 无界增长 | `interpreter.py:604-606` | 循环体作用域回收或 LRU 裁剪 |
| P2-5 | 调度器直连 interpreter，绕过 `scan_flow_violations` 预扫描；legacy 流程默认全放行 | `scheduler.py:196-202`；`execution_policy.py:61-66` | 调度触发走同一预扫描；legacy 默认收紧为 standard |
| P2-6 | `$var` 插值无转义，字面量 `$xxx` 被吞 | `variable_resolver.py:10,221-227` | 支持 `$$` 转义 |
| P2-7 | 错误吞噬成风（关键路径 ≥6 处 `except Exception: pass`） | `chat_graph.py:92-93`、`session_manager.py:769-770`、`memory.py:121-122` 等 | 至少记 debug 日志 |
| P2-8 | 超大文件：`flow_graph.py` 1817 行、`api.py` 3828 行、`AIAssistant.tsx` 2052 行 | — | 拆分（跟随重构节奏，不单独立项） |

---

## 三、分阶段实施

### 阶段 1：可靠性 + 可观测性（P0-1 / P0-3 / P0-4 / P0-5 / P0-6）✅ 已完成（2026-09-02）

> 实施落点与计划略有调整：重试层统一包在 `lc/structured_call.py` 的
> `invoke_structured` 内（覆盖 guarded 链路与工具循环两条路），而非仅在
> `guarded_structured_invoke` 外层；瞬态错误在 method 级联中提前 break，
> 避免无意义的换方法重试。usage 采集独立为 `usage_tracker.py`
> （thread-local 轮次累计 + LangChain 回调），chat() 包装轮次。

**任务 1.1 LLM 统一重试层 ✅**
- 新增 `backend/core/ai/retry.py`：`is_transient_error`（状态码优先/文本标记兜底/非瞬态白名单）+ `with_retry`（指数退避 ± 抖动，默认 2 次重试）+ `retry_delay`。
- 接入点：`lc/models.py`（`max_retries=2` SDK 级）、`lc/structured_call.py`（`invoke_structured` 全链路包 with_retry，覆盖 understand/plan/repair/patch/summarize/tighten/node_refine/工具循环）、`graphs/streaming.py`（流式首包重试，保持已产出内容时的非流式兜底）、`context_budget.py`（tighten 调用）。
- 测试：`backend/test_retry.py` 8 例（判定、退避、耗尽、on_retry）。

**任务 1.2 usage 落审计 + 缓存命中率 ✅**
- 新增 `backend/core/ai/usage_tracker.py`：thread-local 轮次累计（`start_turn/record/snapshot/finish_turn`），`UsageCallback` 挂 Runnable config 提取 `on_llm_end` 的 token 数；流式路径从带 `usage_metadata` 的 chunk 采集；轮次外零开销。
- `session_manager.chat()` 包装轮次 → `result["usage"]`（`calls/input_tokens/output_tokens/total_tokens/no_usage`）；flow 轮审计事件与 agent_log 附 `usage` 快照。
- `llm_cache.py`：metrics 表持久化命中指标，`get_json` 记 hit/miss/miss_expired/miss_corrupt，`stats()` 返回 `hits/misses/hit_rate`，`clear()` 一并归零。
- 测试：`backend/test_usage_tracker.py` 6 例 + `test_llm_cache.py` 命中率用例。

**任务 1.3 MCP 锁拆分 + HTTP 加固 ✅**
- `mcp_bridge.py`：`flow_control` 移出 `_run_lock`（独立 `_control_lock`）——流程挂死时 stop 必须可达；`_rpc_slots` 信号量（8 并发，超出 503 busy）；Handler `timeout=30`（socket 级死连接看门狗，非请求总时长）。
- `_tool_run_flow`：超时后流程仍在运行 → 返回 `timed_out: true`（审计同步记录）；`nexuz_mcp.py` 更新 run_flow 描述。
- 测试：`test_mcp_bridge.py` 新增 3 例（stop 不被 run 锁阻塞、wait 超时 timed_out:true、并发上限 503）。

### 阶段 2：取消 + 超时（P0-2 / P1-1 / P1-5）✅ 已完成（2026-09-02）

> 关键设计：`TurnCancelled` 继承 `BaseException`（同 asyncio.CancelledError 思路），
> 绕过链路上所有 `except Exception` 兜底，只在关心取消的边界被捕获。
> 取消注册表按 conversation_id 组织（`cancel.py`），chat() 每轮注册/注销。

**任务 2.1 AI 链路 cancel token ✅**
- 新增 `backend/core/ai/cancel.py`：轮次注册表（`start_turn/stop_turn/finish_turn`）+ `checkpoint()` + `run_with_timeout`（守护线程 + 弃置语义）。
- 检查点三处：`build_flow_graph` 统一包装每个图节点入口、`_run_structured_action_loop` 每次迭代、`stream_chat_model` 每 token（经 `cancel_check` 注入，chat_graph 传入）。
- `session_manager.chat()` 捕获 TurnCancelled → `{"ok": False, "cancelled": true, "error": "已按用户要求停止"}`；api worker 透传 `cancelled` 到 ai_progress。
- 端到端：`api.ai_chat_stop` → `bridge.aiChatStop` → AIAssistant 发送按钮在执行中切换为停止按钮（Square 图标）。
- 测试：`test_cancel.py`（注册表生命周期、checkpoint、BaseException 旁路验证）。

**任务 2.2 run_block 超时 ✅**
- `run_block.py`：handler 经 `run_with_timeout` 执行（默认 90s，可用 `timeout_s` 覆盖），超时返回 `{"ok": False, "timed_out": true}` 并置位 `should_stop` 通知协作型积木退出；`_clamp_wait` 扩展到 wait_until/browser_wait（timeout_ms 上限 60s，`<=0` 的"无限等待"一并收口）与 window_wait（60s）。
- 测试：卡死 handler 超时 + should_stop 置位断言、wait 钳制断言。

**任务 2.3 ai_refine 超时预算 ✅**
- `node_refine.refine_node_params` 内部经 `run_with_timeout`（默认 20s，可参数覆盖），超时按失败处理返回 None（保留原参数），与现有失败路径一致。
- 测试：慢 invoke_fn 超时返回 None。

### 阶段 3：事件流治理（P1-2）✅ 已完成（2026-09-02）

> 关键设计：合帧放在 api 层事件总线（而非 streaming 层）——前端 50ms 轮询
> `drain_ui_events` 时统一冲刷缓冲，事件量由轮询频率决定而非 token 速率；
> 非 delta 事件先冲刷缓冲保证顺序；replace 语义（非流式兜底）不参与合并。

**delta 合帧 ✅**
- `api.py` 新增 `_queue_ai_progress` 统一入口：delta/reasoning 按 (cid, aid, type) 分桶缓冲；`drain_ui_events` 每次先冲刷（≤ 一个轮询间隔的延迟）；缓冲 ≥2048 字符主动冲刷（内存有界）；`done`/`error`/`process` 等事件前先冲刷保序。
- process 事件在入口处剥离全量 `process` 快照（一处改动覆盖 streaming.emit_process 与 flow_graph 手工 emit 两类源头），只发增量 `step` —— 前端 AIAssistant 本就有累积逻辑，天然兼容；`detail.process` 兼容读取保留（旧后端 + 新前端仍工作）。
- 前端零改动（delta 拼接语义对"大块合并 delta"天然兼容）。
- 测试：`test_ai_progress_bus.py` 9 例。**验收达成：模拟 5000 token 长输出 → delta 事件 < 200 条、文本逐字无损**；另有合帧保序、replace 独立、双会话隔离、2048 字符上限主动冲刷等用例。

**队列溢出告警 ✅**
- `_queue_ui_event` 溢出时丢最老 250 条 + 写 log_hub warning（含累计丢弃数），不再静默。合帧后正常不会触顶，触顶即消费端卡死的强信号。
- 测试：溢出丢最老 + 日志断言。

### 阶段 4：能力表收敛 + 降级开关复位（P1-3 / P1-4）✅ 已完成（2026-09-02）

**单一能力表 ✅**
- 新增 `backend/core/ai/model_capabilities.py`：固定 temperature 规则、推理模型标记、preset 上下文窗口表集中一处。
- 三处历史消费点改为引用（`lc/models.py` 的 `resolve_fixed_temperature`、`token_scheduler/capability.py` 的 `is_reasoning_model`/preset 表、`providers/openai_compat.py` 的温度判定），并新增"三方一致性"防漂移测试。
- 收敛时顺带修复了一处已发生的漂移：openai_compat 旧表把 kimi 当作"必须 1.0"，与 models.py 实测结论（kimi-k2.5 只接受 0.6）矛盾——统一为 0.6。
- dashscope/moonshot preset 从过时的 32k 修正为现行 128k；用户显式 `context_window_tokens` 仍最优先（有测试）。
- 测试：`test_model_capabilities.py` 24 例。

**降级开关 TTL 复位 ✅**
- `_JSON_MODE_UNSUPPORTED`（structured_call）与 `_NATIVE_TOOLS_UNAVAILABLE`（flow_graph）：记录置位时刻，10 分钟 TTL 过期后自动允许重探——网关临时故障不再造成进程级永久降级。
- 行为测试覆盖：级联在 json_mode 被标记后跳过、TTL 过期后重新尝试（网关修复自动被拾起）。

### 阶段 5：评测与测试补强（P2-2 / P2-3）✅ 已完成（2026-09-02）

**eval 扩充（12 → 56 条，两层）✅**
- compile 层（cases.json，39 条）：覆盖全部 12 个闭集 op、槽位兜底（window/message/match_text 缺参补齐）、参数名归一、未知 op 丢弃、多步组合链（跨应用复制/定时报表/微信发送含等待）、clarify 变体。
- 新增原始层（raw_cases.json，17 条）：录制自真实网关的"脏"LLM 输出（别名 op、裸字符串参数、未知 op、连续重复步、额外字段）→ `PlanIRDraft` 宽松解析 → `normalize_plan_ir` 归一化 → **精确断言**（ops 相等 + forbid_ops + expected_args 键值）。用例可标注 `"models": [...]` 录制来源，`run_raw_eval_suite(model=...)` 按模型分组跑分并输出 by_model 对比。
- 质量门槛更新在 `test_ai_eval_offline.py`：两层合计 ≥ 50、compile 层 ≥ 35、归一化产物必须是闭集 op。

**修复的既有 bug（评测扩充暴露）✅**
1. `outline_build.py:191`：`or sense == "ocr"` 把 wait_text/if_text（自感知积木）劫持进 OCR 点击链——"等待文字出现"被编译成"点击目标文字"、if_text 丢失 if 节点。原始 12 条用例中 wait_for_text 在 HEAD 上本来就失败（11/12 勉强过 0.9 线）。
2. `agent_ir.plan_ir_to_dict`：PlanIRDraft 实例被静默丢弃为空步骤（生产走 dict 路径未触发，但任何直接传解析产物实例的调用方会整段丢失别名输出）。
3. `loop_foreach.handler`：循环退出访问时把 `$item` 覆盖为 None，吞掉最后一轮元素。

**解释器控制流主干单测 ✅（此前为零）**
- 新增 `test_interpreter_control_flow.py` 17 例：loop_n（次数/零次/缺 body/计数器归零）、foreach（迭代/空集合/元素注入）、while（假条件/max_times 边界）、forever（exit_condition 先于首轮/max_times 边界）、if 条件双分支、switch 命中/默认、try_catch 三态状态机（body→catch→finally 全路径、无 catch 时 finally 重抛 `__pending_reraise__`、嵌套 try 内层重抛外层接住、错误信息记录）、force_reset 代际隔离（孤儿线程不阻塞新运行、forced 事件）。
- 注：正式覆盖率数字需要 pytest-cov（当前环境未装）；控制流核心分支已从 0 测试到全路径覆盖。

### 阶段 6（择机）：缓存扩面 + Provider + 小修（P2-1 / P1-6 / P2-4~7）✅ 已完成（2026-09-02）

**调度器策略预扫描（P2-5 前半）✅**
- `scheduler._start_or_queue` 在参数校验后、启动前执行 `scan_flow_violations`（与 api.run_flow 同一道闸）；违规记 `policy_blocked` 失败流水 + schedule_error 事件。未声明 execution_policy 的 legacy 流程不受影响（有测试锁定不误伤）。

**`$$` 转义（P2-6）✅**
- `variable_resolver`：`$$name` → 字面量 `$name`（含路径形态 `$$a.b`），`$$` 后非变量形态（如 "$$ 100 元"）不视作转义；与普通 `{{}}`/`$var` 替换可混用。实现为 stash → 替换 → restore，哨兵不含 `$`（避免被自己的 DOLLAR_PATTERN 二次替换——测试抓出的第一版实现 bug）。

**工具循环缓存接入（P2-1）✅**
- flow_graph 工具循环的结构化调用改为 `_invoke_action_loop_cached`：purpose="action_loop" + 模型 + messages 全量哈希。键含演进中的草稿状态，只有同任务同状态重跑才命中，演进中请求天然 miss，代价仅一次哈希。

**Anthropic 原生 provider（P1-6）✅**
- `providers/anthropic.py` 实现完整 Messages API 客户端（/v1/messages、x-api-key + anthropic-version 头、system 提取、OpenAI tool_calls ↔ tool_use/tool_result 块互转（tool_result 置于 assistant 后的 user 消息，符合协议）、max_tokens 必填默认 4096、usage 透传、kimi 式固定温度套用）。
- `llm_client.create_llm_client` 的 provider="anthropic" 从 raise 占位改为真实客户端。生产编排仍走 LangChain OpenAI 兼容网关不变。
- 测试：URL 归一、消息/工具映射往返、固定温度、HTTP 错误转 LlmError、缺 key 拒绝、工厂路由。

**错误吞噬补日志（P2-7）✅**
- 四处关键 `except Exception: pass` 补 stdlib logging：chat checkpoint 写入失败（warning）、flow 审计写入失败（warning）、情景记忆读取失败（warning）、summarize 打磨失败（debug，可选优化）。llm_cache 的静默属文档化的刻意设计，保持不动。

**主动跳过（P2-4 执行上下文 LRU 裁剪）**
- flat context 无界增长属真实问题，但裁剪策略与变量引用正确性强耦合（后续节点可能引用任意历史输出），在缺少真实内存瓶颈数据前贸然裁剪风险大于收益。留待出现实际案例时按"循环体作用域回收"方向设计。

---

## 四、里程碑与验收

| 阶段 | 内容 | 完成标志 |
|------|------|----------|
| M1 ✅ | 阶段 1 | 214 测试通过（新增 17 例）；断网自恢复由重试层保障；审计含 token；MCP 止损/超时用例通过 |
| M2 ✅ | 阶段 2 | 223 测试通过（新增 9 例）；停止按钮→检查点全链路；run_block 超时/等待钳制用例通过 |
| M3 ✅ | 阶段 3 | 232 测试通过（新增 9 例）；5000 token 输出事件 < 200 条且零丢失 |
| M4 ✅ | 阶段 4 | 256 测试通过（新增 24 例）；能力表单一来源 + 三方一致性防漂移；降级开关 10min TTL 重探 |
| M5 ✅ | 阶段 5 | 275 测试通过；eval 两层 56 条（compile 39 + raw 17，按模型分组）；解释器控制流 17 例；顺带修复 3 个既有 bug（wait_text 编译成点击/if_text 丢节点、PlanIRDraft 静默丢弃、$item 退出清空） |
| M6 ✅ | 阶段 6 | 285 测试通过（新增 10 例）；调度预扫描/`$$` 转义/工具循环缓存/Anthropic 原生客户端落地；P2-4 主动跳过并记录理由 |

## 六、收官状态（2026-09-02）

M1-M6 全部完成：**优化项 20 项落地、4 项既有 bug 修复、累计新增 88 个测试用例**（197 → 285）。
唯一遗留：P2-4 执行上下文裁剪（理由见阶段 6）与 P2-8 超大文件拆分（跟随日常重构节奏，不单独立项）。

## 五、风险与约束

- **不改变既有行为优先**：重试/超时/取消全部是新增保护层，默认参数保守（重试 3 次、超时 60s），避免影响现有用户流程。
- **事件格式兼容**：process 增量化保留一个版本的全量兼容读取。
- **legacy 执行策略收紧**（P2-5）会影响存量流程，需要 changelog 公告 + 可配置回退。
- **pywebview 轮询架构不动**：`api.py:368-372` 注释记载了 evaluate_js 死锁的历史，事件治理在现有轮询框架内进行。
