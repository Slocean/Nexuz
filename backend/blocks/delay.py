from __future__ import annotations

from backend.blocks._helpers import interruptible_sleep

SCHEMA = {
    "type": "delay",
    "label": "延时",
    "category": "动作类",
    "inputs": [
        {"name": "ms", "type": "number", "label": "毫秒", "default": 500},
    ],
    "outputs": [],
}


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    ms = int(params.get("ms", 0) or 0)
    if ms < 0:
        raise ValueError("延时不能为负数")
    interruptible_sleep(ms / 1000.0, should_stop, cooperate=cooperate)
    return {}
