"""Mouse/keyboard recorder using pynput → FlowModel node sequence."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from pynput import keyboard, mouse


class Recorder:
    def __init__(self, min_interval_ms: int = 50):
        self.min_interval_ms = min_interval_ms
        self._events: list[dict[str, Any]] = []
        self._last_ts: float | None = None
        self._recording = False
        self._mouse_listener: mouse.Listener | None = None
        self._key_listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._pressed_keys: set[str] = set()
        self._on_stop_hotkey: Callable[[], None] | None = None
        self._mods = {"ctrl": False, "shift": False, "alt": False}

    @property
    def recording(self) -> bool:
        return self._recording

    def set_stop_hotkey_callback(self, cb: Callable[[], None] | None) -> None:
        self._on_stop_hotkey = cb

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._events = []
            self._last_ts = time.time()
            self._recording = True
            self._pressed_keys.clear()
            self._mods = {"ctrl": False, "shift": False, "alt": False}

            self._mouse_listener = mouse.Listener(
                on_click=self._on_click,
                on_scroll=self._on_scroll,
            )
            self._key_listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._mouse_listener.start()
            self._key_listener.start()

    def stop(self) -> list[dict[str, Any]]:
        with self._lock:
            self._recording = False
            if self._mouse_listener:
                self._mouse_listener.stop()
                self._mouse_listener = None
            if self._key_listener:
                self._key_listener.stop()
                self._key_listener = None
            events = list(self._events)
            self._events = []
        return self._events_to_nodes(events)

    def _append(self, event: dict[str, Any]) -> None:
        now = time.time()
        if self._last_ts is not None:
            gap_ms = int((now - self._last_ts) * 1000)
            if gap_ms >= self.min_interval_ms:
                self._events.append({"kind": "delay", "ms": gap_ms})
        self._last_ts = now
        self._events.append(event)

    @staticmethod
    def _button_name(button) -> str:
        """Normalize pynput mouse button → left|right|middle."""
        try:
            name = str(getattr(button, "name", None) or button or "").lower()
            name = name.replace("button.", "").strip()
            if name == "right" or name.endswith(".right"):
                return "right"
            if name == "middle" or name.endswith(".middle"):
                return "middle"
            if name == "left" or name.endswith(".left"):
                return "left"
            if "right" in name:
                return "right"
            if "middle" in name:
                return "middle"
        except Exception:
            pass
        try:
            if button == mouse.Button.right:
                return "right"
            if button == mouse.Button.middle:
                return "middle"
        except Exception:
            pass
        return "left"

    def _on_click(self, x, y, button, pressed):
        if not self._recording or not pressed:
            return
        btn = self._button_name(button)
        with self._lock:
            self._append(
                {
                    "kind": "click",
                    "x": int(x),
                    "y": int(y),
                    "button": btn,
                    "click_type": "single",
                }
            )

    def _on_scroll(self, x, y, dx, dy):
        if not self._recording:
            return
        if dx == 0 and dy == 0:
            return
        with self._lock:
            self._append(
                {
                    "kind": "scroll",
                    "x": int(x),
                    "y": int(y),
                    "dx": int(dx),
                    "dy": int(dy),
                }
            )

    def _key_name(self, key) -> str | None:
        try:
            if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
                return "ctrl"
            if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                return "shift"
            if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
                return "alt"
            fname = getattr(key, "name", None)
            if isinstance(fname, str) and fname.startswith("f") and fname[1:].isdigit():
                return fname.lower()
            if isinstance(key, keyboard.KeyCode):
                ch = key.char
                # With Ctrl held, char is often a control code / None — prefer vk for letters.
                if ch and len(ch) == 1 and ch.isalpha():
                    return ch.lower()
                vk = getattr(key, "vk", None)
                if isinstance(vk, int):
                    if 65 <= vk <= 90:  # A-Z
                        return chr(vk).lower()
                    if 97 <= vk <= 122:
                        return chr(vk).lower()
                if ch and len(ch) == 1 and 32 <= ord(ch) < 127:
                    return ch.lower()
            name = str(key).replace("Key.", "")
            mapping = {
                "ctrl_l": "ctrl",
                "ctrl_r": "ctrl",
                "alt_l": "alt",
                "alt_gr": "alt",
                "alt_r": "alt",
                "shift": "shift",
                "shift_r": "shift",
                "cmd": "win",
                "cmd_l": "win",
                "cmd_r": "win",
                "enter": "enter",
                "space": "space",
                "tab": "tab",
                "esc": "esc",
                "backspace": "backspace",
            }
            if name.startswith("f") and name[1:].isdigit():
                return name.lower()
            return mapping.get(name, name)
        except Exception:
            return None

    def _held_names(self) -> set[str]:
        with self._lock:
            held = set(self._pressed_keys)
        for mod, on in self._mods.items():
            if on:
                held.add(mod)
        return held

    def _is_stop_hotkey(self, name: str) -> bool:
        from backend.core.hotkey_prefs import record_stop_matches

        return record_stop_matches(name, self._held_names())

    def _stop_trigger_key(self) -> str:
        from backend.core.hotkey_prefs import get_record_stop_hotkey

        keys = get_record_stop_hotkey()
        return keys[-1] if keys else "f10"

    def _on_press(self, key):
        if not self._recording:
            return
        name = self._key_name(key)
        if name is None:
            return
        if name in ("ctrl", "shift", "alt"):
            self._mods[name] = True
            return
        # Configurable stop combo (default X+F10) → stop, do not record
        if self._is_stop_hotkey(name):
            from backend.core.hotkey_prefs import get_record_stop_hotkey

            with self._lock:
                for k in get_record_stop_hotkey()[:-1]:
                    self._pressed_keys.discard(k)
            cb = self._on_stop_hotkey
            if cb:
                threading.Thread(target=cb, daemon=True).start()
            return
        with self._lock:
            self._pressed_keys.add(name)

    def _on_release(self, key):
        if not self._recording:
            return
        name = self._key_name(key)
        if name is None:
            return
        if name in ("ctrl", "shift", "alt"):
            self._mods[name] = False
            return
        if name == self._stop_trigger_key():
            return
        with self._lock:
            keys = [k for k in self._pressed_keys if k]
            if name in self._pressed_keys:
                self._pressed_keys.discard(name)
            if not keys:
                return
            mods = {"ctrl", "alt", "shift", "win"}
            if name in mods:
                return
            combo = [k for k in keys if k in mods]
            combo.append(name)
            seen = set()
            ordered = []
            for k in combo:
                if k not in seen:
                    seen.add(k)
                    ordered.append(k)
            self._append({"kind": "key_press", "keys": ordered})

    def _events_to_nodes(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for ev in events:
            nid = f"node_{uuid.uuid4().hex[:8]}"
            kind = ev["kind"]
            if kind == "delay":
                nodes.append(
                    {
                        "id": nid,
                        "type": "delay",
                        "params": {"ms": int(ev["ms"])},
                    }
                )
            elif kind == "click":
                nodes.append(
                    {
                        "id": nid,
                        "type": "click",
                        "params": {
                            "x": ev["x"],
                            "y": ev["y"],
                            "button": ev["button"],
                            "click_type": ev.get("click_type", "single"),
                            "move_duration": 0,
                        },
                    }
                )
            elif kind == "key_press":
                nodes.append(
                    {
                        "id": nid,
                        "type": "key_press",
                        "params": {"keys": ev["keys"]},
                    }
                )
            elif kind == "scroll":
                dx = int(ev.get("dx") or 0)
                dy = int(ev.get("dy") or 0)
                if abs(dy) >= abs(dx):
                    direction = "up" if dy > 0 else "down"
                    clicks = max(1, abs(dy))
                else:
                    direction = "right" if dx > 0 else "left"
                    clicks = max(1, abs(dx))
                nodes.append(
                    {
                        "id": nid,
                        "type": "mouse_scroll",
                        "params": {
                            "x": ev["x"],
                            "y": ev["y"],
                            "move_first": "true",
                            "direction": direction,
                            "clicks": clicks,
                        },
                    }
                )
        for i, n in enumerate(nodes):
            if i + 1 < len(nodes):
                n["next"] = nodes[i + 1]["id"]
            else:
                n["next"] = None
        return nodes


_recorder = Recorder()


def get_recorder() -> Recorder:
    return _recorder
