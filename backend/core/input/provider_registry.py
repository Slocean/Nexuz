"""Register capture/playback providers by mode."""

from __future__ import annotations

from typing import Any

from backend.core.input.provider_base import CaptureProvider, PlaybackProvider
from backend.core.input.types import ERROR_INVALID_MODE, ERROR_PROVIDER_UNAVAILABLE, api_error


class ProviderRegistry:
    def __init__(self) -> None:
        self._capture: dict[str, CaptureProvider] = {}
        self._playback: dict[str, PlaybackProvider] = {}

    def register_capture(self, provider: CaptureProvider) -> None:
        self._capture[provider.mode] = provider

    def register_playback(self, provider: PlaybackProvider) -> None:
        self._playback[provider.mode] = provider

    def get_capture(self, mode: str) -> CaptureProvider | None:
        return self._capture.get(mode)

    def get_playback(self, mode: str) -> PlaybackProvider | None:
        return self._playback.get(mode)

    def require_capture(self, mode: str) -> CaptureProvider | dict[str, Any]:
        provider = self._capture.get(mode)
        if not provider:
            return api_error(ERROR_INVALID_MODE, f"未知录入模式: {mode}")
        ok, msg = provider.is_available()
        if not ok:
            return api_error(ERROR_PROVIDER_UNAVAILABLE, msg or f"录入模式不可用: {mode}")
        return provider

    def require_playback(self, mode: str) -> PlaybackProvider | dict[str, Any]:
        provider = self._playback.get(mode)
        if not provider:
            return api_error(ERROR_INVALID_MODE, f"未知回放模式: {mode}")
        return provider

    def list_providers(self) -> list[dict[str, Any]]:
        modes = sorted(set(self._capture) | set(self._playback))
        rows: list[dict[str, Any]] = []
        for mode in modes:
            cap = self._capture.get(mode)
            play = self._playback.get(mode)
            available = True
            message = None
            caps = None
            if cap:
                available, message = cap.is_available()
                caps = cap.capabilities.to_dict()
            rows.append(
                {
                    "mode": mode,
                    "has_capture": cap is not None,
                    "has_playback": play is not None,
                    "available": available,
                    "message": message,
                    "capabilities": caps,
                }
            )
        return rows


_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        _bootstrap(_registry)
    return _registry


def reset_provider_registry_for_tests() -> None:
    global _registry
    _registry = None


def _bootstrap(registry: ProviderRegistry) -> None:
    from backend.core.input.providers.coord_capture import CoordCaptureProvider
    from backend.core.input.providers.coord_playback import CoordPlaybackProvider
    from backend.core.input.providers.frida_ui_capture import FridaUiCaptureProvider
    from backend.core.input.providers.frida_ui_playback import FridaUiPlaybackProvider

    registry.register_capture(CoordCaptureProvider())
    registry.register_playback(CoordPlaybackProvider())
    registry.register_capture(FridaUiCaptureProvider())
    registry.register_playback(FridaUiPlaybackProvider())
