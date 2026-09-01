"""AI-friendly block cards (description + hints) over BLOCK_REGISTRY."""

from __future__ import annotations

from typing import Any

from backend.core.ai.tool_catalog import is_block_allowed, list_blocks
from backend.core.registry import get_schemas

# Extra hints when SCHEMA.description is empty / thin.
_AI_HINTS: dict[str, dict[str, Any]] = {
    "delay": {
        "description": "等待指定毫秒后继续",
        "key_params": ["ms"],
        "ai_hints": "延时用 ms；勿与 wait_until 混淆",
    },
    "type_text": {
        "description": "键盘输入文本",
        "key_params": ["text"],
        "ai_hints": "params.text 为要输入的内容",
    },
    "key_press": {
        "description": "按下键盘按键或组合键",
        "key_params": ["keys", "key_mode"],
        "ai_hints": "单键用 key_mode=single, keys=['enter']",
    },
    "click": {
        "description": "鼠标点击；坐标必须绑定或 point_ref",
        "key_params": ["x", "y", "coordinate_mode"],
        "ai_hints": "禁止裸数字坐标；用 {{ocr.x}} 或 point_ref",
    },
    "ocr_recognize": {
        "description": "截屏/区域 OCR，可按 match_text 输出坐标",
        "key_params": ["match_text", "region"],
        "ai_hints": "可复现点击：ocr_recognize→click 绑定 x/y",
    },
    "locate_text": {
        "description": "在 OCR 结果中定位文字",
        "key_params": ["match_text"],
        "ai_hints": "常接在 ocr_recognize 后",
    },
    "find_image": {
        "description": "模板图匹配定位",
        "key_params": ["path"],
        "ai_hints": "输出 x/y 供 click 绑定；适合图标",
    },
    "color_detect": {
        "description": "检测颜色并输出位置",
        "key_params": ["target_color", "region"],
        "ai_hints": "纯文本模型可用取色定位",
    },
    "screenshot": {
        "description": "截取屏幕或区域为图片",
        "key_params": ["region"],
        "ai_hints": "多模态/OCR 链路的上游节点",
    },
    "wait_until": {
        "description": "等待文字/颜色/表达式出现",
        "key_params": ["wait_type", "expect_text", "timeout_ms"],
        "ai_hints": "等文字用 wait_type=text + expect_text",
    },
    "window_activate": {
        "description": "激活匹配的窗口",
        "key_params": ["title"],
        "ai_hints": "title 可用包含匹配字符串",
    },
    "window_wait": {
        "description": "等待窗口出现",
        "key_params": ["title"],
        "ai_hints": "与 window_activate 配合",
    },
    "schedule_trigger": {
        "description": "注册定时触发（不阻塞等待）",
        "key_params": ["trigger_type", "run_at", "cron_expression"],
        "ai_hints": "单次用 once+run_at；每天用 cron",
    },
    "if_condition": {
        "description": "条件分支 then/else",
        "key_params": ["expression"],
        "ai_hints": "连接 then/else 边",
    },
    "if_text_contains": {
        "description": "文本包含判断分支",
        "key_params": ["text", "contains"],
        "ai_hints": "适合 OCR 结果分支",
    },
    "loop_n": {
        "description": "固定次数循环",
        "key_params": ["count"],
        "ai_hints": "body 边指向循环体",
    },
    "try_catch": {
        "description": "异常捕获 body/catch/finally",
        "key_params": [],
        "ai_hints": "包裹易失败的 UI 段",
    },
    "mouse_hover": {"description": "鼠标悬停", "key_params": ["x", "y"]},
    "mouse_scroll": {"description": "滚轮滚动", "key_params": ["clicks"]},
    "drag": {"description": "拖拽", "key_params": ["from_x", "from_y", "to_x", "to_y"]},
    "clipboard": {"description": "剪贴板读写", "key_params": ["action", "text"]},
    "notify": {"description": "系统通知", "key_params": ["title", "message"]},
    "assign": {"description": "变量赋值", "key_params": ["map"]},
    "http_request": {"description": "HTTP 请求", "key_params": ["url", "method"]},
    "call_subflow": {"description": "调用子流程", "key_params": ["flow_path"]},
    "switch": {"description": "多路分支", "key_params": ["expression"]},
    "loop_while": {"description": "条件循环", "key_params": ["expression"]},
    "loop_foreach": {"description": "遍历循环", "key_params": ["items"]},
    "loop_forever": {"description": "无限循环（慎用）", "key_params": []},
    "window_close": {"description": "关闭窗口", "key_params": ["title"]},
    "if_color_match": {"description": "颜色匹配分支", "key_params": ["target_color"]},
    "if_logic": {"description": "逻辑组合分支", "key_params": []},
    "image_generate": {
        "description": "AI 生图：调 OpenAI 兼容生图接口存盘",
        "key_params": ["prompt", "size", "count", "save_path"],
        "ai_hints": "需在设置中配置生图模型；输出 first_path 可接 find_image/image_scale",
    },
}


def block_ai_card(schema: dict[str, Any]) -> dict[str, Any]:
    btype = str(schema.get("type") or "")
    hint = _AI_HINTS.get(btype) or {}
    inputs = schema.get("inputs") or []
    key_params = hint.get("key_params")
    if not key_params:
        key_params = [str(i.get("name")) for i in inputs[:6] if isinstance(i, dict)]
    desc = (
        schema.get("description")
        or hint.get("description")
        or f"{schema.get('label') or btype}"
    )
    return {
        "type": btype,
        "label": schema.get("label") or btype,
        "category": schema.get("category") or "",
        "description": desc,
        "key_params": key_params,
        "ai_hints": hint.get("ai_hints") or "",
    }


def list_ai_block_cards(
    *,
    allow_dangerous: bool = False,
    category: str | None = None,
) -> list[dict[str, Any]]:
    cat = (category or "").strip()
    out: list[dict[str, Any]] = []
    for schema in get_schemas():
        btype = str(schema.get("type") or "")
        if not is_block_allowed(btype, allow_dangerous=allow_dangerous):
            continue
        if cat and str(schema.get("category") or "") != cat:
            continue
        out.append(block_ai_card(schema))
    out.sort(key=lambda x: (x.get("category") or "", x.get("type") or ""))
    return out


def coverage_report(*, allow_dangerous: bool = False) -> dict[str, Any]:
    cards = list_ai_block_cards(allow_dangerous=allow_dangerous)
    missing_desc = [c["type"] for c in cards if not (c.get("description") or "").strip()]
    return {
        "count": len(cards),
        "missing_description": missing_desc,
        "ok": len(missing_desc) == 0 and len(cards) > 0,
        "types": [c["type"] for c in cards],
    }


def inject_descriptions_into_list_blocks() -> None:
    """No-op hook retained for compatibility; cards are built on the fly."""
    return
