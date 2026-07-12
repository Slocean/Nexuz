"""Frida UI sequence/single click capture."""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.core.input.frida.session_manager import get_frida_session_manager
from backend.core.input.provider_base import CaptureProvider
from backend.core.input.resolve import recorded_click_to_node_params
from backend.core.input.types import (
    ERROR_CANCELLED,
    ERROR_FRIDA_NOT_ATTACHED,
    ProviderCapabilities,
    api_error,
    api_ok,
)


def _items_to_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("hierarchy_path") or "").strip()
        if not path:
            continue
        params = recorded_click_to_node_params(
            mode="frida_ui",
            button=str(item.get("button") or "left"),
            frida_ui={
                "hierarchy_path": path,
                "component_type": str(item.get("component_type") or "UnityEngine.UI.Button"),
                "sibling_index": int(item.get("sibling_index", 0) or 0),
                "display_name": str(item.get("display_name") or ""),
            },
        )
        nid = f"node_{uuid.uuid4().hex[:8]}"
        nodes.append({"id": nid, "type": "click", "params": params})
    for i, n in enumerate(nodes):
        n["next"] = nodes[i + 1]["id"] if i + 1 < len(nodes) else None
    return nodes


class FridaUiCaptureProvider(CaptureProvider):
    mode = "frida_ui"
    capabilities = ProviderCapabilities(
        modes=["sequence", "single"],
        buttons=["left", "right", "middle"],
        requires_attach=True,
        label="Frida UI",
    )

    def is_available(self) -> tuple[bool, str | None]:
        mgr = get_frida_session_manager()
        st = mgr.status()
        if not st.get("attached"):
            return False, "请先连接 Frida（设置页或 API frida_attach）"
        if not st.get("hooked"):
            return False, st.get("last_error") or "Frida UI Hook 未就绪"
        return True, None

    def start_sequence(self, *, min_interval_ms: int = 50) -> None:
        ok, msg = self.is_available()
        if not ok:
            raise RuntimeError(msg or "Frida UI 不可用")
        mgr = get_frida_session_manager()
        result = mgr.call_export("startSequenceRecord")
        if isinstance(result, dict) and not result.get("ok", True):
            raise RuntimeError(result.get("error") or "无法开始 Frida 序列录制")

    def stop_sequence(self) -> list[dict[str, Any]]:
        mgr = get_frida_session_manager()
        result = mgr.call_export("stopSequenceRecord")
        items: list[dict[str, Any]] = []
        if isinstance(result, dict):
            raw = result.get("items") or []
            if isinstance(raw, list):
                items = [x for x in raw if isinstance(x, dict)]
        return _items_to_nodes(items)

    def pick_single(self, *, timeout_s: float = 120) -> dict[str, Any]:
        ok, msg = self.is_available()
        if not ok:
            return api_error(ERROR_FRIDA_NOT_ATTACHED, msg or "Frida 未连接")
        mgr = get_frida_session_manager()
        try:
            mgr.call_export("setRecordTarget", True)
        except Exception as exc:
            return api_error(ERROR_FRIDA_NOT_ATTACHED, str(exc))

        deadline = time.time() + float(timeout_s)
        item: dict[str, Any] | None = None
        while time.time() < deadline:
            try:
                drained = mgr.call_export("drainRecorded")
            except Exception as exc:
                return api_error(ERROR_FRIDA_NOT_ATTACHED, str(exc))
            if isinstance(drained, dict):
                items = drained.get("items") or []
                if isinstance(items, list) and items:
                    first = items[0]
                    if isinstance(first, dict):
                        item = first
                        break
            time.sleep(0.05)

        try:
            mgr.call_export("setRecordTarget", False)
        except Exception:
            pass

        if not item:
            return api_error(ERROR_CANCELLED, "未捕获到游戏内 UI 点击", cancelled=True)

        params = recorded_click_to_node_params(
            mode="frida_ui",
            button=str(item.get("button") or "left"),
            frida_ui={
                "hierarchy_path": str(item.get("hierarchy_path") or ""),
                "component_type": str(item.get("component_type") or "UnityEngine.UI.Button"),
                "sibling_index": int(item.get("sibling_index", 0) or 0),
                "display_name": str(item.get("display_name") or ""),
            },
        )
        return api_ok(params=params, button=params.get("button"), frida_ui=params.get("frida_ui"))
