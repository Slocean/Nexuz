# Nexuz Agent 平台（路线 B）

自然语言 → 技能/配方 → 可校验 Flow 草稿 → 用户确认 → 执行引擎。

**不是**：模型微调；不是多租户 Agent 云；不是微信官方 API。

## 必达：感知双通路

| 通路 | 条件 | 行为 |
| ---- | ---- | ---- |
| A 多模态 | 模型支持看图（`supports_vision` / 模型名推断） | 截图 → `locate_on_screenshot_vision` → `point_ref`；失败降 OCR |
| B 纯文本 | 仅语言模型 | 编排 `ocr_recognize` / `find_image` / `color_detect` → `click` 绑定 `{{node.x/y}}` |

禁止无来源裸坐标（`strict_coords=True`）。设置页「测试连接」会探测结构化输出与是否多模态。

## 技能包

目录：`backend/core/ai/skills/packs/<id>/skill.json`

内置：`text_click`、`type_submit`、`wait_then_act`、`find_image_click`、`color_click`、`window_focus`、`schedule_at`、`if_text`、`loop_n`、`wechat_send_message`。

禁用：设置「Agent 平台」勾选，或 API `ai_set_skill_enabled`。  
高危积木默认拒绝；勾选「允许高危积木」后才可 draft。

## 澄清（HITL）

缺参 / 多候选 / 定位失败 → `status=needs_clarify` + `clarify_questions`。  
编排卡片展示选项；作答后继续 `aiChat`。

## 验收集 / 审计

- 评测：[`AI_EVAL.md`](./AI_EVAL.md)，设置页「跑评测集」，API `ai_run_eval`
- 审计：`{data_dir}/ai/audit/YYYY-MM-DD.jsonl`，API `ai_list_audit`

## 北极星

「xx 点给王哥发微信」→ 技能 `wechat_send_message`：

定时 → 激活微信 → OCR 点联系人 → 输入 → 点发送  

多「王哥」或未写消息内容时先澄清。微信 UI 变更时改技能包，不必改 Graph 拓扑。

## 扩展技能

1. 新建 `packs/my_skill/skill.json`（`id` / `recipe` / `description`）  
2. 若需新展开逻辑，在 `graphs/recipes.py` 增加 `_recipe_*`  
3. 补 `testdata/ai_eval/cases.json` 后跑 `pytest backend/test_ai_eval.py`

## Done（路线 B）

1. 安全积木有 AI 描述卡；高危默认不可用  
2. 感知双通路 A/B 均具备；无来源坐标拒绝  
3. mock 评测 ≥60 条、通过率 ≥85%  
4. 可从零生成短/中流程，也可增量改画布（`base_flow`）  
5. 缺参/多候选必须澄清  
6. 微信定时发消息骨架可演示（本机已登录微信）  
7. apply 前确认；审计可查  
8. 加技能 = 加包 + 测试  
9. 无微调依赖  

## 诚实边界

- 不能保证微信改版后零维护  
- 本地小模型多模态质量参差  
- 纯文本通路需关键字/模板可定位  
