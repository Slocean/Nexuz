"""Frida UI click playback."""

from __future__ import annotations

from typing import Any

from backend.core.input.frida.session_manager import get_frida_session_manager
from backend.core.input.frida.stable_id import validate_stable_id
from backend.core.input.provider_base import PlaybackProvider
from backend.core.input.types import (
    ERROR_FRIDA_NOT_ATTACHED,
    ERROR_STABLE_ID_RESOLVE_FAILED,
    ClickTarget,
)


class FridaUiPlaybackProvider(PlaybackProvider):
    mode = "frida_ui"

    def execute(self, target: ClickTarget, context: dict[str, Any] | None = None) -> dict[str, Any]:
        mgr = get_frida_session_manager()
        st = mgr.status()
        if not st.get("attached"):
            raise RuntimeError(f"{ERROR_FRIDA_NOT_ATTACHED}: Frida 未连接，无法回放 UI 点击")

        if not target.frida_ui:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: 缺少 frida_ui 目标")

        stable = target.frida_ui.to_dict()
        ok, msg = validate_stable_id(stable)
        if not ok:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: {msg}")

        use_cache = True
        if isinstance(context, dict) and context.get("frida_clear_cache"):
            mgr.clear_resolve_cache()
        try:
            mgr.resolve_ptr(stable, use_cache=use_cache)
        except Exception as exc:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: {exc}") from exc

        try:
            result = mgr.call_export("invokeClick", stable, target.button or "left")
        except Exception as exc:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: invoke 失败: {exc}") from exc

        if isinstance(result, dict) and not result.get("ok", True):
            raise RuntimeError(
                f"{ERROR_STABLE_ID_RESOLVE_FAILED}: {result.get('error') or result.get('message') or 'invoke failed'}"
            )
        return {"ok": True, "mode": "frida_ui", "result": result, "button": target.button}
