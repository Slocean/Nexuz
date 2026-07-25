"""Deterministic recipe macros: FlowSpec steps → draft mutations."""

from __future__ import annotations

from typing import Any

from backend.core.ai import draft_builder
from backend.core.ai.lc.structured import FlowSpec, PlanStep, parse_flow_spec
from backend.core.ai.tool_runtime import ToolRuntime


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

    if action == "recipe":
        name = (step.recipe or "").strip()
        if name == "ocr_click_chain" or name == "ocr_click":
            return _recipe_ocr_click_chain(
                draft,
                match_text=step.match_text or params.get("match_text") or params.get("text") or "",
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
        raise ValueError(f"未知 recipe: {name}")

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


def heuristic_plan_from_text(text: str) -> FlowSpec:
    """Lightweight fallback when structured output fails (tests / offline)."""
    t = (text or "").strip()
    steps: list[PlanStep] = []
    needs_locate = False
    locate_texts: list[str] = []
    lower = t.lower()

    # delay
    import re

    m = re.search(r"(?:等待|wait|delay)\s*(\d+)\s*(秒|s|ms|毫秒)?", t, re.I)
    if m:
        n = int(m.group(1))
        unit = (m.group(2) or "秒").lower()
        ms = n if unit in ("ms", "毫秒") else n * 1000
        steps.append(PlanStep(action="delay", params={"ms": ms}))

    # type
    m = re.search(r"(?:输入|type)\s*[「\"']?(.+?)[」\"']?(?:再|然后|$)", t)
    if not m:
        m = re.search(r"输入\s+(\S+)", t)
    if m:
        steps.append(PlanStep(action="type_text", params={"text": m.group(1).strip()}))

    # click text
    m = re.search(r"(?:点击|点)\s*[「\"'](.+?)[」\"']", t)
    if not m:
        m = re.search(r"(?:点击|点)\s*(屏幕上的)?(.+)", t)
    if m:
        label = (m.group(m.lastindex) or "").strip()
        if label and label not in ("屏幕上的",):
            needs_locate = True
            locate_texts.append(label)
            steps.append(
                PlanStep(action="ocr_click", match_text=label, recipe="ocr_click_chain")
            )

    if not steps:
        # generic delay+type if "hello" mentioned
        if "hello" in lower:
            steps = [
                PlanStep(action="delay", params={"ms": 1000}),
                PlanStep(action="type_text", params={"text": "hello"}),
            ]

    return FlowSpec(
        intent_summary=t[:80],
        needs_locate=needs_locate,
        locate_texts=locate_texts,
        steps=steps,
    )
