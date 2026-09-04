---
name: nexuz-mcp
description: 通过 Nexuz MCP 操作 Windows 桌面自动化与图片处理。当用户提到 Nexuz、nexuz MCP、用积木/流程做桌面自动化（点击、按键、截图、OCR 找字、取色、窗口操作）、图片批处理（缩放/抠图/切图/重命名/生图）、或要运行与编排 Nexuz 流程时使用——即使用户没有明说"MCP"二字。
---

# Nexuz MCP 使用指南

Nexuz 是 Windows 桌面自动化平台：把"积木"（点击/按键/截图/OCR/找图/文件/图片处理等）编排成流程执行。nexuz MCP 把这些能力开放给你（外部 AI 代理）。执行发生在正在运行的 Nexuz 应用内；应用未启动时首次调用会自动唤醒（最长等 40 秒，失败可重试一次）。

## 标准调用顺序

1. `get_status` — 确认服务在线（返回版本、是否正在执行流程）。
2. `list_blocks` — 看有哪些积木可执行，可按 category 过滤（动作类/识别类/浏览器/系统类等）。
3. `get_block_schema` 传 `type` — 拿到单个积木的完整 inputs/outputs，据此填写 params。**先查 schema 再调用，不要凭猜测填参数。**
4. `run_block`（单个积木）或 `run_flow`（整条流程）执行。

## 执行边界（不要尝试绕过）

- 除下方拒绝清单外，**所有积木直接执行即可**，无需任何开关或用户配置：桌面动作（click/key_press/type_text 等）、文件与网络（file_io/file_manage/http_request 等）、图片处理（image_scale/transparent_cut/sprite_sheet_cut/sprite_part_cut/image_rename/image_generate）、浏览器（browser_*）、系统类（env_var/open_path/process_kill 等）、只读观察类（screenshot/ocr_recognize/find_image 等）。
- **始终拒绝**：`python_script`、`run_command`、`power_action`、控制流积木（if_* / loop_* / switch / try_catch）、用户自定义积木。被拒时直接告知用户"Nexuz 不允许外部 AI 执行该积木"，**不要换姿势重试**——没有绕过路径，重试只会浪费时间。
- `run_flow`（内联 JSON 或流程库文件）有内容闸：流程内含上述危险积木时整体拒绝（子流程嵌套、定时任务再触发同样被拦截）。流程自身声明的 safe/standard 执行策略也仍然生效。
- 所有调用写入审计日志（按日分文件），把每次调用当成"用户事后会逐条查看"来约束：只做用户要求的事，不做顺手多做的事。

## 坐标纪律（最重要）

**禁止臆造坐标。** 屏幕坐标只能来自真实截图：

1. `capture_screen` → 返回截图图像 + `shot_ref` + 尺寸与坐标空间。
2. 在截图上定位目标：直接视觉读图，或用 `locate_text_on_screen` 传 `match_text`（可选 `shot_ref`）做 OCR 找字，返回目标中心点 x/y。
3. 把拿到的 x/y 传给 click / mouse_hover / drag 等积木。

```
locate_text_on_screen {"match_text": "设置", "shot_ref": "<capture_screen 返回的>"}
→ {"ok": true, "found": true, "x": 512, "y": 300, "point_ref": "..."}
```

同一张截图找多个目标时复用 `shot_ref`，不要重复截屏。

## 响应结构（run_block）

外层 `ok` 只表示"积木是否被执行"，**业务成败与真实输出在嵌套的 `result` 字段里**，判断结果要看 `result`：

```json
{
  "ok": true,                // 执行状态（handler 是否跑完）
  "type": "file_manage",
  "node_id": "ai_run_1",
  "result": {
    "ok": false,             // 业务成败（如"不是文件夹"、目标已存在）
    "error": "不是文件夹或不存在: D:\\nexuz\\nexuz",
    "output": "", "count": 0, "items": []
  }
}
```

外层 `ok: true` + `result.ok: false` 是"执行成功但业务失败"，不是 Nexuz 故障；按 `result.error` 修正参数重试即可。后续调用绑定时用积木输出名：`{{ai_run_1.output}}`（不带 result 前缀）。

## 路径纪律

- Windows 路径必须用**绝对路径**，且 JSON 中反斜杠**必须双写**：`"D:\\\\nexuz"`。单写 `"D:\\nexuz"` 会把 `\\n` 变成换行符、丢成 `D:nexuz`，这类路径会被直接拒绝并提示修正写法。
- 相对路径会按应用工作目录解析，结果不可预期——不要用。

## 会话变量与绑定

`run_block` 的输出按 `{{ai_run_N.输出名}}` 写入会话上下文（N 是本次会话内第几次 run_block 调用，从 1 起），后续调用可直接绑定引用：

```
run_block 第 1 次: ocr_recognize {...}        → 输出 x/y/found
run_block 第 2 次: click {"x": "{{ai_run_1.x}}", "y": "{{ai_run_1.y}}"}
```

`reset_session` 清空该上下文；会话很长、变量可能很大时主动清理。

## 等待与超时

- delay / wait_until 等等待参数单次上限 60 秒（超出自动钳制），单次积木执行上限 90 秒。要等更久就多次 `wait_until` 轮询，不要一次传大值。
- `run_flow` 默认 `wait: true` 阻塞等结果（`timeout_s` 默认 300）；返回 `timed_out: true` 表示流程仍在运行，此时用 `flow_control {"action": "stop"}` 急停止损，或再次 `get_status` 观察。

## run_block 与 run_flow 怎么选

- 1–3 步的即时操作 → `run_block` 逐步执行，中间读结果再调整下一步。
- 固定管线（如"一批图片统一缩放 + 重命名"）→ `run_flow` 一次执行：库内流程先用 `list_flows` 查路径再传 `flow_path`；临时编排可直接内联 flow JSON（结构同画布导出的 .flow.json）。
