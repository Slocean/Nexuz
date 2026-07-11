from __future__ import annotations

SCHEMA = {
    "type": "loop_forever",
    "label": "无限循环",
    "category": "控制类",
    "inputs": [
        {"name": "exit_condition", "type": "string", "label": "退出条件(可选)", "default": ""},
        {"name": "check_interval_ms", "type": "number", "label": "每轮间隔(ms)", "default": 200},
        {"name": "max_times", "type": "number", "label": "安全最大次数", "default": 1000000},
    ],
    "outputs": [],
}


def handler(params, context, **kwargs):
    return {}
