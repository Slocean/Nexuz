"""screenshot 积木 region 解析：缺省=整个虚拟桌面，显式区域原样/报错。"""

from __future__ import annotations

import pytest

from backend.blocks import screenshot as mod


@pytest.fixture
def fake_grab(monkeypatch):
    calls: list[tuple[int, int, int, int]] = []

    def _grab(x1, y1, x2, y2):
        from PIL import Image

        calls.append((int(x1), int(y1), int(x2), int(y2)))
        return Image.new("RGB", (max(1, x2 - x1), max(1, y2 - y1)), (16, 32, 48))

    monkeypatch.setattr(mod, "grab_region", _grab)
    return calls


def test_screenshot_default_full_virtual_screen(fake_grab, monkeypatch, tmp_path):
    # 模拟左侧副屏：虚拟桌面含负坐标
    monkeypatch.setattr(
        "backend.core.dpi.virtual_screen_rect", lambda: (-1920, 0, 1920, 1080)
    )
    out = mod.handler({"save_path": str(tmp_path / "full.png")}, {})
    assert fake_grab == [(-1920, 0, 1920, 1080)]
    assert out["left"] == -1920 and out["top"] == 0
    assert out["width"] == 3840 and out["height"] == 1080
    assert out["region"] == [-1920, 0, 1920, 1080]
    assert out["path"].endswith("full.png")


def test_screenshot_explicit_region_passthrough(fake_grab, tmp_path):
    out = mod.handler({"region": [10, 20, 110, 80], "save_path": str(tmp_path / "r.png")}, {})
    assert fake_grab == [(10, 20, 110, 80)]
    assert out["region"] == [10, 20, 110, 80]
    assert out["width"] == 100 and out["height"] == 60


def test_screenshot_invalid_region_still_raises(fake_grab):
    with pytest.raises(ValueError):
        mod.handler({"region": [50, 50, 50, 50]}, {})
