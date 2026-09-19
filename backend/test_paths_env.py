"""NEXUZ_DATA_DIR 环境变量优先级：env > config.json data_dir > 默认 AppData。"""

from __future__ import annotations

from pathlib import Path

from backend import paths


def test_default_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUZ_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "_local_app_data", lambda: tmp_path / "appdata")
    assert paths.default_data_dir() == tmp_path / "appdata" / "Nexuz"

    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "server"))
    assert paths.default_data_dir() == tmp_path / "server"


def test_get_data_dir_env_beats_config(monkeypatch, tmp_path):
    """env 最高：config.json 里配置了 data_dir 也被覆盖。"""
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "server"))
    monkeypatch.setattr(paths, "load_app_config", lambda: {"data_dir": str(tmp_path / "fromcfg")})
    assert paths.get_data_dir() == tmp_path / "server"


def test_get_data_dir_config_second(monkeypatch, tmp_path):
    monkeypatch.delenv("NEXUZ_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "load_app_config", lambda: {"data_dir": str(tmp_path / "fromcfg")})
    assert paths.get_data_dir() == tmp_path / "fromcfg"


def test_config_path_follows_env_root(monkeypatch, tmp_path):
    """env 指向的目录就是数据根：config.json 应落在其中（服务器自包含）。"""
    monkeypatch.setenv("NEXUZ_DATA_DIR", str(tmp_path / "server"))
    assert paths.config_path() == Path(tmp_path / "server") / "config.json"
