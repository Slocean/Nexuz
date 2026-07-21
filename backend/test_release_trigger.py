"""Release-tag monotonicity and retag contracts."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import trigger_release


def test_version_key_accepts_only_canonical_release_versions() -> None:
    assert trigger_release.version_key("0.4.1") == (0, 4, 1)
    for invalid in ("v0.4.1", "0.04.1", "0.4", "0.4.1-beta"):
        with pytest.raises(ValueError):
            trigger_release.version_key(invalid)


def test_same_version_may_replace_but_older_is_rejected() -> None:
    existing = ["0.3.2", "0.4.0"]
    assert trigger_release.ensure_release_version_allowed("0.4.0", existing) is True
    with pytest.raises(SystemExit, match="必须递增"):
        trigger_release.ensure_release_version_allowed("0.3.9", existing)
    assert trigger_release.ensure_release_version_allowed("0.4.1", existing) is False


def test_remote_tag_listing_ignores_non_release_tags() -> None:
    payload = (
        "abc\trefs/tags/v0.4.0\n"
        "def\trefs/tags/v0.4.1-beta\n"
        "ghi\trefs/tags/archive\n"
        "jkl\trefs/tags/unsigned-v0.5.0\n"
    )
    with patch.object(trigger_release, "output", return_value=payload):
        assert trigger_release.remote_versions() == ["0.4.0"]


def test_tag_for_version() -> None:
    assert trigger_release.tag_for_version("0.5.0") == "v0.5.0"


def test_parse_args() -> None:
    assert trigger_release.parse_args([]) == ""
    assert trigger_release.parse_args(["0.5.0"]) == "0.5.0"
    assert trigger_release.parse_args(["v0.5.0"]) == "0.5.0"
    with pytest.raises(SystemExit, match="未知参数"):
        trigger_release.parse_args(["--unsigned"])
    with pytest.raises(SystemExit, match="只能指定一个版本号"):
        trigger_release.parse_args(["0.5.0", "0.5.1"])


def test_delete_tag_removes_local_and_remote() -> None:
    calls: list[list[str]] = []

    def fake_output(cmd: list[str]) -> str:
        if cmd[:3] == ["git", "tag", "--list"]:
            return "v0.5.0"
        return ""

    def fake_run(cmd: list[str]) -> None:
        calls.append(cmd)

    with (
        patch.object(trigger_release, "output", side_effect=fake_output),
        patch.object(trigger_release, "run", side_effect=fake_run),
    ):
        trigger_release.delete_tag("v0.5.0", remote=True)

    assert ["git", "tag", "-d", "v0.5.0"] in calls
    assert ["git", "push", "origin", "--delete", "v0.5.0"] in calls
