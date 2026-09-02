"""Deterministic outline → draft helpers (build_loop fallback / offline)."""

from __future__ import annotations

import time
from typing import Any

from backend.core.ai import draft_builder
from backend.core.ai.graphs.recipes import (
    _auto_connect,
    _recipe_ocr_click_chain,
)
from backend.core.ai.tool_runtime import ToolRuntime


def build_draft_from_outline(
    draft: dict[str, Any],
    outline: dict[str, Any] | None,
    *,
    slots: dict[str, str] | None = None,
    artifacts: dict[str, Any] | None = None,
    tool_trace: list[dict[str, Any]] | None = None,
    compile_trace: list[dict[str, Any]] | None = None,
    strict_coords: bool = True,
) -> dict[str, Any]:
    """
    Expand PlanOutline steps into nodes without LLM tool-calling.
    Used when tool-calling fails or in tests.
    """
    arts = artifacts if isinstance(artifacts, dict) else {"shots": {}, "points": {}}
    trace = tool_trace if tool_trace is not None else []
    compiler_trace = compile_trace if compile_trace is not None else []
    slots = dict(slots or {})
    steps = []
    if isinstance(outline, dict):
        steps = list(outline.get("steps") or [])
    runtime = ToolRuntime(strict_coords=strict_coords)
    last: str | None = draft.get("entry")
    # walk to chain end
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if nodes and last:
        seen: set[str] = set()
        cur = last
        while cur and cur in nodes and cur not in seen:
            seen.add(cur)
            nxt = nodes[cur].get("next") if isinstance(nodes[cur], dict) else None
            if not nxt:
                last = cur
                break
            cur = nxt
            last = cur

    errors: list[str] = []
    for index, raw in enumerate(steps, 1):
        if not isinstance(raw, dict):
            continue
        before = set((draft.get("nodes") or {}).keys())
        started = time.perf_counter()
        try:
            last = _apply_outline_step(
                draft,
                raw,
                slots=slots,
                last_node_id=last,
                runtime=runtime,
                artifacts=arts,
                tool_trace=trace,
            )
            after = set((draft.get("nodes") or {}).keys())
            compiler_trace.append(
                {
                    "source": "outline_compile",
                    "step_id": str(raw.get("id") or f"s{index}"),
                    "block_hint": str(raw.get("block_hint") or ""),
                    "status": "ok",
                    "node_ids": sorted(after - before),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
        except Exception as exc:
            errors.append(str(exc))
            compiler_trace.append(
                {
                    "source": "outline_compile",
                    "step_id": str(raw.get("id") or f"s{index}"),
                    "block_hint": str(raw.get("block_hint") or ""),
                    "status": "error",
                    "error": str(exc),
                    "node_ids": [],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )

    return {
        "ok": not errors,
        "draft": draft,
        "artifacts": arts,
        "tool_trace": trace,
        "compile_trace": compiler_trace,
        "errors": errors,
        "needs_locate": False,
        "locate_texts": [],
    }


def _apply_outline_step(
    draft: dict[str, Any],
    step: dict[str, Any],
    *,
    slots: dict[str, str],
    last_node_id: str | None,
    runtime: ToolRuntime,
    artifacts: dict[str, Any],
    tool_trace: list[dict[str, Any]],
) -> str | None:
    hint = str(step.get("block_hint") or "").strip().lower()
    params = dict(step.get("params") or {})
    # merge slots into params when empty
    for k, v in slots.items():
        if v and k not in params:
            params[k] = v
    match_text = (
        step.get("match_text")
        or params.get("match_text")
        or params.get("text")
        or ""
    )
    sense = str(step.get("needs_sense") or "none")

    if hint in ("delay",):
        ms = int(params.get("ms") or 1000)
        draft, nid = draft_builder.add_node(draft, block_type="delay", params={"ms": ms})
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("type_text", "type"):
        text = str(params.get("text") or slots.get("message") or match_text or "")
        draft, nid = draft_builder.add_node(
            draft, block_type="type_text", params={"text": text}
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("key_press", "key"):
        raw_key = params.get("key")
        if raw_key is None:
            raw_key = params.get("keys")
        if isinstance(raw_key, list):
            keys = [str(k) for k in raw_key if str(k).strip()]
        elif raw_key is not None and str(raw_key).strip():
            keys = [str(raw_key).strip()]
        else:
            keys = ["enter"]
        draft, nid = draft_builder.add_node(
            draft,
            block_type="key_press",
            params={"key_mode": "single", "keys": keys},
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("window_activate", "window_focus", "window"):
        title = str(
            params.get("title")
            or params.get("window_title")
            or slots.get("window_title")
            or ""
        ).strip()
        if not title:
            raise ValueError("window_activate 需要 title/window_title")
        draft, nid = draft_builder.add_node(
            draft, block_type="window_activate", params={"title": title}
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("schedule_trigger", "schedule_at", "schedule"):
        if str(slots.get("schedule") or "").lower() in ("false", "0", "no"):
            return last_node_id
        p = {
            "trigger_type": params.get("trigger_type") or "once",
            "run_at": params.get("run_at") or slots.get("run_at") or "",
            "cron_expression": params.get("cron_expression") or "0 9 * * *",
        }
        draft, nid = draft_builder.add_node(
            draft, block_type="schedule_trigger", params=p
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    # OCR 识别+点击链仅用于"点击"类 hint。wait_until / if_text_contains 是
    # 自感知积木（内部自带截图 OCR），此前被 `or sense == "ocr"` 劫持成点击链，
    # 导致 wait_text 编译成"点击目标文字"、if_text 丢失 if 节点。
    if hint in ("ocr_click", "text_click", "click"):
        text = str(
            match_text
            or params.get("contact")
            or slots.get("contact")
            or params.get("match_text")
            or ""
        ).strip()
        if not text:
            raise ValueError("ocr_click 需要 match_text")
        return _recipe_ocr_click_chain(
            draft,
            match_text=text,
            last_node_id=last_node_id,
            tool_trace=tool_trace,
            runtime=runtime,
            artifacts=artifacts,
            window_title=str(
                params.get("window_title")
                or params.get("title")
                or slots.get("window_title")
                or ""
            ),
        )

    if hint in ("wait_until", "wait_text"):
        text = str(match_text or params.get("expect_text") or "").strip()
        draft, nid = draft_builder.add_node(
            draft,
            block_type="wait_until",
            params={
                "wait_type": "text",
                "expect_text": text,
                "timeout_ms": params.get("timeout_ms") or 30000,
            },
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("if_text_contains", "if_text"):
        text = str(match_text or params.get("match_text") or "").strip()
        draft, nid = draft_builder.add_node(
            draft,
            block_type="if_text_contains",
            params={"source_mode": "capture", "match_text": text, "expect_text": text},
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("loop_n",):
        draft, nid = draft_builder.add_node(
            draft,
            block_type="loop_n",
            params={"times": int(params.get("times") or params.get("count") or 3)},
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("try_catch",):
        draft, nid = draft_builder.add_node(draft, block_type="try_catch", params={})
        _auto_connect(draft, last_node_id, nid)
        return nid

    if hint in ("find_image", "find_image_click"):
        path = str(params.get("path") or params.get("template") or "").strip()
        if not path:
            raise ValueError("find_image 需要 path")
        draft, fid = draft_builder.add_node(
            draft, block_type="find_image", params={"path": path, "template": path}
        )
        _auto_connect(draft, last_node_id, fid)
        draft, cid = draft_builder.add_node(
            draft,
            block_type="click",
            params={
                "x": f"{{{{{fid}.x}}}}",
                "y": f"{{{{{fid}.y}}}}",
                "coordinate_mode": "screen_abs",
            },
        )
        draft_builder.connect(draft, from_id=fid, to_id=cid, edge="next")
        return cid

    # Generic add by block_hint as type
    if hint:
        draft, nid = draft_builder.add_node(
            draft, block_type=hint, params=params
        )
        _auto_connect(draft, last_node_id, nid)
        return nid
    return last_node_id
