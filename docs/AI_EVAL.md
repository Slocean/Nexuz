# Flow AI 验收集

路径：`backend/testdata/ai_eval/cases.json`  

这些 JSON **只用于自动化回归测试**，不是产品里写死的「唯一能跑的流程」。  
换你自己的话术（任意联系人、任意消息）照样走规划 → 技能展开。

运行：

```bash
python -c "from backend.core.ai.eval_runner import run_eval_suite; print(run_eval_suite())"
pytest backend/test_ai_eval.py -q
```

Bridge：`ai_run_eval`。

## 规则

- mock / 启发式：≥60 条时通过率 ≥85%
- 点击类禁止裸坐标；应 OCR/找图/取色 + 绑定
- 发消息类：参数必须从 utterance 提取；缺参应 `expect_clarify`，禁止默认虚构联系人/文案

## 手工核心场景（本机）

1. 等待 1 秒，输入任意文本 → apply 能跑  
2. 点击屏幕上某段文字 → OCR 链  
3. 输入后回车  
4. 找图点击（自备模板路径）  
5. 按颜色点击（给出色值）  
6. 激活某窗口后输入  
7. 定时 + delay + type  
8. 如果出现某文字 → if  
9. 循环 N 次  
10. 「定时/立刻用某 IM 给某人发某句话」→ 缺参才澄清 → 草稿 → apply  
