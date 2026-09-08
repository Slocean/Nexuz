"""Trim runtime payloads before IPC / long-lived context retention."""

from __future__ import annotations

from typing import Any

_MAX_STR = 240
_MAX_LIST = 24
_MAX_DICT_KEYS = 40
_MAX_DEPTH = 6
_HEAVY_KEYS = frozenset({"box", "image", "bitmap", "pixels", "raw", "screenshot"})
# Large OCR lists: keep bindable structure, drop only heavy nested keys.
_LIGHT_LIST_KEYS = frozenset({"boxes", "matches", "items", "issues"})
_WINDOW_TARGET_KEYS = (
    "pid",
    "process_name",
    "class_name",
    "title",
    "client_width",
    "client_height",
    "dpi",
    "point_norm",
)


def _compact_window_target(value: Any) -> Any:
    """Keep fields needed for window_client click replay after OCR compacting."""
    if isinstance(value, list):
        return [_compact_window_target(v) for v in value[:24]]
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for key in _WINDOW_TARGET_KEYS:
        if key not in value:
            continue
        val = value.get(key)
        if key == "point_norm" and isinstance(val, (list, tuple)) and len(val) >= 2:
            try:
                out[key] = [float(val[0]), float(val[1])]
            except (TypeError, ValueError):
                continue
        elif key in ("process_name", "class_name", "title"):
            out[key] = str(val or "")[:160]
        else:
            out[key] = val
    return out or None


def _compact_scalar_list(value: list[Any] | tuple[Any, ...], *, str_limit: int = 80) -> list[Any]:
    head: list[Any] = []
    for x in list(value)[:_MAX_LIST]:
        if isinstance(x, (bool, int, float)) or x is None:
            head.append(x)
        elif isinstance(x, str):
            head.append(x[:str_limit])
        elif isinstance(x, dict):
            head.append(_compact_structured_dict(x, depth=1))
        else:
            try:
                head.append(int(round(float(x))))
            except (TypeError, ValueError):
                head.append(str(x)[:str_limit])
    return head


def _compact_structured_dict(item: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    """Preserve real keys/structure; only strip heavy payloads and truncate sizes.

    Previously a fixed OCR field whitelist dropped ``*_all`` / ``primary_index`` etc.,
    which broke downstream path digs that follow the live output shape.
    """
    entry: dict[str, Any] = {}
    for i, (key, val) in enumerate(item.items()):
        if i >= _MAX_DICT_KEYS:
            entry["…"] = f"+{len(item) - _MAX_DICT_KEYS} keys"
            break
        lk = str(key).lower()
        if lk in _HEAVY_KEYS:
            continue
        if lk == "window_target":
            wt = _compact_window_target(val)
            if wt is not None:
                entry[key] = wt
            continue
        if val is None or isinstance(val, (bool, int, float)):
            entry[key] = val
        elif isinstance(val, str):
            entry[key] = val[:120] if len(val) > 120 else val
        elif isinstance(val, (list, tuple)):
            entry[key] = _compact_scalar_list(val)
        elif isinstance(val, dict):
            if depth >= 3:
                entry[key] = "{…}"
            else:
                entry[key] = _compact_structured_dict(val, depth=depth + 1)
        else:
            entry[key] = str(val)[:120]
    return entry


def _compact_structured_list(value: list[Any]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in value[:200]:
        if isinstance(item, dict):
            compact.append(_compact_structured_dict(item))
    return compact


def summarize_value(value: Any, *, depth: int = 0, key: str | None = None) -> Any:
    """Return a compact, JSON-serializable preview of a runtime value."""
    # Scalars always pass through — never replace numbers with "…" due to depth.
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _MAX_STR:
            return value
        return f"{value[:_MAX_STR]}…(+{len(value) - _MAX_STR})"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"

    leaf = str(key).lower() if key else ""
    if leaf in _LIGHT_LIST_KEYS and isinstance(value, list):
        return _compact_structured_list(value)
    if leaf in _HEAVY_KEYS:
        if isinstance(value, list):
            return {"_omitted": leaf, "count": len(value)}
        return None if value is None else {"_omitted": leaf}

    if depth >= _MAX_DEPTH:
        return "…"

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_DICT_KEYS:
                out["…"] = f"+{len(value) - _MAX_DICT_KEYS} keys"
                break
            out[str(k)] = summarize_value(v, depth=depth + 1, key=str(k))
        return out
    if isinstance(value, (list, tuple)):
        items = list(value)
        # Homogeneous number lists (multi-hit OCR coords) stay numeric.
        if items and all(isinstance(v, (bool, int, float)) or v is None for v in items):
            head = list(items[:_MAX_LIST])
            if len(items) > _MAX_LIST:
                head.append(f"…(+{len(items) - _MAX_LIST})")
            return head
        head = [summarize_value(v, depth=depth + 1) for v in items[:_MAX_LIST]]
        if len(items) > _MAX_LIST:
            head.append(f"…(+{len(items) - _MAX_LIST})")
        return head
    return str(value)[:_MAX_STR]


def summarize_params(params: dict | None) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    return {str(k): summarize_value(v, key=str(k)) for k, v in params.items()}


def summarize_result(result: dict | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {str(k): summarize_value(v, key=str(k)) for k, v in result.items()}


def summarize_node_outcome(
    block_type: str,
    *,
    ok: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    elapsed_ms: float | None = None,
    stopped: bool = False,
) -> str:
    """One-line human summary for runtime logs."""
    t = str(block_type or "node")
    if stopped:
        return f"{t} 已停止"
    if not ok:
        return f"{t} 失败: {error or '未知错误'}"
    r = result if isinstance(result, dict) else {}
    ms = f" · {elapsed_ms}ms" if elapsed_ms is not None else ""

    if t == "click":
        x, y = r.get("x", r.get("screen_x")), r.get("y", r.get("screen_y"))
        ax, ay = r.get("actual_x"), r.get("actual_y")
        hit = r.get("hit_process") or r.get("hit_title")
        try:
            count = int(r.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        if count > 1:
            pts = r.get("clicks") if isinstance(r.get("clicks"), list) else []
            if pts:
                trail = " → ".join(
                    f"({p.get('x')}, {p.get('y')})"
                    for p in pts
                    if isinstance(p, dict) and p.get("x") is not None
                )
                if trail:
                    return f"多点点击 {count} 次 {trail}{ms}"
            if x is not None and y is not None:
                return f"多点点击 {count} 次 · 末点 ({x}, {y}){ms}"
            return f"多点点击 {count} 次{ms}"
        if x is not None and y is not None:
            extra = ""
            if ax is not None and ay is not None and (ax != x or ay != y):
                extra += f" · 实际光标 ({ax}, {ay})"
            if hit:
                extra += f" · 命中 {hit}"
            return f"点击 ({x}, {y}){extra}{ms}"
        return f"点击完成{ms}"
    if t == "drag":
        return f"拖拽完成{ms}"
    if t == "mouse_hover":
        x, y = r.get("x"), r.get("y")
        if x is not None and y is not None:
            return f"悬停 ({x}, {y}){ms}"
        return f"悬停完成{ms}"
    if t == "find_image":
        found = bool(r.get("found"))
        score = r.get("score")
        if found:
            return f"找图命中 score={score} @ ({r.get('x')}, {r.get('y')}){ms}"
        return f"找图未命中{ms}"
    if t == "ocr_recognize":
        text = r.get("text")
        if text:
            return f"OCR: {str(text)[:120]}{ms}"
        return f"OCR 无文字{ms}"
    if t == "if_text_contains":
        matched = bool(r.get("matched"))
        actual = r.get("actual_text")
        recognized = r.get("recognized")
        if matched:
            detail = f" · 实际: {str(actual)[:80]}" if actual else ""
            return f"文字匹配 成立{detail}{ms}"
        if recognized is False or (recognized is None and not actual):
            return f"文字匹配 不成立 · 识别为空{ms}"
        return f"文字匹配 不成立 · 实际: {str(actual)[:80]}{ms}"
    if t in ("if_condition", "if_color_match", "if_logic"):
        return f"条件{'成立' if r.get('matched') else '不成立'}{ms}"
    if t == "color_detect":
        c = r.get("color") or r.get("hex")
        return f"取色 {c}{ms}" if c else f"取色完成{ms}"
    if t == "switch":
        return f"分支值={r.get('value')!r}{ms}"
    if t.startswith("window_"):
        found = r.get("found")
        title = r.get("title") or r.get("matched_title")
        if found is False:
            return f"{t} 未找到窗口{ms}"
        if title:
            return f"{t} → {str(title)[:80]}{ms}"
        return f"{t} 完成{ms}"
    if t.startswith("loop_"):
        return f"循环步进{ms}"
    if t == "assign":
        name = r.get("name") or r.get("variable")
        return f"赋值 {name}{ms}" if name else f"赋值完成{ms}"
    if t == "delay":
        return f"延时完成{ms}"
    # Generic: surface a few useful keys
    keys = [k for k in ("found", "matched", "ok", "x", "y", "text", "value") if k in r]
    if keys:
        bits = ", ".join(f"{k}={r.get(k)!r}" for k in keys[:4])
        return f"{t} {bits}{ms}"
    return f"{t} 完成{ms}"


def compact_context_value(key: str, value: Any) -> Any:
    """Keep context bindable but drop heavy OCR/geometry payloads.

    Structure follows the live value — do not rewrite to a fixed field set.
    """
    k = str(key)
    leaf = k.rsplit(".", 1)[-1].lower()
    if leaf in ("boxes", "matches") and isinstance(value, list):
        return _compact_structured_list(value)
    if leaf in ("box", "image", "bitmap", "pixels") and isinstance(value, (list, dict)):
        return None
    return value
