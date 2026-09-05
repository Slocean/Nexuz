"""等待监控事件（长轮询唤醒）：阻塞到「启动监控」产生新事件或超时。

这是外部 AI 的「唤醒点」：run_block 调用会挂起在这里，条件一满足调用立即
返回事件内容，等效被监控唤醒。单次最长 60 秒（超时返回 timed_out=true，
带着 last_event_id 继续下一次等待即可）；流程内可放循环里长期监听，
停止按钮随时可中断。since_event_id 传上次返回的 last_event_id 实现增量取件。
"""

from __future__ import annotations

_MAX_WAIT_MS = 60_000.0

SCHEMA = {
    "type": "monitor_wait",
    "label": "等待监控事件",
    "category": "控制类",
    "description": "阻塞等待监控新事件（长轮询，单次上限 60 秒）；返回 last_event_id 供下次增量。",
    "inputs": [
        {
            "name": "monitor_id",
            "type": "string",
            "label": "监控 ID",
            "required": True,
            "default": "",
            "placeholder": "「启动监控」返回的 monitor_id",
            "bindable": True,
        },
        {
            "name": "timeout_ms",
            "type": "number",
            "label": "等待毫秒",
            "default": 30000,
            "placeholder": "上限 60000，超时后重试即可",
        },
        {
            "name": "since_event_id",
            "type": "number",
            "label": "事件游标",
            "default": 0,
            "placeholder": "传上次返回的 last_event_id，0=从头",
            "bindable": True,
        },
        {
            "name": "limit",
            "type": "number",
            "label": "最多返回条数",
            "default": 10,
            "placeholder": "上限 20",
        },
    ],
    "outputs": [
        {"name": "got", "type": "boolean"},
        {"name": "count", "type": "number"},
        {"name": "last_event_id", "type": "number"},
        {
            "name": "events",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {
                "id": "number",
                "ts": "number",
                "ts_text": "string",
                "type": "string",
                "fire": "string",
                "detail": "string",
                "data": "object",
            },
        },
        {"name": "timed_out", "type": "boolean"},
        {"name": "status", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, should_stop=None, cooperate=None, **kwargs):
    from backend.core.monitor import get_monitor_manager

    monitor_id = str(params.get("monitor_id") or "").strip()
    if not monitor_id:
        raise ValueError("等待监控事件需要填写 monitor_id")
    try:
        timeout_ms = float(params.get("timeout_ms") if params.get("timeout_ms") not in (None, "") else 30000)
    except (TypeError, ValueError):
        timeout_ms = 30000.0
    timeout_ms = min(max(timeout_ms, 0.0), _MAX_WAIT_MS)
    try:
        limit = max(1, min(20, int(float(params.get("limit") if params.get("limit") not in (None, "") else 10))))
    except (TypeError, ValueError):
        limit = 10
    try:
        since = int(float(params.get("since_event_id") or 0))
    except (TypeError, ValueError):
        since = 0

    res = get_monitor_manager().wait_events(
        monitor_id,
        since_event_id=since,
        timeout_s=timeout_ms / 1000.0,
        limit=limit,
        should_stop=should_stop,
        cooperate=cooperate,
    )
    res.setdefault("timed_out", False)
    return res
