# Input Capture / Playback Engine

Pluggable click capture and playback for the Nexuz platform.

## Concepts

- **CaptureMode**: `coord` | `frida_ui` (extend by registering a provider)
- **ClickTarget**: normalized click node params (legacy flat `x/y` still accepted)
- **CaptureProvider**: sequence + single pick
- **PlaybackProvider**: execute a ClickTarget at runtime
- **RecordingSession**: API-facing router (window hide, overlays, mode)

Mode resolution:

```text
effectiveMode = node.params.capture_mode
             ?? appSettings.defaultCaptureMode
             ?? "coord"
```

At run time the frontend injects `defaultCaptureMode` into click nodes that omit `capture_mode` (see `applyDefaultCaptureMode`).

## Add a new provider

1. Implement `CaptureProvider` and/or `PlaybackProvider` under `providers/`
2. Register in `provider_registry._bootstrap`
3. Add mode string to click schema options + Settings UI if user-facing
4. Never persist session-only pointers in FlowModel JSON

## Frida UI

- Script: `frida/scripts/unity_ui_click.js`
- Session: `frida/session_manager.py`
- Stable id: `hierarchy_path` + `component_type` + `sibling_index`
- Connect via Settings → Frida 连接, or API `frida_attach`

## Error codes

| Code | Meaning |
|------|---------|
| `PROVIDER_UNAVAILABLE` | Mode registered but not ready |
| `FRIDA_NOT_ATTACHED` | Need attach first |
| `STABLE_ID_RESOLVE_FAILED` | Path no longer resolves |
| `RECORDING_ACTIVE` / `NOT_RECORDING` | Session state |
| `INVALID_MODE` | Unknown mode |
| `CANCELLED` | User timeout / cancel on pick |
