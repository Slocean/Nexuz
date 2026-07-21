"""Focused regression checks for the fail-closed update chain."""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import updater


def test_release_url_allowlist() -> None:
    valid = (
        "https://github.com/Slocean/Nexuz/releases/download/v1.2.3/Nexuz.exe"
    )
    assert updater._validate_github_url(valid, initial=True) == valid
    for invalid in (
        "http://github.com/Slocean/Nexuz/releases/download/v1.2.3/Nexuz.exe",
        "https://example.com/Nexuz.exe",
        "https://github.com/other/repo/releases/download/v1.2.3/Nexuz.exe",
    ):
        try:
            updater._validate_github_url(invalid, initial=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe update URL accepted: {invalid}")


def test_checksum_manifest_is_bound_to_expected_asset() -> None:
    digest = "a" * 64
    assert (
        updater._parse_checksum_manifest(f"{digest} *Nexuz.exe\n".encode())
        == digest
    )
    try:
        updater._parse_checksum_manifest(f"{digest} *Other.exe\n".encode())
    except ValueError:
        pass
    else:
        raise AssertionError("checksum for a different asset was accepted")


def test_download_verifies_hash() -> None:
    blob = b"MZ" + (b"x" * (110 * 1024))
    digest = hashlib.sha256(blob).hexdigest()
    release = {
        "ok": True,
        "download_url": (
            "https://github.com/Slocean/Nexuz/releases/download/v1.2.3/Nexuz.exe"
        ),
        "checksum_url": (
            "https://github.com/Slocean/Nexuz/releases/download/v1.2.3/"
            "Nexuz.exe.sha256"
        ),
    }
    info = {
        "ok": True,
        "update_available": True,
        "current_version": "1.2.2",
        "latest_version": "1.2.3",
        "html_url": "https://github.com/Slocean/Nexuz/releases/tag/v1.2.3",
    }
    with tempfile.TemporaryDirectory() as td:
        with (
            patch.object(updater, "check_for_update", return_value=info),
            patch.object(updater, "resolve_download_url", return_value=release),
            patch.object(
                updater,
                "_http_bytes",
                side_effect=[f"{digest} *Nexuz.exe\n".encode(), blob],
            ),
            patch.object(updater, "exe_dir", return_value=Path(td)),
        ):
            result = updater.download_update()
        assert result["ok"] is True
        assert result["sha256"] == digest
        assert (Path(td) / "Nexuz_update.exe").read_bytes() == blob
        assert (Path(td) / updater.VERIFY_METADATA_NAME).is_file()


if __name__ == "__main__":
    test_release_url_allowlist()
    test_checksum_manifest_is_bound_to_expected_asset()
    test_download_verifies_hash()
    print("UPDATER OK")
