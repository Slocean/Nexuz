"""启动后台监控：注册一个条件监视器，条件满足时产生事件（不阻塞）。

监控在应用后台线程按 poll_interval_ms 轮询条件，事件进入该监控的内存队列。
谁来消费由调用方决定：外部 AI 用「等待监控事件」长轮询（事件一出现调用即
返回，等效被唤醒），或「查询监控事件」非阻塞取件；流程内可先启动再在循环里
取，实现边执行边监听。监控规格随应用重启自动恢复（事件历史不保留）。
"""

from __future__ import annotations

from typing import Any

from backend.blocks._ocr_match import match_policy_inputs
from backend.blocks._window_ops import MATCH_INPUTS

# 管理器级参数：从积木入参里拆出来构成监控规格，其余全部作为条件参数透传。
_SPEC_KEYS = (
    "monitor_type",
    "poll_interval_ms",
    "refire_ms",
    "fire_on_start",
    "expire_seconds",
    "max_events",
    "toast",
)

_WINDOW_INPUTS = [dict(inp, show_when={"monitor_type": "window"}) for inp in MATCH_INPUTS]

SCHEMA = {
    "type": "monitor_start",
    "label": "启动监控",
    "category": "控制类",
    "description": "后台监控条件（进程/窗口/文件/屏幕），出现事件记入队列；本节点立即返回，配合「等待/查询监控事件」取件。",
    "inputs": [
        {
            "name": "monitor_id",
            "type": "string",
            "label": "监控 ID",
            "default": "",
            "placeholder": "留空自动生成；等待/查询事件时要用它",
        },
        {
            "name": "monitor_type",
            "type": "select",
            "label": "监控类型",
            "options": ["process", "window", "file", "screen_text", "screen_color"],
            "default": "process",
            "option_labels": {
                "process": "进程状态",
                "window": "窗口出现/关闭",
                "file": "文件变化",
                "screen_text": "屏幕文字",
                "screen_color": "屏幕颜色",
            },
        },
        {
            "name": "on",
            "type": "select",
            "label": "触发时机",
            "options": ["appear", "disappear", "change"],
            "default": "appear",
            "option_labels": {
                "appear": "出现/开始",
                "disappear": "消失/结束",
                "change": "内容变化",
            },
        },
        {
            "name": "process_name",
            "type": "string",
            "label": "进程名",
            "default": "",
            "placeholder": "如 zcode.exe / Code.exe（子串匹配）",
            "bindable": True,
            "show_when": {"monitor_type": "process"},
        },
        {
            "name": "pid",
            "type": "number",
            "label": "PID",
            "default": 0,
            "placeholder": "可选，优先于进程名",
            "bindable": True,
            "show_when": {"monitor_type": "process"},
        },
        *_WINDOW_INPUTS,
        {
            "name": "file_path",
            "type": "string",
            "label": "文件路径",
            "default": "",
            "placeholder": "绝对路径",
            "bindable": True,
            "show_when": {"monitor_type": "file"},
        },
        {
            "name": "expect_text",
            "type": "string",
            "label": "期望文字",
            "default": "",
            "bindable": True,
            "show_when": {"monitor_type": "screen_text"},
        },
        *match_policy_inputs(show_when={"monitor_type": "screen_text"}),
        {
            "name": "region",
            "type": "rect",
            "label": "检测区域",
            "default": None,
            "show_when": {"monitor_type": ["screen_text", "screen_color"]},
        },
        {
            "name": "color_sample",
            "type": "select",
            "label": "颜色取样",
            "options": ["region", "point"],
            "default": "region",
            "option_labels": {"region": "区域", "point": "单点"},
            "show_when": {"monitor_type": "screen_color"},
        },
        {
            "name": "x",
            "type": "number",
            "label": "单点 X",
            "default": 0,
            "show_when": {"monitor_type": "screen_color", "color_sample": "point"},
        },
        {
            "name": "y",
            "type": "number",
            "label": "单点 Y",
            "default": 0,
            "show_when": {"monitor_type": "screen_color", "color_sample": "point"},
        },
        {
            "name": "target_color",
            "type": "color",
            "label": "目标颜色",
            "default": "#FF0000",
            "show_when": {"monitor_type": "screen_color"},
        },
        {
            "name": "tolerance",
            "type": "number",
            "label": "颜色容差",
            "default": 20,
            "show_when": {"monitor_type": "screen_color"},
        },
        {
            "name": "poll_interval_ms",
            "type": "number",
            "label": "轮询间隔毫秒",
            "default": 1000,
            "placeholder": "最小 250；屏幕文字用 OCR，建议 ≥1000",
        },
        {
            "name": "refire_ms",
            "type": "number",
            "label": "持续重复间隔毫秒",
            "default": 0,
            "placeholder": "0 = 仅状态翻转时记一次事件",
        },
        {
            "name": "fire_on_start",
            "type": "select",
            "label": "启动时已满足",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "不记事件", "true": "立即记一次"},
        },
        {
            "name": "expire_seconds",
            "type": "number",
            "label": "自动过期秒",
            "default": 3600,
            "placeholder": "0 = 不过期",
        },
        {
            "name": "max_events",
            "type": "number",
            "label": "事件队列上限",
            "default": 100,
            "placeholder": "超出丢最旧，上限 500",
        },
        {
            "name": "toast",
            "type": "select",
            "label": "事件弹窗提醒",
            "options": ["false", "true"],
            "default": "false",
            "option_labels": {"false": "否", "true": "是（Windows 通知）"},
        },
    ],
    "outputs": [
        {"name": "monitor_id", "type": "string"},
        {"name": "started", "type": "boolean"},
        {"name": "status", "type": "string"},
        {"name": "spec", "type": "string"},
    ],
}


def handler(params, context, **kwargs):
    from backend.core.monitor import get_monitor_manager

    p: dict[str, Any] = dict(params if isinstance(params, dict) else {})
    monitor_id = str(p.pop("monitor_id", "") or "")
    spec: dict[str, Any] = {key: p.pop(key, None) for key in _SPEC_KEYS}
    spec["params"] = p  # 剩余入参全部作为条件参数（on/进程名/区域/颜色…）
    flow = kwargs.get("flow") if isinstance(kwargs.get("flow"), dict) else {}
    origin = str(flow.get("__run_origin__") or "")
    res = get_monitor_manager().start_monitor(spec, monitor_id=monitor_id, origin=origin)
    return {
        "monitor_id": res["monitor_id"],
        "started": True,
        "status": res.get("status", "running"),
        "spec": res.get("spec", ""),
    }
