"""监控列表：列出当前后台监控的状态与最近事件。

应用重启后监控规格自动恢复但事件清空，外部 AI 可先调本积木找回 monitor_id
再决定重新「启动监控」还是直接增量查询。"""

from __future__ import annotations

SCHEMA = {
    "type": "monitor_list",
    "label": "监控列表",
    "category": "控制类",
    "description": "列出后台监控：状态/条件摘要/事件数/最近事件/错误。",
    "inputs": [],
    "outputs": [
        {"name": "count", "type": "number"},
        {
            "name": "monitors",
            "type": "array",
            "itemType": "object",
            "canvas": False,
            "fields": {
                "monitor_id": "string",
                "monitor_type": "string",
                "spec": "string",
                "status": "string",
                "origin": "string",
                "created_at_text": "string",
                "poll_interval_ms": "number",
                "refire_ms": "number",
                "expire_seconds": "number",
                "check_count": "number",
                "event_count": "number",
                "last_event_id": "number",
                "last_event_text": "string",
                "last_error": "string",
            },
        },
    ],
}


def handler(params, context, **kwargs):
    from backend.core.monitor import get_monitor_manager

    monitors = get_monitor_manager().list_monitors()
    return {"count": len(monitors), "monitors": monitors}
