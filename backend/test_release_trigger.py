"""Release-tag monotonicity and immutability contracts."""

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


def test_existing_or_non_incrementing_release_is_rejected() -> None:
    existing = ["0.3.2", "0.4.0"]
    with pytest.raises(SystemExit, match="禁止覆盖"):
        trigger_release.assert_new_release_version("0.4.0", existing)
    with pytest.raises(SystemExit, match="必须递增"):
        trigger_release.assert_new_release_version("0.3.9", existing)
    trigger_release.assert_new_release_version("0.4.1", existing)


def test_remote_tag_listing_ignores_non_release_tags() -> None:
    payload = (
        "abc\trefs/tags/v0.4.0\n"
        "def\trefs/tags/v0.4.1-beta\n"
        "ghi\trefs/tags/archive\n"
    )
    with patch.object(trigger_release, "output", return_value=payload):
        assert trigger_release.remote_versions() == ["0.4.0"]
