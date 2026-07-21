# Nexuz Flow AI 技术计划

更新日期：2026-07-21  
状态：设计稿 / 待排期  
关联：[`2026-07-19-平台功能不足分析.md`](./2026-07-19-平台功能不足分析.md)、[`schemas/flow_schema.json`](../schemas/flow_schema.json)、[`02-架构文档.md`](../02-架构文档.md)

---

## 1. 目标与非目标

### 1.1 产品目标

用户用自然语言描述自动化意图（可选附当前屏幕），系统通过 **Function Calling** 调用平台能力，生成符合 Nexuz `FlowModel` 的流程，并在需要坐标时通过 **截图 + 识别取点** 回填，经用户确认后落到画布。

核心闭环：

```
用户意图（+ 可选截图）
  → LLM + Tools（积木编排 / 截图 / 定位）
  → 草稿 FlowModel（严格 Schema）
  → 画布预览 + 点位确认
  → 写入 store / 可运行
```

### 1.2 非目标（本期不做）

| 项 | 说明 |
| -- | ---- |
| MCP Server | 本期不引入；LLM 在进程内直接调 Python tools |
| 外部 Agent 远程编排 | 可后续把同一 tool 层包成 MCP，非前置 |
| 通信 / IM 通道 | 飞书、钉钉、Webhook 等另立项 |
| 替代执行引擎 | 不改 Interpreter；AI 只写流程数据 |
| 无确认全自动点屏幕 | 生产默认需预览确认；可配置「信任自动落点」为高级选项 |
| 设计稿 Gemini Express 路径 | `frontend/canvasflow/server.ts` 的 `/api/ai-assistant` 仅 DEV 演示，不作为生产链路 |

### 1.3 设计原则

1. **结构靠 Tools + Schema，不靠提示词死约束**  
2. **坐标不得由模型空想**；必须来自定位 tool / 用户修正 / 已有变量绑定  
3. **积木目录单一真相源**：`BLOCK_REGISTRY` 的 `SCHEMA` 自动生成 tool 定义  
4. **走 Python Bridge**，与正式桌面路径一致（对齐不足分析中的 P1-A1）  
5. **先 OCR 取点，后可选 Vision**；Vision 为增强，不是 MVP 阻塞项  

---

## 2. 现状底座（可复用）

| 能力 | 位置 | 用途 |
| ---- | ---- | ---- |
| Block 注册表 | `backend/core/registry.py` | Schema → tool 参数 |
| Bridge 积木列表 | `api.get_block_registry` | 前端 / AI 侧枚举能力 |
| Flow 校验 | `api.validate_flow` + `schemas/flow_schema.json` | 落盘前校验 |
| 全屏截图 | `api.capture_desktop` | 返回 `data_url` + `coord_space` |
| 点/区域打包 | `api.pack_screen_point` / `pack_screen_region` | 与人工取点同语义 |
| OCR / 文字定位 | `ocr_recognize` / `locate_text` | 文字 UI 取点 |
| 找图 | `find_image` | 模板图定位（可选 tool） |
| 画布写入 | `addNodeFromSchema` / `setFlow` | 应用 AI 草稿 |
| Flow AI UI 壳 | `AIAssistant.tsx`（仅 DEV 显示） | 可复用面板，改接 Bridge |

---

## 3. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (canvasflow)                                           │
│  AIAssistant ─► bridge.aiChat / aiApplyDraft                     │
│       │                    ▲                                     │
│       │ 草稿预览 / 点位确认 │ 事件：tool 进度、截图预览、diff      │
└───────┼────────────────────┼─────────────────────────────────────┘
        │ pywebview Bridge   │
┌───────▼────────────────────┴─────────────────────────────────────┐
│  backend/api.py（门面）                                            │
│    ai_session_start / ai_chat / ai_confirm_apply / ai_cancel      │
└───────┬──────────────────────────────────────────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────────┐
│  backend/core/ai/（新建）                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ session      │  │ llm_client   │  │ tool_runtime            │ │
│  │ 多轮消息/草稿 │  │ 供应商适配   │  │ 执行 tool + 权限门禁    │ │
│  └──────────────┘  └──────┬───────┘  └───────────▲─────────────┘ │
│                           │ function calling       │               │
│  ┌────────────────────────▼───────────────────────┴─────────────┐ │
│  │ tool_catalog：SCHEMA → OpenAI/Anthropic/Gemini tools JSON    │ │
│  │ 编排 tools + 感知 tools（截图/OCR/定位）                        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│         │ 写草稿                    │ 调既有能力                    │
│         ▼                           ▼                               │
│  FlowDraftBuilder          capture_desktop / OCR / pack_point       │
│         │                                                           │
│         ▼                                                           │
│  validate_flow → 返回 DraftDiff 给前端确认                          │
└─────────────────────────────────────────────────────────────────────┘
```

**数据流要点**

- LLM **从不**直接改正在编辑的正式 flow；只改 **Session Draft**。
- 用户确认后，前端一次 `setFlow` / 批量 `addNodeFromSchema`，并走现有校验。
- 高危 tool（如 `run_command`、任意路径 `file_io`）默认不进入 AI tool 目录，或需显式白名单。

---

## 4. 模块设计

### 4.1 目录建议

```
backend/core/ai/
  __init__.py
  session.py           # AiSession：消息、draft、tool 轨迹
  llm_client.py        # 统一 chat(tools) 接口
  tool_catalog.py      # SCHEMA → tool definitions
  tool_runtime.py      # 分发执行 + 审计日志
  draft_builder.py     # 对 FlowModel 草稿的增删改连
  locate.py            # 截图 + OCR/Vision 定位编排
  prompts.py           # 系统提示（意图与策略，不含 Schema 全文）
  providers/
    openai_compat.py
    anthropic.py       # 可选
    gemini.py          # 可选
```

前端：

- 复用 `AIAssistant.tsx`，去掉对 `/api/ai-assistant` 的 `fetch`
- 经 `bridge.js` 调用 Python：`aiChat`、`aiGetSession`、`aiApplyDraft`
- 增加「草稿 Diff / 点位预览层」（可叠在截图或画布上）

### 4.2 LLM Client

统一接口（示意）：

```python
class LlmClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ) -> LlmTurn:
        """返回 assistant 文本 和/或 tool_calls。"""
```

配置（设置页 / 环境变量，二选一或并存）：

| 键 | 说明 |
| -- | ---- |
| `NEXUZ_AI_PROVIDER` | `openai_compat` / `anthropic` / `gemini` |
| `NEXUZ_AI_BASE_URL` | 兼容网关（可选） |
| `NEXUZ_AI_API_KEY` | 密钥；存用户数据目录加密或 OS 凭据，禁止写进 flow |
| `NEXUZ_AI_MODEL` | 默认模型名 |
| `NEXUZ_AI_VISION_MODEL` | 可选；未配则定位仅走 OCR |

**约束**：密钥与请求只在 Python 侧；前端不持有 key，不直连公网 LLM（生产路径）。

### 4.3 Tool Catalog：SCHEMA → Function

#### 4.3.1 生成规则

对每个 `SCHEMA`：

- `type` → tool 名空间中的积木类型（见下）
- `inputs[]` → JSON Schema `properties` / `required`
- `select` → `enum`
- `bindable` 字段允许 string（含 `{{var}}`）或 primitive
- `label` / `category` → tool `description`

**不要**为每个积木单独做一个「巨型 add_xxx」导致 tool 爆炸；采用 **少量编排原语 + 动态类型枚举**：

| Tool | 作用 |
| ---- | ---- |
| `list_blocks` | 按 category 返回精简目录（type/label/简述） |
| `get_block_schema` | 取单个 type 的完整 inputs |
| `draft_add_node` | 向草稿添加节点：`type` + `params` + 可选 `node_id` + `position` |
| `draft_update_node` | 改 params / 控制边 |
| `draft_connect` | 设置 `next` / `then` / `else` / `body` / `catch` / `finally` |
| `draft_set_entry` | 设置 `entry` |
| `draft_remove_node` | 删除节点并清理边 |
| `draft_get` | 返回当前草稿摘要（防上下文漂移） |
| `capture_screen` | 隐藏主窗后截虚拟桌面，返回句柄/尺寸/`coord_space`（大图不回灌全文给模型时可只回 meta + 缩略图策略） |
| `locate_text_on_screen` | OCR 找文字 → 中心点；内部走 RapidOCR |
| `locate_image_on_screen` | 可选；模板路径 + matchTemplate |
| `pack_point` | 把绝对坐标打成与人工取点一致的 packed 结构 |
| `bind_point_to_node` | 将 packed 点写入指定 click/hover 等节点 params |

可选二期：

| Tool | 作用 |
| ---- | ---- |
| `locate_vision` | 多模态：描述目标 → bbox/中心点 |
| `run_draft_dry` | 静态校验 + 模拟走图（不真点击） |

#### 4.3.2 为何不用「一积木一 function」

- 积木约 40+，全量塞进 tools 会降低选中率。
- `list_blocks` → `get_block_schema` → `draft_add_node` 两跳后，参数仍 100% 来自真实 SCHEMA。
- 新增积木自动出现在 `list_blocks`，零手工同步。

若某供应商对「动态 enum」不友好：可对 **高频动作类**（`click`、`type_text`、`delay`、`ocr_recognize`、`if_condition`、`loop_n`）额外生成专用 short tools，其余仍走通用 `draft_add_node`。

#### 4.3.3 坐标硬约束

在 `tool_runtime` 层强制：

- `draft_add_node` / `draft_update_node` 若写入 `x`/`y`/`points`/`region` 等几何字段：  
  - 必须引用本 session 内 `locate_*` / `pack_point` 的 `ref_id`，或  
  - 必须是 `{{node_xxx.x}}` 形式的绑定，或  
  - 标记 `source: "user_override"`（仅确认 UI 写入）  
- 否则拒绝 tool 结果并返回错误给模型重试。

---

## 5. 会话与草稿模型

### 5.1 AiSession

```json
{
  "session_id": "uuid",
  "created_at": "...",
  "messages": [ { "role": "user|assistant|tool", "...": "..." } ],
  "draft": { "flow_id": "...", "name": "...", "nodes": {}, "entry": null, "variables": {} },
  "base_flow": null,
  "artifacts": {
    "shots": { "shot_1": { "path_or_ref": "...", "width": 0, "height": 0, "coord_space": {} } },
    "points": { "pt_1": { "x": 100, "y": 200, "packed": {}, "label": "登录按钮", "source": "ocr" } }
  },
  "tool_trace": [],
  "status": "idle|running|awaiting_confirm|applied|cancelled"
}
```

- `base_flow`：会话开始时的当前画布副本；支持「在现有流程上增量改」。
- `draft`：始终保持可被 `validate_flow` 校验的形状。
- 应用成功后 session 归档或关闭；不自动覆盖未确认草稿。

### 5.2 Bridge API（建议）

| 方法 | 说明 |
| ---- | ---- |
| `ai_get_config` / `ai_set_config` | 供应商、模型、是否启用 Vision、是否允许高危积木 |
| `ai_session_start` | `{ base_flow?, goal? }` → `session_id` |
| `ai_chat` | `{ session_id, message, attach_screenshot?: bool }` → 多轮直到本轮无 tool 或达上限 |
| `ai_get_draft` | 返回 draft + points 预览 |
| `ai_override_point` | 用户拖动修正点位 |
| `ai_apply_draft` | 校验通过后返回 canonical flow；前端 `setFlow` |
| `ai_cancel` | 丢弃 session |

`ai_chat` 内部循环：

```
while turn has tool_calls and steps < MAX_TOOL_STEPS:
    execute tools
    append tool results
    call LLM again
return assistant reply + draft summary + pending confirmations
```

建议 `MAX_TOOL_STEPS = 12`（可配），超时与取消与现有 stop 语义对齐（至少能打断 HTTP/LLM 等待）。

---

## 6. 取点流水线（核心）

### 6.1 OCR 路径（MVP）

```
capture_screen
  → 本地 RapidOCR（可全屏或先让模型指定大概 region）
  → locate_text_on_screen(match_text, match_mode)
  → 命中 boxes → 中心点
  → pack_point（与人工取点同一 pack_point / coord_space）
  → bind_point_to_node(node_id, pt_ref)
```

与现有积木关系：

- 运行时仍可用流程内 `ocr_recognize` + `locate_text` + `click`（更鲁棒，抗分辨率变化）。
- AI 编排时应 **优先生成「OCR→定位→点击」节点链**，而不是写死绝对坐标；  
  绝对坐标仅用于：演示、静态桌面、或用户明确要求「点这里」。

推荐策略（写入系统提示）：

1. 可复现流程 → 生成识别类节点 + 变量绑定点击  
2. 一次性点选 / 用户已给截图目标 → session 内 pack 绝对坐标并标注来源  

### 6.2 Vision 路径（二期）

```
capture_screen
  → vision model：目标描述 → bbox [x1,y1,x2,y2]（图像像素坐标）
  → 映射到虚拟桌面绝对坐标（left/top + scale）
  → pack_point / pack_region
```

注意：

- 必须使用与 `capture_desktop` 相同的坐标系（虚拟桌面，含 `coord_space`）。
- 多显示器 DPI：复用现有 `pack_point` / `window_client` 逻辑，禁止模型直接报「看起来像」的屏幕百分比除非经换算。
- 输出置信度低于阈值 → 强制用户确认或回退 OCR。

### 6.3 确认 UX

1. 展示截图缩略图 + 红色准星 / 框  
2. 列表：节点 ↔ 目标描述 ↔ 坐标来源（ocr/vision/user）  
3. 拖拽修正 → `ai_override_point`  
4. 「应用到画布」→ `ai_apply_draft`  

---

## 7. 系统提示职责边界

系统提示 **只**负责：

- 你是 Nexuz 桌面自动化编排助手  
- 必须用 tools 改草稿，禁止在回复里编造 flow JSON 当最终结果  
- 坐标规则、优先 OCR 链、少用高危积木  
- 中文回复、简要说明将添加的节点  

系统提示 **不**负责：

- 粘贴全部 SCHEMA（改由 `get_block_schema`）  
- 手写 JSON Schema 示例冒充约束  

可选：**内部 Skill（二期）** = 提示片段 + 允许 tool 子集 + 默认策略。例如 `skill.form_fill`、`skill.static_click`。MVP 用单一默认 skill 即可，不必做插件框架。

---

## 8. 安全与信任

| 风险 | 对策 |
| ---- | ---- |
| 提示注入导致乱点 | Draft + 确认；默认不自动 `run_flow` |
| 高危积木 | AI 目录默认排除 `run_command`、`python_script`、未授权 `file_io`；设置中白名单 |
| 密钥泄漏 | 仅 Python 配置存储；日志脱敏 |
| 截图隐私 | 截图仅存 session 临时目录，结束可清；不默认上传除 LLM 请求外的第三方 |
| 第三方流程 | AI 生成流仍走现有 trust / 能力清单（若已启用） |
| Tool 放大 | `MAX_TOOL_STEPS`、单 session 截图次数上限 |

与整改计划关系：Flow AI 仍建议在 Bridge 拆分 / 停止语义等 P1 项并行或稍后上线，但 **架构上必须从第一天走 Bridge**，避免再嵌一条 Vite-only 旁路。

---

## 9. 分阶段交付

### Phase 0 — 清理与接线（约 2–3 人天）

- 生产入口：设置项「启用 Flow AI」+ 顶栏按钮（不再仅 `import.meta.env.DEV`）  
- AIAssistant 改调 Bridge；删除对设计稿节点类型的依赖  
- 配置页：Provider / Model / API Key  

**验收**：无 key 时友好报错；有 key 时可多轮纯文本对话（尚可不改画布）。

### Phase 1 — Function Calling 编排（约 8–12 人天）

- `tool_catalog` + `draft_*` tools  
- `ai_chat` tool 循环  
- `validate_flow` 后预览 Diff  
- `ai_apply_draft` → `setFlow`  

**验收**：  
「先等待 1 秒，输入 hello，再点坐标 100,200」→ 生成 `delay` + `type_text` + `click`（click 坐标若无定位源则应失败并提示改用截图定位，或 Phase1 允许临时绝对坐标并标警告）。

建议 Phase1 绝对坐标：**允许但 UI 黄标「未经验证取点」**。

### Phase 2 — 截图 OCR 取点（约 10–15 人天）

- `capture_screen` / `locate_text_on_screen` / `pack_point` / `bind_point_to_node`  
- 坐标硬约束落地  
- 点位确认 UI  

**验收**：  
「点击屏幕上的『登录』」→ 截图 → OCR → 草稿 click（或 ocr→locate→click 链）→ 用户确认 → 运行命中。

### Phase 3 — 体验与策略（约 8–12 人天）

- 增量改现有画布（`base_flow`）  
- 失败自动 `get_block_schema` 重试  
- 优先生成 OCR 链而非死坐标  
- 工具轨迹面板（可调试）  

### Phase 4 — Vision（可选，约 15–25 人天）

- `locate_vision` + 坐标映射  
- 置信度与回退 OCR  
- 图标/无字按钮场景验收集  

### 通信 / MCP

- 不在本计划范围。  
- 若未来对外：将 `tool_runtime` 暴露为 MCP tools，**复用同一实现**，禁止第二套积木描述。

---

## 10. 前端改动要点

| 项 | 说明 |
| -- | ---- |
| `AIAssistant.tsx` | Bridge 会话；展示 tool 进度；建议操作改为「预览草稿」 |
| `Toolbar.tsx` | 生产可见入口（受设置开关控制） |
| 点位预览 | 新组件：截图 + markers；调用 `ai_override_point` |
| Diff | 节点增删列表；应用前确认 |
| Store | 应用时 `setFlow(canonical, path, { recordHistory: true })` |

废弃：生产路径对 `suggestNodes`（设计稿 AI/Database/HTTP subType）的依赖。

---

## 11. 测试计划

### 单元

- SCHEMA → tool JSON 快照测试（积木增删不破坏生成器）  
- `draft_builder` 连线 / 删节点边清理  
- 坐标硬约束：无 ref 写 x,y 应拒绝  
- OCR locate 在 fixtures 图上的回归  

### 集成

- mock LLM tool_calls 序列 → 得到合法 draft  
- `capture_desktop` → pack → validate  

### 手工验收场景

1. 纯文本：循环 3 次输入文本  
2. 「点击开始菜单」类（易失败）— 验证确认 UX 与失败提示  
3. 多显示器 / 缩放 125% 取点回放  
4. 无 API Key / 超时 / 取消中途  

---

## 12. 工作量汇总（1 名全栈）

| 阶段 | 人天 | 产出 |
| ---- | ---- | ---- |
| Phase 0 | 2–3 | Bridge 对话壳 + 配置 |
| Phase 1 | 8–12 | FC 编排落画布 |
| Phase 2 | 10–15 | OCR 取点 + 确认 |
| Phase 3 | 8–12 | 增量编辑与策略 |
| Phase 4 | 15–25 | Vision（可选） |
| **MVP（0–2）** | **约 20–30** | **可演示、可用的 AI 编排+取点** |

---

## 13. 决策记录（ADR 摘要）

| 决策 | 选择 | 理由 |
| ---- | ---- | ---- |
| 约束方式 | Function Calling + Schema | 比纯提示词严格，对齐注册表 |
| MCP | 不做（本期） | 同进程 tools 足够 |
| 程序内 Skill | MVP 单一默认策略；框架后置 | 避免空架构 |
| 取点 | 先 OCR，后 Vision | 复用 RapidOCR；成本与稳定性更好 |
| 写流程 | Session Draft + 确认 | 防误操作与注入 |
| LLM 位置 | Python Bridge | 密钥、截图、OS 能力同侧 |

---

## 14. 开放问题

1. 默认供应商与是否捆绑某一网关（产品决策）。  
2. 截图是否默认发给多模态模型，或仅本地 OCR（隐私开关）。  
3. AI 生成流程是否默认「OCR 链」还是「绝对坐标 + 确认」（建议：可复现场景默认 OCR 链）。  
4. 与 P1 Bridge 拆分的排期先后：AI 可先挂在 `api.py` 门面，但 tool 实现放 `core/ai/`，避免继续膨胀无法迁移。

---

## 15. 下一步

1. 评审本计划（尤其：tool 原语集合、坐标硬约束、确认 UX）。  
2. 冻结 Phase 0–2 验收用例。  
3. 开工 `backend/core/ai/` 骨架 + Bridge 方法空实现。  
4. 同步改 README「Flow AI」状态说明。
