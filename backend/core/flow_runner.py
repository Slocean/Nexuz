"""共用流程运行链：Api（桌面）与 ServerApi（无头）共享 parse→validate→启动。

UI 相关分支（运行监视器、热键提示、run controls）留在 Api；本模块只做
无 UI 的校验与解释器启动，保证两种宿主跑同一条运行链、不复制逻辑。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from backend.core.block_params_validate import validate_flow_params
from backend.core.interpreter import get_interpreter
from backend.core.runtime_log import get_runtime_log_manager

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional dependency
    Draft202012Validator = None  # type: ignore


def load_flow_schema() -> dict | None:
    path = Path(__file__).resolve().parent.parent / "schemas" / "flow_schema.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_flow(flow: Any, schema: dict | None) -> str | None:
    if not isinstance(flow, dict):
        return "FlowModel 必须是对象"
    if "nodes" not in flow or not isinstance(flow["nodes"], dict):
        return "缺少 nodes 字典"
    if "entry" not in flow:
        return "缺少 entry"
    if flow["entry"] and flow["entry"] not in flow["nodes"]:
        return f"entry 节点不存在: {flow['entry']}"
    if schema and Draft202012Validator:
        try:
            Draft202012Validator(schema).validate(flow)
        except Exception as exc:
            return str(exc)
    return None


def prepare_flow(
    flow_json: Any,
    *,
    schema: dict | None = None,
) -> tuple[dict | None, str | None, list[dict] | None]:
    """parse + 结构校验 + 参数校验。

    返回 (flow, error, validation_issues)：error 为 None 表示通过；
    参数校验未通过时 error 为汇总文案、issues 带明细。
    """
    flow = json.loads(flow_json) if isinstance(flow_json, str) else flow_json
    err = validate_flow(flow, schema)
    if err:
        return None, err, None
    issues = validate_flow_params(flow)
    blocking = [i for i in issues if i.get("level") == "error"]
    if blocking:
        return None, f"流程参数校验未通过（{len(blocking)} 处）", issues
    return flow, None, None


def start_flow(
    flow: dict,
    *,
    emit: Callable[[str, dict], Any],
    step_mode: bool = False,
    debug_mode: bool = False,
    breakpoints: Any = None,
) -> dict:
    """启动解释器（含"暂停中→续跑"分支与运行日志会话）。异常向上抛。

    返回 {ok, started, resumed, debug_mode, run_log}；resumed 时无 started
    等键的稳定保证，调用方按 resumed 分支处理。
    """
    interp = get_interpreter(emit=emit)

    bps = breakpoints
    if isinstance(bps, str):
        try:
            bps = json.loads(bps)
        except Exception:
            bps = None
    if bps is None:
        bps = flow.get("breakpoints")
    if not isinstance(bps, list):
        bps = []

    # 已暂停 / 停在断点的会话：续跑，不重新启动。
    if interp.running and getattr(interp, "paused", False):
        result = interp.run_flow(
            flow,
            step_mode=bool(step_mode),
            debug_mode=bool(debug_mode) or bool(step_mode),
            breakpoints=bps,
        )
        return {"ok": True, "resumed": True, **(result or {})}

    in_debug = bool(debug_mode) or bool(step_mode)
    logs = get_runtime_log_manager().start(flow)
    try:
        result = interp.run_flow(
            flow,
            step_mode=bool(step_mode),
            debug_mode=in_debug,
            breakpoints=bps,
        )
    except Exception as exc:
        get_runtime_log_manager().finish({"ok": False, "error": str(exc)})
        raise
    started = bool((result or {}).get("started", True))
    resumed = bool((result or {}).get("resumed"))
    return {
        "ok": True,
        "started": started,
        "resumed": resumed,
        "debug_mode": in_debug,
        "run_log": logs.info(),
    }
