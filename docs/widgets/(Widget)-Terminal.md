# Terminal Widget

Cycles through configured terminals. Left-click starts `command`, right-click starts
`alternate_command`, middle-click toggles the label, and the mouse wheel selects the
previous or next terminal.

```yaml
terminal:
  type: yasb.terminal.TerminalWidget
  options:
    label: "<span>{icon}</span>{short}"
    label_alt: "{name}"
    launcher: "wt.exe"
    terminals:
      - name: PowerShell
        short: "PS"
        launcher: wt.exe # Overrides the global launcher; "No" bypasses a host.
        icon: "\ue756"
        command: 'pwsh.exe'
      - name: Git Bash
        short: "SH"
        icon: "\ue756"
        command: '"C:\Program Files\Git\git-bash.exe"'
      - name: VS Developer PowerShell
        short: "VS"
        icon: "\ue756"
        command: >-
          pwsh.exe -NoExit -Command
          "& 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\Launch-VsDevShell.ps1'"
      - name: Command Prompt
        short: "CMD"
        icon: "\ue756"
        command: 'cmd.exe'
    callbacks:
      on_left: launch
      on_middle: toggle_label
      on_right: launch_alternate
```

| Option | Description |
|---|---|
| `label` / `label_alt` | Support `{icon}`, `{short}`, `{name}`, and `{command}`. |
| `launcher` | Optional global terminal host. It prefixes each command, for example `wt.exe pwsh.exe`. |
| `terminals` | Non-empty list of `name`, optional `short`, `icon`, optional `launcher`, plus `command` and/or `alternate_command`. |
| `class_name` | Additional CSS class. |
| `callbacks` | `launch`, `launch_alternate`, and `toggle_label` are available. |

An entry's `launcher` overrides the global value. Set it to `"No"` (case-insensitive)
to run the command directly; this is useful for terminals that already create their own window.

```css
.terminal-widget {}
.terminal-widget .widget-container {}
.terminal-widget .label {}
.terminal-widget .icon {}
```
