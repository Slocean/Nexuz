"""Headless smoke test for registry + interpreter (no GUI)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.registry import register_all_blocks, get_schemas
from backend.core.interpreter import FlowInterpreter


def main():
    register_all_blocks()
    schemas = get_schemas()
    types = sorted(s["type"] for s in schemas)
    print("registered:", types)
    assert "click" in types and "loop_n" in types and "if_color_match" in types

    flow_path = ROOT / "examples" / "demo_color_loop.flow.json"
    flow = json.loads(flow_path.read_text(encoding="utf-8"))

    events = []

    def emit(event, payload):
        events.append((event, payload))
        print(event, payload.get("node_id") or payload)

    interp = FlowInterpreter(emit=emit)
    interp.run_flow(flow, step_mode=False)
    interp.wait_until_idle(timeout=30)
    assert any(e[0] == "flow_finished" for e in events), events
    finished = [e for e in events if e[0] == "flow_finished"][-1][1]
    assert finished.get("ok") is True, finished
    print("SMOKE OK")


if __name__ == "__main__":
    main()
