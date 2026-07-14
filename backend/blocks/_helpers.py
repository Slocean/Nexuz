"""Shared helpers for block handlers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import mss
import pyautogui
from PIL import Image

from backend.core.dpi import (
    get_dpi_scale,
    screen_size_logical,
    virtual_screen_rect,
    virtual_screen_size,
)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01


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


def pack_coord_space() -> dict[str, Any]:
    left, top, width, height = virtual_screen_size()
    pw, ph = screen_size_logical()
    return {
        "w": width,
        "h": height,
        "left": left,
        "top": top,
        "primary_w": pw,
        "primary_h": ph,
        "dpi_scale": get_dpi_scale(),
    }


def pack_point(x: int, y: int) -> dict[str, Any]:
    left, top, width, height = virtual_screen_size()
    x, y = validate_point(x, y)
    return {
        "x": int(x),
        "y": int(y),
        "point_norm": [(x - left) / width, (y - top) / height],
        "coord_space": pack_coord_space(),
    }


def pack_region(region: list | tuple) -> dict[str, Any]:
    x1, y1, x2, y2 = validate_region(region)
    left, top, width, height = virtual_screen_size()
    return {
        "region": [x1, y1, x2, y2],
        "region_norm": [
            (x1 - left) / width,
            (y1 - top) / height,
            (x2 - left) / width,
            (y2 - top) / height,
        ],
        "coord_space": pack_coord_space(),
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


def resolve_point(params: dict, x_key: str = "x", y_key: str = "y") -> tuple[int, int]:
    """
    Resolve a point from absolute coords, optional *_norm, or scale via coord_space.
    Prefer absolute x/y when present; point_norm is a fallback for resolution changes.
    """
    left, top, vw, vh = virtual_screen_size()
    space = params.get("coord_space") if isinstance(params.get("coord_space"), dict) else {}
    ox, oy, sw, sh, has_origin = _space_origin_size(space)

    raw_x = params.get(x_key)
    raw_y = params.get(y_key)
    has_abs = raw_x is not None and raw_x != "" and raw_y is not None and raw_y != ""

    if has_abs:
        x = int(float(raw_x))
        y = int(float(raw_y))
        if has_origin and sw > 0 and sh > 0 and (sw != vw or sh != vh or ox != left or oy != top):
            x = int(round(left + (x - ox) * (vw / sw)))
            y = int(round(top + (y - oy) * (vh / sh)))
        return validate_point(x, y)

    norm = params.get("point_norm")
    if (
        isinstance(norm, (list, tuple))
        and len(norm) == 2
        and all(isinstance(v, (int, float)) for v in norm)
    ):
        x = int(round(ox + float(norm[0]) * sw))
        y = int(round(oy + float(norm[1]) * sh))
        # Legacy packs (no left/top) stored abs-derived norms against primary size;
        # reconstructed x/y are already desktop absolute — do not remap to virtual size.
        if has_origin and (sw != vw or sh != vh or ox != left or oy != top):
            x = int(round(left + (x - ox) * (vw / sw)))
            y = int(round(top + (y - oy) * (vh / sh)))
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

    tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if tpl is None:
        raise ValueError(f"无法读取模板图片: {template_path}")

    if search_region:
        x1, y1, x2, y2 = validate_region(search_region)
        hay_img = grab_region(x1, y1, x2, y2)
        origin_x, origin_y = x1, y1
    else:
        w, h = screen_size_logical()
        hay_img = grab_region(0, 0, w, h)
        origin_x, origin_y = 0, 0

    hay = cv2.cvtColor(np.array(hay_img), cv2.COLOR_RGB2BGR)
    if hay.shape[0] < tpl.shape[0] or hay.shape[1] < tpl.shape[1]:
        return {
            "found": False,
            "x": 0,
            "y": 0,
            "score": 0.0,
            "left": 0,
            "top": 0,
            "width": 0,
            "height": 0,
        }

    res = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(res)
    found = float(max_val) >= float(threshold)
    tw, th = int(tpl.shape[1]), int(tpl.shape[0])
    left = int(origin_x + max_loc[0])
    top = int(origin_y + max_loc[1])
    cx = left + tw // 2
    cy = top + th // 2
    return {
        "found": found,
        "x": cx if found else 0,
        "y": cy if found else 0,
        "score": round(float(max_val), 4),
        "left": left if found else 0,
        "top": top if found else 0,
        "width": tw if found else 0,
        "height": th if found else 0,
    }
