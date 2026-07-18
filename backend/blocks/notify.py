from __future__ import annotations

import subprocess
import sys


SCHEMA = {
    "type": "notify",
    "label": "系统通知",
    "category": "系统类",
    "inputs": [
        {
            "name": "title",
            "type": "string",
            "label": "标题",
            "default": "Nexuz",
            "bindable": True,
        },
        {
            "name": "message",
            "type": "string",
            "label": "内容",
            "default": "",
            "ui": "textarea",
            "bindable": True,
        },
        {
            "name": "play_sound",
            "type": "select",
            "label": "播放提示音",
            "options": ["true", "false"],
            "default": "true",
            "option_labels": {"true": "是", "false": "否"},
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "error", "type": "string"},
    ],
}


def _xml_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _beep() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass


def _windows_toast(title: str, message: str) -> tuple[bool, str]:
    """Show a Windows toast via PowerShell (no extra pip deps)."""
    title_xml = _xml_escape(title)
    message_xml = _xml_escape(message)
    # Use single-quoted here-string so XML is not re-expanded by PowerShell
    script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @'
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title_xml}</text>
      <text>{message_xml}</text>
    </binding>
  </visual>
</toast>
'@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Nexuz").Show($toast)
"""
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if completed.returncode == 0:
            return True, ""
        err = (completed.stderr or completed.stdout or "").strip() or f"退出码 {completed.returncode}"
        return False, err
    except Exception as exc:
        return False, str(exc)


def handler(params, context, **kwargs):
    title = str(params.get("title") if params.get("title") is not None else "Nexuz")
    message = "" if params.get("message") is None else str(params.get("message"))
    play_sound = str(params.get("play_sound") or "true").strip().lower() in ("true", "1", "yes")

    ok = False
    error = ""
    if sys.platform == "win32":
        ok, error = _windows_toast(title, message)
    else:
        ok = True

    if play_sound or not ok:
        _beep()

    if not ok and play_sound:
        return {"ok": True, "error": error or "Toast 失败，已播放提示音"}

    if not ok:
        return {"ok": False, "error": error or "通知失败"}

    return {"ok": True, "error": ""}
