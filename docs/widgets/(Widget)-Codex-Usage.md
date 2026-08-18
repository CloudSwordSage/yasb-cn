# Codex Usage Widget

Shows the ChatGPT Codex rate limits from the local `codex app-server` JSON-RPC interface. It uses
the existing Codex sign-in and never reads, stores, or displays credentials.

| Option | Type | Default | Description |
|---|---|---|---|
| `label` | string | `"Codex {usage[primary][used_percent]}%"` | Primary-window label. |
| `label_alt` | string | `"Codex {usage[secondary][used_percent]}%"` | Secondary-window label. |
| `update_interval` | integer | `60` | Refresh interval in seconds (10–3600). |
| `command` | string | `"codex"` | Codex executable path or command. |
| `class_name` | string | `""` | Additional CSS class. |
| `callbacks` | dict | `{'on_left': 'update_label'}` | Mouse callbacks. |

```yaml
codex_usage:
  type: "yasb.codex_usage.CodexUsageWidget"
  options:
    label: "Codex {usage[primary][used_percent]}%"
    label_alt: "长期 {usage[secondary][used_percent]}%"
    update_interval: 60
```

Use `primary` or `secondary` with `used_percent`, `window_duration_mins`, or `resets_at`.
Missing data renders as `--`. If YASB cannot find Codex on its own PATH, set `command` to the full path of `codex.cmd`, for example `"D:/nodejs/node_global/codex.cmd"`.

```css
.codex-usage {}
.codex-usage .widget-container {}
.codex-usage .label {}
.codex-usage .label.alt {}
.codex-usage .icon {}
```
