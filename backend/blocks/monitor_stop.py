"""停止监控：停掉后台检查线程并删除该监控（事件队列一并丢弃）。

需要剩余事件请先「查询监控事件」，再停止。"""

from __future__ import annotations

SCHEMA = {
    "type": "monitor_stop",
    "label": "停止监控",
    "category": "控制类",
    "description": "停止并删除监控；先「查询监控事件」取走剩余事件再停。",
    "inputs": [
        {
            "name": "monitor_id",
            "type": "string",
            "label": "监控 ID",
            "required": True,
            "default": "",
            "bindable": True,
        },
    ],
    "outputs": [
        {"name": "stopped", "type": "boolean"},
        {"name": "monitor_id", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from backend.core.monitor import get_monitor_manager

    monitor_id = str(params.get("monitor_id") or "").strip()
    if not monitor_id:
        raise ValueError("停止监控需要填写 monitor_id")
    if not get_monitor_manager().stop_monitor(monitor_id):
        raise ValueError(f"监控不存在: {monitor_id}（可 monitor_list 查看现存监控）")
    return {"stopped": True, "monitor_id": monitor_id}
