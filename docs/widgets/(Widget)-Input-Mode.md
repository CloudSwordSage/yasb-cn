# Input Mode Widget

Shows the active Windows IME conversion mode. It reacts to foreground, focus, and IME
WinEvents immediately, and queries the focused (then caret, then foreground) window's default IME window every 200 ms.
The label is redrawn only when the conversion mode changes.

```yaml
input_mode:
  type: "yasb.input_mode.InputModeWidget"
  options:
    label: "{input_mode_label}"
    input_mode_labels:
      native: "中"
      alphanumeric: "英"
      unknown: "?"
```

| Option | Type | Default | Description |
|---|---|---|---|
| `label` | string | `"{input_mode_label}"` | Supports `{input_mode_label}`. |
| `input_mode_labels` | dict | `{'native': '中', 'alphanumeric': '英', 'unknown': '?'}` | Labels for the three conversion-mode states. |
| `class_name` | string | `""` | Additional CSS class. |

```css
.input-mode-widget {}
.input-mode-widget .widget-container {}
.input-mode-widget .label {}
.input-mode-widget .icon {}
```
