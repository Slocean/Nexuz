"""Application version and update channel metadata.

Source of truth for remote clients: repo-root `app_update.json`
(version + announcement). `__version__` is baked at package time from that file.
"""

from __future__ import annotations

__version__ = "0.1.1"

GITHUB_OWNER = "Slocean"
GITHUB_REPO = "Nexuz"

# Single channel file: version + announcement (+ optional download_url)
APP_UPDATE_FILE = "app_update.json"
APP_UPDATE_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/{APP_UPDATE_FILE}"
)

RELEASES_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
