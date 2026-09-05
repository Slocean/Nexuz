"""查询监控事件：立即返回「启动监控」队列里的新事件，不等待。

配合外部客户端的定时任务周期性调用（定时唤醒 → check → 结束），或以
「等待监控事件」长轮询代替。since_event_id 传上次返回的 last_event_id。
"""

from __future__ import annotations

SCHEMA = {
    "type": "monitor_check",
    "label": "查询监控事件",
    "category": "控制类",
    "description": "非阻塞取出监控新事件；返回 last_event_id 供下次增量查询。",
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
        {"name": "status", "type": "string"},
        {"name": "error", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from backend.core.monitor import get_monitor_manager

    monitor_id = str(params.get("monitor_id") or "").strip()
    if not monitor_id:
        raise ValueError("查询监控事件需要填写 monitor_id")
    try:
        since = int(float(params.get("since_event_id") or 0))
    except (TypeError, ValueError):
        since = 0
    try:
        limit = max(1, min(20, int(float(params.get("limit") if params.get("limit") not in (None, "") else 10))))
    except (TypeError, ValueError):
        limit = 10
    return get_monitor_manager().drain_events(monitor_id, since_event_id=since, limit=limit)
