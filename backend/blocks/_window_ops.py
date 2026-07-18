"""Shared match inputs / helpers for window_* blocks."""

from __future__ import annotations

from typing import Any

from backend.core import window_coords as wc

# title 带 window_pick UI：右侧面板用「点选 / 列表」填，不用手猜名字。
# process_name / class_name 由选取自动写入，面板里折叠为次要信息。
MATCH_INPUTS = [
    {
        "name": "title",
        "type": "string",
        "label": "目标窗口",
        "default": "",
        "placeholder": "点「选取窗口」或从列表选，不用手填",
        "ui": "window_pick",
        "bindable": True,
    },
    {
        "name": "process_name",
        "type": "string",
        "label": "进程",
        "default": "",
        "ui": "window_pick_meta",
        "bindable": True,
    },
    {
        "name": "class_name",
        "type": "string",
        "label": "类名",
        "default": "",
        "ui": "window_pick_meta",
        "bindable": True,
    },
]


def match_or_error(params: dict[str, Any]) -> tuple[int, dict[str, Any], str]:
    """Return (hwnd, describe, error). hwnd=0 on failure."""
    if not wc._supported():
        return 0, {}, "窗口操作仅支持 Windows"
    criteria = wc.criteria_from_params(params)
    if not wc.criteria_has_match_fields(criteria):
        return 0, {}, "请先选取目标窗口（点选或从列表选择）"
    hwnd = wc.find_matching_window(criteria)
    if not hwnd:
        label = (
            criteria.get("title")
            or criteria.get("process_name")
            or criteria.get("class_name")
            or "未知"
        )
        return 0, {}, f"未找到窗口：{label}"
    return hwnd, wc.describe_hwnd(hwnd), ""
