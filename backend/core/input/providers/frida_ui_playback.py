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
        if not st.get("hooked"):
            raise RuntimeError(
                f"{ERROR_STABLE_ID_RESOLVE_FAILED}: UI Hook 未就绪，无法回放。"
                f"详情: {st.get('last_error') or '请重新连接并确认 GameAssembly / il2cpp_runtime_invoke 可用'}"
            )

        if not target.frida_ui:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: 缺少 frida_ui 目标")

        stable = target.frida_ui.to_dict()
        ok, msg = validate_stable_id(stable)
        if not ok:
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: {msg}")

        if isinstance(context, dict) and context.get("frida_clear_cache"):
            mgr.clear_resolve_cache()

        # Single RPC: script invokeClick does one findByPath + press (no Python pre-resolve).
        try:
            result = mgr.call_export("invokeClick", stable, target.button or "left")
        except Exception as exc:
            err = str(exc)
            if "access violation" in err.lower() or "0x0" in err:
                raise RuntimeError(
                    f"{ERROR_STABLE_ID_RESOLVE_FAILED}: 回放时访问了空指针。"
                    "请：1) 完全重启 Nexuz 后重新连接 Frida；2) 确认 Hook 就绪；"
                    "3) 在当前界面重新录入该点击；4) 不要切走界面再运行。"
                ) from exc
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: invoke 失败: {exc}") from exc

        if isinstance(result, dict) and not result.get("ok", True):
            err = str(result.get("error") or result.get("message") or "invoke failed")
            if "access violation" in err.lower() or "0x0" in err:
                raise RuntimeError(
                    f"{ERROR_STABLE_ID_RESOLVE_FAILED}: 回放空指针。"
                    "请：1) 断开并重新连接游戏；2) 停在原界面重新录入该点击；3) 确认状态为 Hook 就绪后再运行。"
                )
            raise RuntimeError(f"{ERROR_STABLE_ID_RESOLVE_FAILED}: {err}")
        return {"ok": True, "mode": "frida_ui", "result": result, "button": target.button}
