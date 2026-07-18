"""Shared helpers for block handlers."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import mss
import pyautogui
from PIL import Image

from backend.core.dpi import (
    get_dpi_for_point,
    get_dpi_scale,
    get_dpi_scale_for_point,
    monitor_info_at_point,
    screen_size_logical,
    virtual_screen_rect,
    virtual_screen_size,
)

# RPA needs clicks near screen edges; corner fail-safe fights that.
# Emergency stop is the app「停止」button, not moving the mouse to a corner.
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01


def interruptible_sleep(
    seconds: float,
    should_stop: Callable[[], bool] | None = None,
    *,
    cooperate: Callable[[], None] | None = None,
    chunk: float = 0.05,
) -> None:
    """Sleep in small chunks so flow pause/stop can interrupt mid-wait.

    - ``should_stop``: polled each chunk; raises InterruptedError when true.
    - ``cooperate``: called before each chunk (interpreter pause wait). Time spent
      blocked inside cooperate does **not** count toward the delay.
    """
    if seconds <= 0:
        return
    check = should_stop or (lambda: False)
    remaining = float(seconds)
    while remaining > 0:
        if check():
            raise InterruptedError("流程已停止")
        if cooperate is not None:
            cooperate()  # may block while paused; may raise InterruptedError
            if check():
                raise InterruptedError("流程已停止")
        slice_s = min(chunk, remaining)
        time.sleep(slice_s)
        remaining -= slice_s


def pre_step_delay_ms(index: int, item_delay: Any, *, default_interval: int = 0) -> int:
    """Milliseconds to wait *before* step ``index`` (0-based).

    Matches UI「本点/本步前延迟」:
    - Explicit ``item_delay`` always wins (including 0).
    - Empty on the first step → 0 (do not apply global interval before #1).
    - Empty on later steps → ``default_interval`` (点间/步间全局延迟).
    """
    if item_delay is not None and item_delay != "":
        try:
            return max(0, int(float(item_delay)))
        except (TypeError, ValueError):
            return 0
    if int(index) <= 0:
        return 0
    try:
        return max(0, int(float(default_interval)))
    except (TypeError, ValueError):
        return 0


def sleep_pre_step(
    index: int,
    item_delay: Any,
    *,
    default_interval: int = 0,
    should_stop: Callable[[], bool] | None = None,
    cooperate: Callable[[], None] | None = None,
) -> None:
    """Apply :func:`pre_step_delay_ms` via :func:`interruptible_sleep`."""
    wait = pre_step_delay_ms(index, item_delay, default_interval=default_interval)
    if wait > 0:
        interruptible_sleep(wait / 1000.0, should_stop, cooperate=cooperate)


def validate_point(x: int, y: int) -> tuple[int, int]:
    """Clamp point into the virtual desktop (all monitors)."""
    left, top, right, bottom = virtual_screen_rect()
    cx = max(left, min(int(x), right - 1))
    cy = max(top, min(int(y), bottom - 1))
    return cx, cy


def validate_region(region: list | tuple) -> tuple[int, int, int, int]:
    if not region or len(region) != 4:
        raise ValueError("region 必须是 [x1,y1,x2,y2]")
    x1, y1, x2, y2 = [int(v) for v in region]
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效区域: {region}")
    left, top, right, bottom = virtual_screen_rect()
    # Clamp soft edges for scaled restores / multi-monitor
    x1 = max(left, min(x1, right - 1))
    y1 = max(top, min(y1, bottom - 1))
    x2 = max(x1 + 1, min(x2, right))
    y2 = max(y1 + 1, min(y2, bottom))
    return x1, y1, x2, y2


def pack_coord_space(x: int | None = None, y: int | None = None) -> dict[str, Any]:
    left, top, width, height = virtual_screen_size()
    pw, ph = screen_size_logical()
    space: dict[str, Any] = {
        "w": width,
        "h": height,
        "left": left,
        "top": top,
        "primary_w": pw,
        "primary_h": ph,
        "dpi_scale": get_dpi_scale(),
    }
    if x is not None and y is not None:
        mon = monitor_info_at_point(int(x), int(y))
        space["point_dpi"] = mon.get("dpi")
        space["point_dpi_scale"] = mon.get("dpi_scale")
        if isinstance(mon.get("monitor"), dict):
            space["monitor"] = mon["monitor"]
    return space


def pack_point(x: int, y: int) -> dict[str, Any]:
    left, top, width, height = virtual_screen_size()
    x, y = validate_point(x, y)
    packed = {
        "x": int(x),
        "y": int(y),
        "coordinate_mode": "screen_abs",
        "point_norm": [(x - left) / width, (y - top) / height],
        "coord_space": pack_coord_space(x, y),
        "monitor_dpi": get_dpi_for_point(x, y),
        "monitor_dpi_scale": get_dpi_scale_for_point(x, y),
    }
    try:
        from backend.core.window_coords import capture_window_target

        target = capture_window_target(x, y)
        if target:
            packed["window_target"] = target
    except Exception:
        pass
    return packed


def pack_region(region: list | tuple) -> dict[str, Any]:
    x1, y1, x2, y2 = validate_region(region)
    left, top, width, height = virtual_screen_size()
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    return {
        "region": [x1, y1, x2, y2],
        "region_norm": [
            (x1 - left) / width,
            (y1 - top) / height,
            (x2 - left) / width,
            (y2 - top) / height,
        ],
        "coord_space": pack_coord_space(cx, cy),
        "monitor_dpi": get_dpi_for_point(cx, cy),
    }


def _space_origin_size(space: dict) -> tuple[int, int, int, int, bool]:
    """Return (left, top, w, h, has_virtual_origin) from coord_space."""
    left, top, vw, vh = virtual_screen_size()
    if not isinstance(space, dict):
        return left, top, vw, vh, True
    sw = int(space.get("w") or 0)
    sh = int(space.get("h") or 0)
    if sw <= 0 or sh <= 0:
        return left, top, vw, vh, True
    has_origin = "left" in space or "top" in space
    ox = int(space.get("left") or 0) if has_origin else 0
    oy = int(space.get("top") or 0) if has_origin else 0
    return ox, oy, sw, sh, has_origin


def _as_coord_int(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def point_looks_unconfigured(params: dict, x_key: str = "x", y_key: str = "y") -> bool:
    """True when coords are still the (0,0) default with no norm / frida target."""
    if isinstance(params.get("point_norm"), (list, tuple)) and len(params.get("point_norm") or []) == 2:
        return False
    frida = params.get("frida_ui")
    if isinstance(frida, dict) and frida.get("hierarchy_path"):
        return False
    window_target = params.get("window_target")
    if isinstance(window_target, dict):
        wnorm = window_target.get("point_norm")
        if isinstance(wnorm, (list, tuple)) and len(wnorm) == 2:
            return False
    return _as_coord_int(params.get(x_key), 0) == 0 and _as_coord_int(params.get(y_key), 0) == 0


def require_configured_point(
    params: dict,
    *,
    x_key: str = "x",
    y_key: str = "y",
    label: str = "坐标",
) -> None:
    """Raise if the point was never picked (avoids silently hitting screen top-left)."""
    if point_looks_unconfigured(params, x_key, y_key):
        raise ValueError(f"请先取点：{label}仍为 (0,0)，疑似未配置")


def resolve_point(params: dict, x_key: str = "x", y_key: str = "y") -> tuple[int, int]:
    """
    Resolve a point from absolute coords, optional *_norm, or scale via coord_space.
    Prefer absolute x/y when present; point_norm is a fallback for resolution changes.
    """
    left, top, vw, vh = virtual_screen_size()
    mode = str(
        params.get("coordinate_mode", params.get("coord_mode", "screen_abs"))
        or "screen_abs"
    ).strip()

    raw_x = params.get(x_key)
    raw_y = params.get(y_key)
    has_abs = raw_x is not None and raw_x != "" and raw_y is not None and raw_y != ""
    norm = params.get("point_norm")
    has_norm = (
        isinstance(norm, (list, tuple))
        and len(norm) == 2
        and all(isinstance(v, (int, float)) for v in norm)
    )

    if mode == "window_client":
        target = params.get("window_target")
        if not isinstance(target, dict):
            nested = params.get("coord")
            if isinstance(nested, dict):
                target = nested.get("window_target")
        from backend.core.window_coords import resolve_window_point

        x, y, _hwnd = resolve_window_point(target)
        return validate_point(x, y)

    if mode == "virtual_norm" and has_norm:
        x = int(round(left + float(norm[0]) * vw))
        y = int(round(top + float(norm[1]) * vh))
        return validate_point(x, y)

    # Existing flows are screen-absolute. Never silently rescale an absolute
    # desktop point when monitor geometry changes.
    if has_abs:
        return validate_point(int(round(float(raw_x))), int(round(float(raw_y))))

    # Legacy fallback for records that only contain point_norm.
    if has_norm:
        x = int(round(left + float(norm[0]) * vw))
        y = int(round(top + float(norm[1]) * vh))
        return validate_point(x, y)

    return validate_point(0, 0)


def resolve_region_from_params(
    params: dict,
    region_key: str = "region",
    norm_key: str = "region_norm",
) -> tuple[int, int, int, int] | None:
    """
    Resolve [x1,y1,x2,y2] preferring absolute region, then region_norm.
    Returns None if no region configured.
    """
    left, top, vw, vh = virtual_screen_size()
    space = params.get("coord_space") if isinstance(params.get("coord_space"), dict) else {}
    ox, oy, sw, sh, has_origin = _space_origin_size(space)

    region = params.get(region_key)
    if region and len(region) == 4:
        x1, y1, x2, y2 = [int(v) for v in region]
        if has_origin and sw > 0 and sh > 0 and (sw != vw or sh != vh or ox != left or oy != top):
            x1 = int(round(left + (x1 - ox) * (vw / sw)))
            y1 = int(round(top + (y1 - oy) * (vh / sh)))
            x2 = int(round(left + (x2 - ox) * (vw / sw)))
            y2 = int(round(top + (y2 - oy) * (vh / sh)))
        return validate_region([x1, y1, x2, y2])

    norm = params.get(norm_key)
    if (
        isinstance(norm, (list, tuple))
        and len(norm) == 4
        and all(isinstance(v, (int, float)) for v in norm)
    ):
        x1 = int(round(ox + float(norm[0]) * sw))
        y1 = int(round(oy + float(norm[1]) * sh))
        x2 = int(round(ox + float(norm[2]) * sw))
        y2 = int(round(oy + float(norm[3]) * sh))
        if has_origin and (sw != vw or sh != vh or ox != left or oy != top):
            x1 = int(round(left + (x1 - ox) * (vw / sw)))
            y1 = int(round(top + (y1 - oy) * (vh / sh)))
            x2 = int(round(left + (x2 - ox) * (vw / sw)))
            y2 = int(round(top + (y2 - oy) * (vh / sh)))
        return validate_region([x1, y1, x2, y2])

    return None


def grab_region(x1: int, y1: int, x2: int, y2: int) -> Image.Image:
    with mss.mss() as sct:
        monitor = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def pixel_color(x: int, y: int) -> str:
    x, y = validate_point(x, y)
    img = grab_region(x, y, x + 1, y + 1)
    r, g, b = img.getpixel((0, 0))
    return f"#{r:02X}{g:02X}{b:02X}"


def region_dominant_color(region: list | tuple) -> str:
    x1, y1, x2, y2 = validate_region(region)
    img = grab_region(x1, y1, x2, y2)
    img = img.resize((max(1, img.width // 4), max(1, img.height // 4)))
    colors = list(img.getdata())
    quantized = [((r // 16) * 16, (g // 16) * 16, (b // 16) * 16) for r, g, b in colors]
    (r, g, b), _ = Counter(quantized).most_common(1)[0]
    return f"#{r:02X}{g:02X}{b:02X}"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"无效颜色: {hex_color}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def color_distance(c1: str, c2: str) -> float:
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return ((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) ** 0.5


def _imread_template(path: Path):
    """Read a template unchanged; supports Unicode paths and preserves PNG alpha."""
    import cv2
    import numpy as np

    raw = path.read_bytes()
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    return img


def _best_template_match(hay, tpl, mask=None):
    """Return an intuitive 0..1 similarity and its best location.

    CCOEFF is useful for structure but can report surprisingly low values after
    harmless rendering/color changes.  Pixel RMSE makes identical and visually
    near-identical images score as users expect.  Transparent template pixels
    are excluded from the RMSE comparison.
    """
    import cv2
    import numpy as np

    channels = int(tpl.shape[2]) if tpl.ndim == 3 else 1
    if mask is not None:
        valid = np.asarray(mask, dtype=np.float32)
        if valid.ndim == 2 and channels > 1:
            valid = np.repeat(valid[:, :, None], channels, axis=2)
        weight = float(np.sum(valid * valid))
        if weight <= 0:
            valid = None
        else:
            squared_error = cv2.matchTemplate(hay, tpl, cv2.TM_SQDIFF, mask=valid)
            similarity = 1.0 - np.sqrt(np.maximum(squared_error, 0.0) / weight) / 255.0
            similarity = np.nan_to_num(similarity, nan=0.0, posinf=0.0, neginf=0.0)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(similarity)
            return max(0.0, min(1.0, float(max_val))), max_loc

    pixel_count = max(1, int(tpl.shape[0]) * int(tpl.shape[1]) * channels)
    squared_error = cv2.matchTemplate(hay, tpl, cv2.TM_SQDIFF)
    pixel_similarity = 1.0 - np.sqrt(np.maximum(squared_error, 0.0) / pixel_count) / 255.0
    pixel_similarity = np.nan_to_num(
        pixel_similarity, nan=0.0, posinf=0.0, neginf=0.0
    )
    _min_val, pixel_score, _min_loc, pixel_loc = cv2.minMaxLoc(pixel_similarity)

    # Keep correlation as a second signal for templates whose brightness or
    # contrast changed, while avoiding its NaN/Inf behavior on flat images.
    correlation = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    correlation = np.nan_to_num(correlation, nan=0.0, posinf=0.0, neginf=0.0)
    _min_val, corr_score, _min_loc, corr_loc = cv2.minMaxLoc(correlation)
    if float(corr_score) > float(pixel_score):
        return max(0.0, min(1.0, float(corr_score))), corr_loc
    return max(0.0, min(1.0, float(pixel_score))), pixel_loc


def match_template_on_screen(
    template_path: str,
    *,
    search_region: list | tuple | None = None,
    threshold: float = 0.8,
) -> dict[str, Any]:
    """Shared template match used by find_image and OCR anchor."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "未安装找图依赖，请执行: pip install opencv-python-headless"
        ) from exc

    path = Path(str(template_path).strip())
    if not path.is_file():
        raise FileNotFoundError(f"模板图片不存在: {template_path}")

    try:
        template = _imread_template(path)
    except OSError as exc:
        raise ValueError(f"无法读取模板图片: {template_path}") from exc
    if template is None:
        raise ValueError(f"无法读取模板图片: {template_path}")
    if template.ndim == 2:
        tpl = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
        mask = None
    elif template.shape[2] == 4:
        tpl = template[:, :, :3]
        alpha = template[:, :, 3]
        # Ignore transparent and antialiased edge pixels: their stored RGB is
        # not the color produced when the image is rendered over a background.
        mask = (alpha >= 250).astype(np.float32)
        if not np.any(mask):
            mask = (alpha > 0).astype(np.float32)
    else:
        tpl = template[:, :, :3]
        mask = None

    if search_region:
        x1, y1, x2, y2 = validate_region(search_region)
        hay_img = grab_region(x1, y1, x2, y2)
        origin_x, origin_y = x1, y1
    else:
        # Must use virtual desktop (same as capture_desktop / 截模板), not primary-only (0,0,w,h).
        left, top, vw, vh = virtual_screen_size()
        hay_img = grab_region(left, top, left + vw, top + vh)
        origin_x, origin_y = left, top

    hay = cv2.cvtColor(np.array(hay_img), cv2.COLOR_RGB2BGR)
    th, tw = int(tpl.shape[0]), int(tpl.shape[1])
    hh, hw = int(hay.shape[0]), int(hay.shape[1])
    if hh < th or hw < tw:
        # Common when search_region ≈ template size but clamp/rounding shrank hay by 1px.
        # Crop template to hay so an "identical" frame still matches instead of score=0.
        if hh < 1 or hw < 1:
            return {
                "found": False,
                "x": 0,
                "y": 0,
                "score": 0.0,
                "path": "",
                "left": 0,
                "top": 0,
                "width": 0,
                "height": 0,
                "message": f"搜索区域过小（{hw}x{hh}），模板为 {tw}x{th}",
            }
        tpl = tpl[0:hh, 0:hw]
        if mask is not None:
            mask = mask[0:hh, 0:hw]
        th, tw = hh, hw

    max_val, max_loc = _best_template_match(hay, tpl, mask)
    score = round(max_val, 4)
    found = score >= float(threshold)
    left = int(origin_x + max_loc[0])
    top = int(origin_y + max_loc[1])
    cx = left + tw // 2
    cy = top + th // 2

    # Always save the best-match crop so users can preview even when below threshold.
    match_path = ""
    try:
        from time import strftime

        from backend.paths import get_data_dir

        crop = grab_region(left, top, left + tw, top + th)
        shots = get_data_dir(create=True) / "screenshots"
        shots.mkdir(parents=True, exist_ok=True)
        out = shots / f"match_{strftime('%Y%m%d_%H%M%S')}.png"
        crop.save(out)
        match_path = str(out.resolve())
    except Exception:
        match_path = ""

    return {
        "found": found,
        "x": cx,
        "y": cy,
        "score": score,
        "path": match_path,
        "left": left,
        "top": top,
        "width": tw,
        "height": th,
    }
