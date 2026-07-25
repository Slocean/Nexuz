# Flow AI 验收集

路径：`backend/testdata/ai_eval/cases.json`  
运行：

```bash
python -c "from backend.core.ai.eval_runner import run_eval_suite; print(run_eval_suite())"
pytest backend/test_ai_eval.py -q
```

Bridge（设置页）：`ai_run_eval`。

## 规则

- mock / 启发式模式：≥60 条时通过率 ≥85%；小集 ≥90%
- 含点击的用例禁止裸坐标；应出现 OCR / 找图 / 取色 + `click` 绑定
- 微信北极星与澄清用例见 `wechat_*` / `expect_clarify`

## 手工核心场景（本机 10 条）

1. 等待 1 秒，输入 hello → apply 能跑  
2. 点击「登录」文字 → OCR 链，无裸坐标  
3. 输入后回车  
4. 找图点击模板（有模板图时）  
5. 按颜色点击（可控色块）  
6. 激活微信窗口后输入  
7. 定时 + delay + type  
8. 如果出现「确定」→ if 节点  
9. 循环 3 次  
10. 「明天 9 点给王哥发微信消息「…」」→ 澄清（如需）→ 完整草稿 → apply  

详见 [`AGENT_PLATFORM.md`](./AGENT_PLATFORM.md)。
