# LLM 桥接积木（llm_convert / llm_forward）

版本：v1（2026-09-09）

## 背景与定位

部分 LLM 端点有两类接入障碍：

1. **不支持跨域（CORS）**：浏览器内前端代码直接 `fetch` LLM 端点被预检拦截；
2. **API 形态不一**：OpenAI 新版 **Responses API**（`/v1/responses`，`input`/`output` 词汇）
   与广泛使用的 **Chat Completions**（`/v1/chat/completions`，`messages`/`choices` 词汇）
   请求与响应结构互不兼容，手写适配容易漏语义。

对应两块积木，共享一个转换内核：

| 积木 | 定位 | 副作用分级 |
| --- | --- | --- |
| `llm_convert` | 纯格式转换，不发网络。数据可以是 JSON 字符串或上游绑定来的对象 | SAFE（AI 可直接执行） |
| `llm_forward` | 本机 Python 侧代发请求（无跨域限制），可选在转发途中做格式转换 | ELEVATED（网络请求，同 http_request） |

两块分开而非合一的理由：

- 转换是纯函数、可独立测试、可在流程中间做数据整形（如把 http_request 拿到的
  responses 响应转成 chat 格式再喂给其他积木），与"发请求"是两件事；
- 副作用分级不同：转换零风险可进 SAFE 白名单，转发必须走网络危险闸；
- 转发场景里转换是可选项（`convert: none` 透明转发），内嵌同一内核而非复制逻辑。

## 文件布局

- `backend/blocks/_llm_formats.py` — 共享转换内核（纯函数，不发网络，不改输入）。
  下划线开头，注册扫描自动跳过。
- `backend/blocks/llm_convert.py` — 转换积木（SCHEMA + handler）。
- `backend/blocks/llm_forward.py` — 转发积木（SCHEMA + handler）。
- `backend/test_llm_bridge.py` — 内核映射 + 积木行为 + 本地 HTTP 回显服务端到端 + 接线分级。

## 转换内核映射口径（v1）

### 请求转换

| Chat Completions | Responses | 说明 |
| --- | --- | --- |
| `messages[]` | `input[]` | 见下方消息映射 |
| `max_tokens` / `max_completion_tokens` | `max_output_tokens` | |
| `tools[{type:function, function:{...}}]` | `tools[{type:function, name, description, parameters, strict}]` | 扁平化/嵌套互转 |
| `tool_choice: {type:function, function:{name}}` | `tool_choice: {type:function, name}` | |
| `response_format: {type:json_object}` | `text.format: {type:json_object}` | |
| `response_format: {type:json_schema, json_schema:{name,schema,strict}}` | `text.format: {type:json_schema, name, schema, strict}` | |
| `instructions`（responses 独有） | chat 侧转为第一条 system 消息 | |
| `model/temperature/top_p/stream/parallel_tool_calls/metadata/user/store` | 同名直传 | |

消息映射（chat ↔ responses）：

- `role` 消息：content 为字符串时 user/system 直接沿用；assistant 侧 chat 用
  `text` 部件、responses 用 `output_text` 部件；
- 部件互转：`text` ↔ `input_text`（user 方向）/ `output_text`（assistant 方向）；
  `image_url:{url}` ↔ `input_image`；
- chat `tool_calls`（assistant 消息里的数组）↔ responses `function_call` 独立输入项
  （`call_id` + `name` + `arguments`）；
- chat `role:tool`（`tool_call_id` + content）↔ responses `function_call_output`
  （`call_id` + `output`）；非字符串 output 一律 JSON 序列化成字符串；
- responses `input` 为纯字符串时，chat 侧展开成单条 user 消息；
- responses `reasoning` 输入项丢弃（chat 无等价载体），不报错。

### 响应转换

| Chat | Responses |
| --- | --- |
| `choices[0].message.content` | `output[]` 中 `type:message` 项（`output_text` 部件），另合成顶层 `output_text` 便捷字段 |
| `choices[0].message.tool_calls[]` | `output[]` 中 `type:function_call` 项 |
| `finish_reason: stop/tool_calls` | `status: completed` |
| `finish_reason: length` | `status: incomplete` + `incomplete_details:{reason:max_output_tokens}`（可逆） |
| `usage.prompt_tokens/completion_tokens/total_tokens` | `usage.input_tokens/output_tokens/total_tokens`；`*_tokens_details` 同步换名 |
| `error` 对象 | 原样携带，`status: failed` |

约束与已知取舍：

- 仅映射**第一个 choice**（responses 无 `n>1` 等价物），多 choice 请求走 responses
  需自行拆分；
- `reasoning`、`logprobs`、服务端工具（web_search 等）v1 不映射；
- 流式（SSE 分片）不转换——转发积木按非流式 JSON 处理，流式请求请直连端点；
- 转换不改输入（深拷贝语义），`source == target` 时原样浅拷贝返回。

## llm_forward 行为细节

**定位**：纯转发器，不是对话积木——payload 是完整请求体 JSON，积木不解析、
不包装、不丢字段（含各家扩展参数），响应原文返回。

**双模式**（mode 参数，仅控制画布字段显隐，handler 共用）：

- **简易模式**（默认）：只填 `base_url` + `api_key` + 请求体，其余全自动。
- **手动模式**（mode: custom）：额外露出模型覆盖、格式转换、额外请求头、超时。

**payload**：完整请求体，JSON 对象或 JSON 字符串。`messages` 走
`/chat/completions`、`input` 走 `/responses`，端点按格式自动路由。

**自动行为**（用户零配置的部分）：

- 端点：`base_url` + 按请求格式自动拼 `/chat/completions` 或 `/responses`；
  base_url 已带完整端点路径时原样使用（与生图节点 `_images_url` 同套路）；
- 认证：`api_key` → `Authorization: Bearer …`；Content-Type 自动补；本地端点
  （Ollama/LM Studio）key 留空则不带认证头；
- base_url / api_key 留空自动沿用「设置 → Nexuz AI」的服务商配置（`get_ai_config`）；
- 模型补齐（三级）：model 参数（覆盖）> payload 自带 > 设置里的模型（仅
  payload 缺 model 时补，不覆盖已有值）。

**convert 方向语义**：入口格式是调用方手里的格式，出口格式是端点要求的格式。
响应按出口格式转回入口格式返回，调用方全程只见入口格式。请求体会按出口
格式路由到对应端点（chat_to_responses → /responses）。

**错误与边界**：

- 非 2xx：HTTPError 响应体尽力读出并解析进 `response`/`response_json`，
  `error` 带 `HTTP <code>: <reason>`——端点报错正文（如配额不足）对调用方可见；
- 非 JSON 响应：`ok:false`，响应原文前 500 字进 `error`；
- 超时 1–300 秒钳制，默认 120；仅支持 POST；
- 输出 `text` 是从响应抽出的助手纯文本（chat/responses 都认），供流程直接绑定；
- 流式（SSE 分片）不转换——按非流式 JSON 处理。

## 接线清单（本次实际改动）

1. `backend/core/ai/run_block.py`：`llm_convert` → `RUN_BLOCK_SAFE`；
   `llm_forward` → `RUN_BLOCK_ACTION`（网络副作用）。
2. `backend/core/ai/ai_catalog.py`：两块积木的 description/key_params 条目。
3. `backend/core/execution_policy.py`：`llm_forward` 进 `ELEVATED_TYPES` 与
   `CAPABILITY_LABELS`（仅 agent 执行链的 `__policy_floor__` 下限扫描会用到；
   用户自跑流程不做策略拦截）。`llm_convert` 纯转换无需列入。
4. `frontend/src/bridge.js`：`MOCK_SCHEMAS` 补两条目（Vite 纯浏览器开发兜底一致性）。
5. `backend/core/ai/config.py`：复用既有 `get_ai_config`，llm_forward 的
   base_url/api_key/model 留空时自动回退到「设置 → Nexuz AI」配置（同生图节点）。
6. `mcp_bridge.py` / `nexuz_mcp.py` 未动：run_block 通用分发，白名单生效即可被外部 AI 调用。

## 测试

`python -m pytest backend/test_llm_bridge.py -q`（30 例）覆盖：

- 格式探测（请求/响应/kind）与无法识别时的报错；
- 双向请求映射逐字段断言、chat→responses→chat 语义往返（工具调用、usage、
  instructions、json_schema 严格模式、length↔incomplete）；
- 转换不改输入；
- 错误体双向透传（`insufficient_quota` 类）；
- llm_convert 积木：字符串/对象输入、同格式直通、错误文案；
- llm_forward 积木：本地回显 HTTP 服务端到端（请求体原样转发不包装 /
  模型三级补齐 / 端点按格式路由 / 完整端点 URL 直用 / 设置回退 base_url 与
  key / 额外头到达端点 / 转换往返路由到 /responses / HTTP 429 带错误体 /
  非 JSON 响应 / 普通文本被拒——不是对话积木）；
- 接线：registry 注册、run_block 分级、execution_policy 分级、
  mode 显隐字段（show_when 只挂在手动模式参数上，无 system 字段）。
