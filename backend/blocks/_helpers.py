"""Shared helpers for block handlers."""

from __future__ import annotations

from collections import Counter

import mss
import pyautogui
from PIL import Image

from backend.core.dpi import screen_size_logical

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01


def validate_point(x: int, y: int) -> None:
    w, h = screen_size_logical()
    if x < 0 or y < 0 or x >= w or y >= h:
        raise ValueError(f"坐标超出屏幕范围: ({x},{y})，屏幕逻辑尺寸 {w}x{h}")


def validate_region(region: list | tuple) -> tuple[int, int, int, int]:
    if not region or len(region) != 4:
        raise ValueError("region 必须是 [x1,y1,x2,y2]")
    x1, y1, x2, y2 = [int(v) for v in region]
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"无效区域: {region}")
    w, h = screen_size_logical()
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h:
        raise ValueError(f"区域超出屏幕范围: {region}，屏幕 {w}x{h}")
    return x1, y1, x2, y2


def grab_region(x1: int, y1: int, x2: int, y2: int) -> Image.Image:
    with mss.mss() as sct:
        monitor = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def pixel_color(x: int, y: int) -> str:
    validate_point(x, y)
    img = grab_region(x, y, x + 1, y + 1)
    r, g, b = img.getpixel((0, 0))
    return f"#{r:02X}{g:02X}{b:02X}"


def region_dominant_color(region: list | tuple) -> str:
    x1, y1, x2, y2 = validate_region(region)
    img = grab_region(x1, y1, x2, y2)
    # downsample for speed
    img = img.resize((max(1, img.width // 4), max(1, img.height // 4)))
    colors = list(img.getdata())
    # quantize roughly
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
