"""Deterministic recipe macros: FlowSpec steps → draft mutations."""

from __future__ import annotations

from typing import Any

from backend.core.ai import draft_builder
from backend.core.ai.graphs._heuristic_plan import heuristic_plan_from_text
from backend.core.ai.lc.structured import FlowSpec, PlanStep, parse_flow_spec
from backend.core.ai.tool_runtime import ToolRuntime

__all__ = ["apply_flow_spec", "heuristic_plan_from_text"]


def apply_flow_spec(
    draft: dict[str, Any],
    plan: FlowSpec | dict[str, Any] | None,
    *,
    artifacts: dict[str, Any] | None = None,
    allow_dangerous: bool = False,
    strict_coords: bool = True,
    tool_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Apply FlowSpec to draft. Prefers recipes; falls back to draft_* via ToolRuntime.
    Returns {ok, draft, artifacts, tool_trace, errors, needs_locate, locate_texts}.
    """
    spec = parse_flow_spec(plan)
    arts = artifacts if isinstance(artifacts, dict) else {"shots": {}, "points": {}}
    trace = tool_trace if tool_trace is not None else []
    errors: list[str] = []
    runtime = ToolRuntime(
        allow_dangerous=allow_dangerous,
        strict_coords=strict_coords,
    )
    last_node_id: str | None = draft.get("entry")
    # Prefer last node in chain for auto-connect
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    if nodes:
        # walk from entry
        cur = draft.get("entry")
        seen = set()
        while cur and cur in nodes and cur not in seen:
            seen.add(cur)
            nxt = nodes[cur].get("next") if isinstance(nodes[cur], dict) else None
            if not nxt:
                last_node_id = cur
                break
            cur = nxt
            last_node_id = cur

    for step in spec.steps:
        try:
            last_node_id = _apply_step(
                draft,
                arts,
                step,
                runtime=runtime,
                tool_trace=trace,
                last_node_id=last_node_id,
            )
        except Exception as exc:
            errors.append(str(exc))

    return {
        "ok": not errors,
        "draft": draft,
        "artifacts": arts,
        "tool_trace": trace,
        "errors": errors,
        "needs_locate": bool(spec.needs_locate or spec.locate_texts),
        "locate_texts": list(spec.locate_texts or []),
        "intent_summary": spec.intent_summary,
    }


def _apply_step(
    draft: dict[str, Any],
    artifacts: dict[str, Any],
    step: PlanStep,
    *,
    runtime: ToolRuntime,
    tool_trace: list[dict[str, Any]],
    last_node_id: str | None,
) -> str | None:
    action = (step.action or "add").strip().lower()
    params = dict(step.params or {})

    if action == "recipe" or action == "call_skill":
        name = (step.recipe or step.params.get("skill") or "").strip()
        if name in ("ocr_click_chain", "ocr_click", "text_click"):
            return _recipe_ocr_click_chain(
                draft,
                match_text=step.match_text
                or params.get("match_text")
                or params.get("text")
                or "",
                last_node_id=last_node_id,
                tool_trace=tool_trace,
                runtime=runtime,
                artifacts=artifacts,
            )
        if name in ("delay_type", "type_after_delay"):
            return _recipe_delay_type(
                draft,
                ms=int(params.get("ms") or 1000),
                text=str(params.get("text") or ""),
                last_node_id=last_node_id,
                press_enter=bool(params.get("press_enter")),
            )
        if name == "type_enter":
            return _recipe_type_enter(
                draft,
                text=str(params.get("text") or step.match_text or ""),
                last_node_id=last_node_id,
            )
        if name in ("wait_text", "ocr_wait_click", "wait_then_act"):
            return _recipe_wait_text(
                draft,
                match_text=step.match_text or params.get("match_text") or "",
                then_click=bool(params.get("then_click", name != "wait_text")),
                click_text=params.get("click_text") or step.match_text,
                last_node_id=last_node_id,
                tool_trace=tool_trace,
                runtime=runtime,
                artifacts=artifacts,
            )
        if name in ("window_focus", "window_activate"):
            return _recipe_window_focus(
                draft,
                title=str(params.get("title_contains") or params.get("title") or "微信"),
                last_node_id=last_node_id,
            )
        if name in ("schedule_at", "schedule_trigger"):
            return _recipe_schedule_at(
                draft,
                params=params,
                last_node_id=last_node_id,
            )
        if name == "find_image_click":
            return _recipe_find_image_click(
                draft,
                template=str(params.get("template") or params.get("path") or ""),
                last_node_id=last_node_id,
                tool_trace=tool_trace,
                runtime=runtime,
                artifacts=artifacts,
            )
        if name == "color_click":
            return _recipe_color_click(
                draft,
                params=params,
                last_node_id=last_node_id,
            )
        if name == "wechat_send_message":
            return _recipe_wechat_send_message(
                draft,
                params=params,
                last_node_id=last_node_id,
                tool_trace=tool_trace,
                runtime=runtime,
                artifacts=artifacts,
            )
        if name in ("if_text", "if_text_contains"):
            return _recipe_if_text(
                draft,
                params=params,
                match_text=step.match_text or params.get("match_text") or "",
                last_node_id=last_node_id,
            )
        if name in ("loop_n", "loop_times"):
            return _recipe_loop_n(
                draft,
                times=int(params.get("times") or params.get("count") or 3),
                last_node_id=last_node_id,
            )
        if name in ("try_catch", "try_catch_wrap"):
            return _recipe_try_catch(draft, last_node_id=last_node_id)
        # try skill pack registry
        from backend.core.ai.skills.loader import try_apply_skill

        skill_last = try_apply_skill(
            name,
            draft,
            params={**params, "match_text": step.match_text},
            last_node_id=last_node_id,
            artifacts=artifacts,
            tool_trace=tool_trace,
            runtime=runtime,
        )
        if skill_last is not None:
            return skill_last
        raise ValueError(f"未知 recipe/skill: {name}")

    if action == "ocr_click":
        return _recipe_ocr_click_chain(
            draft,
            match_text=step.match_text or params.get("match_text") or "",
            last_node_id=last_node_id,
            tool_trace=tool_trace,
            runtime=runtime,
            artifacts=artifacts,
        )

    if action == "delay":
        ms = params.get("ms", 1000)
        draft, nid = draft_builder.add_node(
            draft,
            block_type="delay",
            params={"ms": ms},
            node_id=step.node_id,
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if action == "type_text":
        text = params.get("text") or step.match_text or ""
        draft, nid = draft_builder.add_node(
            draft,
            block_type="type_text",
            params={"text": text},
            node_id=step.node_id,
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if action == "key_press":
        key = params.get("key") or params.get("keys") or "enter"
        if isinstance(key, str):
            key_params = {"key_mode": "single", "keys": [key]}
        else:
            key_params = {"key_mode": "single", "keys": list(key)}
        draft, nid = draft_builder.add_node(
            draft,
            block_type="key_press",
            params=key_params,
            node_id=step.node_id,
        )
        _auto_connect(draft, last_node_id, nid)
        return nid

    if action == "connect":
        runtime.execute(
            "draft_connect",
            {"from_id": step.from_id, "to_id": step.to_id, "edge": step.edge or "next"},
            draft=draft,
            artifacts=artifacts,
            tool_trace=tool_trace,
        )
        return last_node_id

    if action == "set_entry":
        runtime.execute(
            "draft_set_entry",
            {"node_id": step.node_id},
            draft=draft,
            artifacts=artifacts,
            tool_trace=tool_trace,
        )
        return step.node_id or last_node_id

    if action == "remove":
        runtime.execute(
            "draft_remove_node",
            {"node_id": step.node_id},
            draft=draft,
            artifacts=artifacts,
            tool_trace=tool_trace,
        )
        return last_node_id

    if action == "update":
        runtime.execute(
            "draft_update_node",
            {
                "node_id": step.node_id,
                "params": params,
                "point_ref": params.get("point_ref"),
            },
            draft=draft,
            artifacts=artifacts,
            tool_trace=tool_trace,
        )
        return step.node_id or last_node_id

    # default add
    btype = (step.block_type or "").strip()
    if not btype:
        raise ValueError(f"步骤缺少 block_type: {step.model_dump()}")
    result = runtime.execute(
        "draft_add_node",
        {
            "type": btype,
            "params": params,
            "node_id": step.node_id,
            "point_ref": params.get("point_ref") or None,
        },
        draft=draft,
        artifacts=artifacts,
        tool_trace=tool_trace,
    )
    if not result.get("ok"):
        raise ValueError(result.get("error") or f"添加节点失败: {btype}")
    nid = str(result.get("node_id") or "")
    _auto_connect(draft, last_node_id, nid)
    return nid


def _auto_connect(draft: dict[str, Any], from_id: str | None, to_id: str) -> None:
    if not from_id or not to_id or from_id == to_id:
        return
    nodes = draft.get("nodes") if isinstance(draft.get("nodes"), dict) else {}
    src = nodes.get(from_id)
    if not isinstance(src, dict):
        return
    if src.get("next"):
        return
    try:
        draft_builder.connect(draft, from_id=from_id, to_id=to_id, edge="next")
    except Exception:
        pass


def _recipe_delay_type(
    draft: dict[str, Any],
    *,
    ms: int,
    text: str,
    last_node_id: str | None,
    press_enter: bool = False,
) -> str:
    draft, d_id = draft_builder.add_node(draft, block_type="delay", params={"ms": ms})
    _auto_connect(draft, last_node_id, d_id)
    draft, t_id = draft_builder.add_node(draft, block_type="type_text", params={"text": text})
    draft_builder.connect(draft, from_id=d_id, to_id=t_id, edge="next")
    if press_enter:
        draft, k_id = draft_builder.add_node(
            draft,
            block_type="key_press",
            params={"key_mode": "single", "keys": ["enter"]},
        )
        draft_builder.connect(draft, from_id=t_id, to_id=k_id, edge="next")
        return k_id
    return t_id


def _recipe_type_enter(
    draft: dict[str, Any],
    *,
    text: str,
    last_node_id: str | None,
) -> str:
    draft, t_id = draft_builder.add_node(draft, block_type="type_text", params={"text": text})
    _auto_connect(draft, last_node_id, t_id)
    draft, k_id = draft_builder.add_node(
        draft,
        block_type="key_press",
        params={"key_mode": "single", "keys": ["enter"]},
    )
    draft_builder.connect(draft, from_id=t_id, to_id=k_id, edge="next")
    return k_id


def _recipe_wait_text(
    draft: dict[str, Any],
    *,
    match_text: str,
    then_click: bool,
    click_text: str | None,
    last_node_id: str | None,
    tool_trace: list[dict[str, Any]],
    runtime: ToolRuntime,
    artifacts: dict[str, Any],
) -> str:
    text = (match_text or "").strip()
    if not text:
        raise ValueError("wait_text 需要 match_text")
    draft, wid = draft_builder.add_node(
        draft,
        block_type="wait_until",
        params={"wait_type": "text", "expect_text": text, "timeout_ms": 30000},
    )
    _auto_connect(draft, last_node_id, wid)
    if then_click:
        label = (click_text or text).strip()
        return _recipe_ocr_click_chain(
            draft,
            match_text=label,
            last_node_id=wid,
            tool_trace=tool_trace,
            runtime=runtime,
            artifacts=artifacts,
        )
    return wid


def _recipe_window_focus(
    draft: dict[str, Any],
    *,
    title: str,
    last_node_id: str | None,
) -> str:
    draft, nid = draft_builder.add_node(
        draft,
        block_type="window_activate",
        params={"title": title or ""},
    )
    _auto_connect(draft, last_node_id, nid)
    return nid


def _recipe_schedule_at(
    draft: dict[str, Any],
    *,
    params: dict[str, Any],
    last_node_id: str | None,
) -> str:
    p = {
        "trigger_type": params.get("trigger_type") or "once",
        "run_at": params.get("run_at") or params.get("time") or "",
        "cron_expression": params.get("cron_expression") or "0 9 * * *",
        "interval_seconds": params.get("interval_seconds") or 60,
    }
    draft, nid = draft_builder.add_node(draft, block_type="schedule_trigger", params=p)
    _auto_connect(draft, last_node_id, nid)
    return nid


def _recipe_find_image_click(
    draft: dict[str, Any],
    *,
    template: str,
    last_node_id: str | None,
    tool_trace: list[dict[str, Any]],
    runtime: ToolRuntime,
    artifacts: dict[str, Any],
) -> str:
    draft, fid = draft_builder.add_node(
        draft,
        block_type="find_image",
        params={"path": template or "", "template": template or ""},
    )
    _auto_connect(draft, last_node_id, fid)
    click_params = {
        "x": f"{{{{{fid}.x}}}}",
        "y": f"{{{{{fid}.y}}}}",
        "coordinate_mode": "screen_abs",
    }
    draft, cid = draft_builder.add_node(draft, block_type="click", params=click_params)
    draft_builder.connect(draft, from_id=fid, to_id=cid, edge="next")
    return cid


def _recipe_color_click(
    draft: dict[str, Any],
    *,
    params: dict[str, Any],
    last_node_id: str | None,
) -> str:
    draft, cid_detect = draft_builder.add_node(
        draft,
        block_type="color_detect",
        params=dict(params or {}),
    )
    _auto_connect(draft, last_node_id, cid_detect)
    click_params = {
        "x": f"{{{{{cid_detect}.x}}}}",
        "y": f"{{{{{cid_detect}.y}}}}",
        "coordinate_mode": "screen_abs",
    }
    draft, click_id = draft_builder.add_node(
        draft, block_type="click", params=click_params
    )
    draft_builder.connect(draft, from_id=cid_detect, to_id=click_id, edge="next")
    return click_id


def _recipe_wechat_send_message(
    draft: dict[str, Any],
    *,
    params: dict[str, Any],
    last_node_id: str | None,
    tool_trace: list[dict[str, Any]],
    runtime: ToolRuntime,
    artifacts: dict[str, Any],
) -> str:
    """Skeleton: schedule → window → search contact via OCR → type → send click."""
    contact = str(params.get("contact") or params.get("to") or "王哥")
    message = str(params.get("message") or params.get("text") or "")
    run_at = str(params.get("run_at") or params.get("time") or "")
    cur = last_node_id
    if run_at or params.get("schedule", True):
        cur = _recipe_schedule_at(
            draft,
            params={"trigger_type": "once", "run_at": run_at},
            last_node_id=cur,
        )
    cur = _recipe_window_focus(draft, title="微信", last_node_id=cur)
    # search / contact via OCR click on contact name
    cur = _recipe_ocr_click_chain(
        draft,
        match_text=contact,
        last_node_id=cur,
        tool_trace=tool_trace,
        runtime=runtime,
        artifacts=artifacts,
    )
    if message:
        draft, tid = draft_builder.add_node(
            draft, block_type="type_text", params={"text": message}
        )
        draft_builder.connect(draft, from_id=cur, to_id=tid, edge="next")
        cur = tid
    cur = _recipe_ocr_click_chain(
        draft,
        match_text=str(params.get("send_label") or "发送"),
        last_node_id=cur,
        tool_trace=tool_trace,
        runtime=runtime,
        artifacts=artifacts,
    )
    return cur


def _recipe_if_text(
    draft: dict[str, Any],
    *,
    params: dict[str, Any],
    match_text: str,
    last_node_id: str | None,
) -> str:
    text = (match_text or params.get("contains") or params.get("expect_text") or "").strip()
    p = {
        "source_mode": params.get("source_mode") or "capture",
        "match_text": text,
        "expect_text": text,
        **{k: v for k, v in params.items() if k not in ("match_text",)},
    }
    draft, nid = draft_builder.add_node(draft, block_type="if_text_contains", params=p)
    _auto_connect(draft, last_node_id, nid)
    return nid


def _recipe_loop_n(
    draft: dict[str, Any],
    *,
    times: int,
    last_node_id: str | None,
) -> str:
    draft, nid = draft_builder.add_node(
        draft, block_type="loop_n", params={"times": max(1, int(times))}
    )
    _auto_connect(draft, last_node_id, nid)
    return nid


def _recipe_try_catch(draft: dict[str, Any], *, last_node_id: str | None) -> str:
    draft, nid = draft_builder.add_node(draft, block_type="try_catch", params={})
    _auto_connect(draft, last_node_id, nid)
    return nid


def _recipe_ocr_click_chain(
    draft: dict[str, Any],
    *,
    match_text: str,
    last_node_id: str | None,
    tool_trace: list[dict[str, Any]],
    runtime: ToolRuntime,
    artifacts: dict[str, Any],
) -> str:
    """
    Prefer a single ocr_recognize with match_text + click bound to its outputs.
    Falls back to ocr → locate_text → click if schemas differ.
    """
    text = (match_text or "").strip()
    if not text:
        raise ValueError("ocr_click 需要 match_text")

    # ocr_recognize with match_text — many Nexuz builds expose x/y outputs
    draft, ocr_id = draft_builder.add_node(
        draft,
        block_type="ocr_recognize",
        params={"match_text": text},
    )
    _auto_connect(draft, last_node_id, ocr_id)

    click_params = {
        "x": f"{{{{{ocr_id}.x}}}}",
        "y": f"{{{{{ocr_id}.y}}}}",
        "coordinate_mode": "screen_abs",
    }
    result = runtime.execute(
        "draft_add_node",
        {"type": "click", "params": click_params},
        draft=draft,
        artifacts=artifacts,
        tool_trace=tool_trace,
    )
    if not result.get("ok"):
        # If binding rejected somehow, still add click with bindings via builder
        draft, click_id = draft_builder.add_node(
            draft, block_type="click", params=click_params
        )
    else:
        click_id = str(result["node_id"])
    draft_builder.connect(draft, from_id=ocr_id, to_id=click_id, edge="next")
    return click_id

