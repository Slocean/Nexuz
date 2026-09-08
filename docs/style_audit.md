# 样式审计（style_audit）设计文档

> 目标：agent 传入一张截图（或贴图），得到一份**确定性测量报告**——哪里疑似有样式问题、
> 证据是什么、置信度如何；最终判断由 agent 复核后做出。

## 1. 背景与定位

UI 样式问题（文字被裁剪、文字超出背景素材、元素互相遮挡、对比度过低）的本质是
「渲染结果 ≠ 设计意图」。纯像素分析只能看到渲染结果，因此本功能按信息来源划清可靠性边界：

| 信息来源 | 能检测什么 | 可靠性 |
| --- | --- | --- |
| 纯截图（像素 + OCR） | 贴边裁剪、超出内容区、元素重叠、对比度量化 | 中高，存在误报，需 agent 复核 |
| DOM（网页） | 文字溢出/截断/隐藏/遮挡，零误报 | 确定性，但需要浏览器上下文，**不在本仓库范围**（浏览器侧由接入方项目自行处理，如 RWT 的 browser_eval） |
| 预期参照（设计稿/预期文案清单） | 文字缺失/隐藏 | 需要参照物，v2 预留 |

**产品原则：工具负责测量和取证，结论由 agent 复核后下。** 本积木只输出
「问题类型 + 坐标 + 数字证据 + 置信度」，不做 VLM 调用，不做"合格/不合格"二值判断。

## 2. 架构

```
backend/blocks/_style_audit.py   # 测量核心：进 PIL 图 + OCR 词框，出 JSON 报告（纯函数，无桌面副作用）
backend/blocks/style_audit.py    # 积木壳：SCHEMA + handler（加载图片 / 内置 OCR / 派发检查）
backend/core/ai/run_block.py     # RUN_BLOCK_SAFE 白名单注册（外部 AI 可经 MCP run_block 执行）
```

三层分工：

1. **采集**（已有能力）：`screenshot` 积木出图文件 → 输出 `path`；
2. **测量**（本功能）：`style_audit` 积木——内置 OCR（复用 `ocr_recognize` 的
   `_prepare_ocr_image` / `_infer_ocr` 链路）或接受外部传入词框，然后跑确定性检查；
3. **判断**（agent）：拿 issues + 标注图复核，可选 `locate_text` 比对预期文案
   （「文字被隐藏」类问题在 v1 的推荐玩法：agent 先列预期文案，再用 OCR 逐条确认）。

## 3. 检查项（v1）

| 检查项 | type | 算法口径 | 置信度 |
| --- | --- | --- | --- |
| 文字框超出画布 | `text_out_of_canvas` | 文字框任一边超出图像边界超过 `margin_px` | 高 |
| 文字框贴边 | `text_edge_flush` | 文字框与画布边缘距离 ≤ `margin_px`（默认 2px）且未超出 | 中（可能是刻意满铺） |
| 文字互相遮挡 | `text_overlap` | 两文字框相交面积 / 较小框面积 > 0.35 | 中高 |
| 文字对比度过低 | `text_low_contrast` | 框内 Otsu 二分 → 前景/背景两组平均色的 WCAG 对比度 < `contrast_threshold`（默认 4.5；< 2.5 判 error） | 中（受抗锯齿、贴图纹理干扰） |

**v1 明确不做**（要么不可靠要么越界）：

- 「文字被隐藏/丢失」——隐藏即无像素，纯截图原理上不可检；用 agent + 预期文案清单工作流替代；
- 渐变/字体/圆角等"视觉理解"型输出；
- 背景素材边界的自动分割（`text_edge_flush` 覆盖其大部分高价值场景）；
- VLM 调用、批量处理（批量交给流程编排 loop_foreach）。

## 4. 积木参数与输出

`type: style_audit`，分类「识别类」，`RUN_BLOCK_SAFE`（外部 AI 无需危险开关即可执行）。

输入：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `image_path` | string | 必填 | 截图/贴图文件路径（推荐绑定 `screenshot` 积木的 `path` 输出） |
| `text_source` | select | `auto` | `auto`=内置 OCR；`custom`=用 `text_boxes` 传入（跳过 OCR）；`none`=跳过全部文字类检查 |
| `text_boxes` | string | — | `custom` 时必填，JSON 数组 `[{text,left,top,width,height,...}]`（同 `ocr_recognize` 的 boxes 结构） |
| `origin_x`/`origin_y` | number | 0 | 图像左上角在屏幕上的坐标；输出坐标换算成屏幕绝对值，方便 agent 直接用于点击 |
| `min_confidence` | number | 0.3 | 内置 OCR 置信度下限 |
| `checks` | string | 全部 | 逗号分隔启用检查项，未知项报错 |
| `margin_px` | number | 2 | 贴边判定容差 |
| `contrast_threshold` | number | 4.5 | WCAG 对比度阈值 |
| `palette_size` | number | 6 | 主色数量，0 = 跳过配色提取 |
| `save_report` | string | — | 可选，JSON 报告落盘路径 |
| `annotate_path` | string | — | 可选，标注图（问题框红/橙/黄按严重度着色）落盘路径 |

输出：

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| `ok` / `issue_count` / `text_count` | boolean / number | 基本计数 |
| `issues` | array | `{type, severity(high/medium/info), message, text, left, top, width, height, detail}` |
| `palette` | object | `{colors:[{hex,rgb,ratio}], background}`，`background` 为边框环主色（透明画布为 null） |
| `image` | object | `{path, width, height}` |
| `report_path` / `annotated_path` | string | 落盘路径（未请求则为空） |

坐标口径：issues 中的 `left/top` 已加 `origin_x/origin_y`（屏幕绝对坐标）；
`image.width/height` 与框尺寸为图像本地像素。

## 5. 使用链路

**MCP / 对话内（推荐两跳）：**

```
run_block {type:"screenshot", params:{region:[x1,y1,x2,y2]}}   → result.path
run_block {type:"style_audit", params:{image_path:"{{ai_run_1.path}}", origin_x:x1, origin_y:y1}}
```

**应用内流程：** `screenshot → style_audit → if_condition(issue_count > 0) → notify`。

**agent 复核建议：** 读取 `annotated_path` 标注图目检；对「文字被隐藏」类问题，
用 `locate_text`/`ocr_recognize` 逐条确认预期文案是否出现。

## 6. 路线图（v2 方向，未实施）

- 预期文案清单输入 `expected_texts`：OCR 未命中 → `text_missing`（信息级，需复核）；
- 背景素材边界分割（九切片/圆角卡检测），把「文字超出背景素材」做成独立高置信检查；
- 精灵帧一致性检查与页面渲染回归（依赖切分/回归积木的编排组合）；
- DOM-grounded 审计：需要浏览器上下文，归接入方项目的浏览器工具（`browser_eval`）承担，
  Nexuz 侧仅消费其产出的证据包。
