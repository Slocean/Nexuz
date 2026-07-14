from __future__ import annotations

SCHEMA = {
    "type": "schedule_trigger",
    "label": "注册定时任务",
    "category": "控制类",
    "description": "仅注册/更新定时任务，不会在此节点等待到点再继续。实际执行由调度器触发整条流程。",
    "inputs": [
        {
            "name": "trigger_type",
            "type": "select",
            "label": "触发类型",
            "options": ["interval", "once", "cron"],
            "default": "interval",
            "option_labels": {
                "interval": "周期",
                "once": "单次",
                "cron": "Cron",
            },
        },
        {
            "name": "interval_seconds",
            "type": "number",
            "label": "周期秒数",
            "default": 60,
            "show_when": {"trigger_type": "interval"},
        },
        {
            "name": "run_at",
            "type": "string",
            "label": "单次时间",
            "placeholder": "2026-07-12 10:00:00",
            "default": "",
            "show_when": {"trigger_type": "once"},
        },
        {
            "name": "cron_expression",
            "type": "string",
            "label": "Cron",
            "default": "0 * * * *",
            "placeholder": "分 时 日 月 周",
            "show_when": {"trigger_type": "cron"},
        },
        {
            "name": "enabled",
            "type": "select",
            "label": "启用",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {"true": "启用", "false": "禁用"},
        },
    ],
    "outputs": [
        {"name": "registered", "type": "boolean"},
        {"name": "job_id", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    """
    When executed as a normal node: register/update a schedule for the *current* flow.
    Actual firing is managed by backend.core.scheduler (APScheduler).
    """
    from backend.core.scheduler import get_scheduler

    flow = kwargs.get("flow") or {}
    node_id = kwargs.get("node_id") or "schedule"
    enabled = str(params.get("enabled", "true")).lower() != "false"
    sched = get_scheduler()
    job_id = f"flow:{flow.get('flow_id', 'unknown')}:{node_id}"

    if not enabled:
        sched.remove_job(job_id)
        return {"registered": False, "job_id": job_id}

    # Persist flow snapshot path hint in job kwargs — caller should save first
    file_path = context.get("__flow_file_path__") or flow.get("__file_path__")
    sched.register_flow_job(
        job_id=job_id,
        flow=flow,
        file_path=file_path,
        trigger_type=str(params.get("trigger_type") or "interval"),
        interval_seconds=float(params.get("interval_seconds") or 60),
        run_at=str(params.get("run_at") or ""),
        cron_expression=str(params.get("cron_expression") or "0 * * * *"),
    )
    return {"registered": True, "job_id": job_id}
