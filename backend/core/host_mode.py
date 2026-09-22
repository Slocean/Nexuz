"""运行宿主模式：桌面应用 vs 无头服务器。

backend/server.py 启动时置位 headless；桌面入口（backend/main.py）完全不接触
本模块，桌面行为零变化。消费方：interpreter / run_block_once 的 requires 闸、
tool_catalog 目录过滤、mcp_bridge 无头工具报错。

积木分档（docs/headless_server.md）：
- 无标记（A 档）：无头全可用；
- requires="partial"（B 档）：按参数判定（wait_until 的屏幕条件、monitor 的
  window/screen 条件、剪贴板的 Session 0）；
- requires="desktop"（C 档）：真机绑定，无头一律拒绝。
"""

from __future__ import annotations

import ctypes
import os
import threading

_lock = threading.Lock()
_headless = False


def set_headless(value: bool = True) -> None:
    global _headless
    with _lock:
        _headless = bool(value)


def is_headless() -> bool:
    with _lock:
        return _headless


def is_interactive_session() -> bool:
    """当前进程是否在可交互桌面会话中（Windows Session 0 服务模式返回 False）。

    判定失败时按可交互处理（宁可放行由积木自身报错，不误伤桌面场景）。
    """
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        session_id = ctypes.c_uint32(0)
        if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            return bool(session_id.value)
        return True
    except Exception:
        return True


# monitor/wait_until 里依赖屏幕或桌面窗口的条件，无头下拒绝。
_SCREEN_WAIT_TYPES = frozenset({"color", "text"})
_DESKTOP_MONITOR_TYPES = frozenset({"window", "screen_text", "screen_color"})

# 浏览器积木本身是 A 档（有 Chromium 就能跑），但这份服务器镜像没装浏览器。
BROWSER_BLOCK_TYPES = frozenset(
    {
        "browser_click",
        "browser_close",
        "browser_eval",
        "browser_extract",
        "browser_fill",
        "browser_navigate",
        "browser_resize",
        "browser_screenshot",
        "browser_snapshot",
        "browser_tabs",
        "browser_wait",
    }
)

# 当前无头环境不具备的能力：无 Chromium/Edge、无 tk 剪贴板、无屏幕抓取。
# 未配置的云服务积木（llm_forward / image_generate / smtp_send）不在此列。
HEADLESS_ENV_UNAVAILABLE_TYPES = BROWSER_BLOCK_TYPES | frozenset(
    {
        "clipboard",
        "ocr_recognize",
    }
)


def hide_from_headless_catalog(schema: dict | None) -> bool:
    """无头目录是否隐藏该积木（真机档 + 当前环境不具备的能力）。"""
    if not is_headless():
        return False
    schema = schema if isinstance(schema, dict) else {}
    btype = str(schema.get("type") or "")
    if btype in HEADLESS_ENV_UNAVAILABLE_TYPES:
        return True
    return str(schema.get("requires") or "") == "desktop"


def headless_block_error(block_type: str, params: dict | None) -> str | None:
    """无头模式下的拒绝理由；None = 允许执行。桌面模式调用方不应走到这里。"""
    if not is_headless():
        return None
    block_type = str(block_type or "").strip()
    from backend.core.registry import BLOCK_REGISTRY

    entry = BLOCK_REGISTRY.get(block_type)
    schema = entry.get("schema") if isinstance(entry, dict) else None
    requires = str((schema or {}).get("requires") or "")
    params = params if isinstance(params, dict) else {}

    if block_type in HEADLESS_ENV_UNAVAILABLE_TYPES:
        return f"积木 {block_type} 当前服务器环境不可用"
    if requires == "desktop":
        return f"积木 {block_type} 需要真机桌面，服务器形态不可用"
    if requires != "partial":
        return None

    if block_type == "wait_until":
        wait_type = str(params.get("wait_type") or "text").strip().lower()
        if wait_type in _SCREEN_WAIT_TYPES:
            return (
                f"积木 wait_until 的当前参数需要真机桌面"
                f"（wait_type={wait_type} 依赖屏幕），服务器形态不可用"
            )
        return None
    if block_type == "monitor_start":
        mtype = str(params.get("monitor_type") or "").strip().lower()
        if mtype in _DESKTOP_MONITOR_TYPES:
            return (
                f"积木 monitor_start 的当前参数需要真机桌面"
                f"（monitor_type={mtype} 依赖窗口/屏幕），服务器形态不可用"
            )
        return None
    if block_type == "clipboard":
        if not is_interactive_session():
            return "积木 clipboard 需要可交互桌面会话（服务模式下不可用）"
        return None
    return None
