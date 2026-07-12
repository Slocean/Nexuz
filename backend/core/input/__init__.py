"""Pluggable click capture / playback engine."""

from backend.core.input.provider_registry import get_provider_registry, reset_provider_registry_for_tests
from backend.core.input.resolve import effective_capture_mode, normalize_click_params
from backend.core.input.session import get_recording_session
from backend.core.input.types import ClickTarget

__all__ = [
    "ClickTarget",
    "effective_capture_mode",
    "get_provider_registry",
    "get_recording_session",
    "normalize_click_params",
    "reset_provider_registry_for_tests",
]
