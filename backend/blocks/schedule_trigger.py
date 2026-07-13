from __future__ import annotations

SCHEMA = {
    "type": "schedule_trigger",
    "label": "定时触发",
    "category": "控制类",
    "inputs": [
        {
            "name": "trigger_type",
            "type": "select",
            "label": "触发类型",
            "options": ["interval", "once", "cron"],
            "default": "interval",
        },
        {
            "name": "interval_seconds",
            "type": "number",
            "label": "周期秒数(interval)",
            "default": 60,
        },
        {
            "name": "run_at",
            "type": "string",
            "label": "单次时间(once)",
            "placeholder": "如 2026-07-12 10:00:00",
            "default": "",
        },
        {
            "name": "cron_expression",
            "type": "string",
            "label": "Cron(分 时 日 月 周)",
            "default": "0 * * * *",
        },
        {
            "name": "enabled",
            "type": "select",
            "label": "启用",
            "options": ["true", "false"],
            "default": "true",
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
