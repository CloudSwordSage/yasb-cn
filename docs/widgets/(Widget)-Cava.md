# Cava Widget Configuration

> NOTE: This widget requires `cava` version >= 0.10.4 to be installed on your system. YASB displays an error instead of starting a detected older version; if version output cannot be parsed, it logs a warning and attempts to start Cava. You can install the latest MSI from the [Cava releases page](https://github.com/karlstav/cava/releases). Cava needs to be accessible in the system PATH. After installing, fully stop YASB and start it again (do not use restart) so that YASB can pick up the new environment variables. If it still does not work, restart your PC.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `class_name` | string | "" | Additional CSS class names for the widget container |
| `source` | string | "auto" | Audio input source device. Use `"auto"` for the default device, or specify a device name to capture from a specific audio device. Requires cava >= 0.10.4 with device selection support |
| `bar_height` | integer | 20 | The height of bars in pixels |
| `min_bar_height` | integer | 1 | The minimum height of bars in pixels (0 or greater) |
| `bars_number` | integer | 10 | The number of bars (1 or greater) |
| `output_bit_format` | string | "16bit" | Binary bit format, can be '8bit' (0-255) or '16bit' (0-65530) |
| `orientation` | string | `"bottom"` | Visual orientation of the bar. Can be `"top"` or `"bottom"`. |
| `bar_spacing` | integer | 1 | Space between bars |
| `bar_width` | integer | 3 | Bars' width in number of characters |
| `sleep_timer` | integer | 0 | Seconds with no input before cava goes to sleep mode. 0 to disable |
| `output_timeout` | float | 3.0 | Seconds without a raw frame before YASB restarts Cava. Active when `sleep_timer` is 0 |
| `signal_timeout` | float | 3.0 | Seconds of system audio with no Cava signal before YASB restarts Cava |
| `cava_peak_threshold` | float | 0.0001 | Minimum normalized Cava peak treated as an effective signal |
| `system_peak_threshold` | float | 0.0001 | Minimum Windows endpoint peak treated as active system audio |
| `cava_stuck_high_threshold` | float | 0.7 | Cava peak above which output is considered stuck high while the system is silent |
| `system_silence_threshold` | float | 0.001 | Maximum Windows endpoint peak treated as system silence for stuck-high detection |
| `stuck_high_timeout` | float | 5.0 | Seconds of sustained stuck-high output during system silence before YASB restarts Cava |
| `sensitivity` | integer | 100 | Manual sensitivity in %. 200 means double height |
| `lower_cutoff_freq` | integer | 50 | Lower cutoff frequencies for lowest bars |
| `higher_cutoff_freq` | integer | 10000 | Higher cutoff frequencies for highest bars |
| `framerate` | integer | 60 | Frames per second (1 or greater) |
| `noise_reduction` | integer | 77 | Noise reduction, 0-100. Higher = smoother but slower, lower = faster but noisier |
| `channels` | string | "stereo" | Visual channels. Can be 'stereo' or 'mono' |
| `mono_option` | string | "average" | Set mono to take input from 'left', 'right' or 'average' |
| `reverse` | integer | 0 | Set to 1 to display frequencies the other way around |
| `waveform` | integer | 0 | Show waveform instead of frequency spectrum, 1 = on, 0 = off |
| `monstercat` | integer | 1 | Disables or enables the so-called "Monstercat smoothing" with or without "waves". Set to 0 to disable. |
| `waves` | integer | 0 | Related to monstercat, 1 = on, 0 = off |
| `foreground` | string | "#ffffff" | Foreground color in hex format |
| `gradient` | integer | 1 | Gradient mode, 1 = on, 0 = off |
| `gradient_color_1` | string | "#74c7ec" | First gradient color in hex format |
| `gradient_color_2` | string | "#89b4fa" | Second gradient color in hex format |
| `gradient_color_3` | string | "#cba6f7" | Third gradient color in hex format |
| `hide_empty` | boolean | false | Hide widget when no audio is playing (requires `sleep_timer` to be enabled) |
| `bar_type`         | string  | `bars`  | Type of bar display. Can be 'bars', 'bars_mirrored', 'waves', or 'waves_mirrored'. |
| `edge_fade` | integer or two-item array | 0 | Apply a non-negative fade width to both edges, or use `[left, right]` for separate control. 0 disables it. **Note:** When both sides have fade, each is capped to half the widget width to prevent overlap. When only one side has fade, it can use the full widget width |
| `callbacks`         | dict    | `{'on_left': 'do_nothing', 'on_middle': 'do_nothing', 'on_right': 'reload_cava'}` | Callbacks for mouse events on the widget. |

## Example Configuration

```yaml
  cava:
    type: "yasb.cava.CavaWidget"
    options:
      bar_height: 12
      min_bar_height: 0
      gradient: 1
      foreground: "#89b4fa"
      gradient_color_1: '#74c7ec'
      gradient_color_2: '#89b4fa'
      gradient_color_3: '#cba6f7'
      bars_number: 8
      bar_spacing: 2
      bar_width: 4
      bar_type: "bars"
      framerate: 60
      hide_empty: true
```

## Description of Options

- **class_name**: Additional CSS class names for the widget container. (optional)
- **source**: Audio input source device. Set to `"auto"` (default) to use the system default audio device, or specify a device name to capture audio from a specific device. This is useful when you have multiple audio outputs and want to visualize a particular one. Requires cava >= 0.10.4 with device selection support.
- **bar_height**: The height of bars in pixels.
- **min_bar_height**: The minimum height of bars in pixels.
- **bars_number**: The number of bars to display. Must be at least 1.
- **output_bit_format**: Binary bit format, can be '8bit' (0-255) or '16bit' (0-65530).
- **orientation**: The visual orientation of the bar. Can be `'top'` (cava bars grow downwards) or `'bottom'` (cava bars grow upwards). Default is `'bottom'`.
- **bar_spacing**: Space between bars in number of characters.
- **bar_width**: Bars' width in number of characters.
- **sleep_timer**: Seconds with no input before cava goes to sleep mode. 0 to disable.
- **output_timeout**: Restart Cava after this many seconds without a raw frame. This watchdog is active when `sleep_timer` is `0`.
- **signal_timeout**: Restart Cava after system audio stays above `system_peak_threshold` while Cava stays at or below `cava_peak_threshold` for this many seconds. This check applies when `source` is `"auto"`.
- **cava_peak_threshold**: Minimum normalized Cava peak treated as an effective signal. Raise it only if device noise prevents silence detection.
- **system_peak_threshold**: Minimum Windows default endpoint peak treated as active system audio. Raise it only if endpoint noise causes false recovery attempts.
- **cava_stuck_high_threshold**: Cava peak above which output is treated as stuck high while the system endpoint remains silent.
- **system_silence_threshold**: Windows default endpoint peak below which the system is treated as silent for stuck-high detection.
- **stuck_high_timeout**: Restart Cava after its peak stays above `cava_stuck_high_threshold` while the system peak stays below `system_silence_threshold` for this many seconds.
- **sensitivity**: Manual sensitivity in %. 200 means double height.
- **lower_cutoff_freq**: Lower cutoff frequencies for lowest bars.
- **higher_cutoff_freq**: Higher cutoff frequencies for highest bars.
- **framerate**: Frames per second. Must be at least 1.
- **noise_reduction**: Noise reduction, 0-100. Higher = smoother but slower, lower = faster but noisier.
- **channels**: Visual channels. Can be 'stereo' or 'mono'.
- **mono_option**: Set mono to take input from 'left', 'right' or 'average'.
- **reverse**: Set to 1 to display frequencies the other way around.
- **waveform**: Show waveform instead of frequency spectrum, 1 = on, 0 = off.
- **monstercat**: Disables or enables the so-called "Monstercat smoothing" (spatial bar blending) with or without "waves". Set to 0 to disable.
- **waves**: Related to monstercat, 1 = on, 0 = off.
- **foreground**: Foreground color in hex format.
- **gradient**: Gradient mode, 1 = on, 0 = off.
- **gradient_color_1**: First gradient color in hex format.
- **gradient_color_2**: Second gradient color in hex format.
- **gradient_color_3**: Third gradient color in hex format. (optional)
- **hide_empty**: Hide widget when no audio is playing (requires `sleep_timer` to be enabled).
- **bar_type**: Type of bar display. Can be 'bars', 'bars_mirrored', 'waves', or 'waves_mirrored'.
- **edge_fade**: Apply fade effect to edges. Creates a smooth fade-out effect on the edges of the visualization. Can be configured in two ways:
  - **Single value** (e.g., `15`): Applies the same fade width to both left and right edges
  - **Two-item array** (e.g., `[10, 20]`): Applies different non-negative fade widths - first value for left edge, second for right edge
  - Set to `0` or `[0, 0]` to disable. **Important:** When both sides have fade, each is automatically capped to half the widget width to prevent overlapping. When only one side has fade (e.g., `[180, 0]`), it can use the full widget width.
- **callbacks**: A dictionary specifying the callbacks for mouse events. The keys are `on_left`, `on_middle`, and `on_right`, and the values are the names of the callback functions.

> **Note:** The `waves` and `waves_mirrored` ignore the `bar_spacing` option.

### Allowed Callbacks:
```
"reload_cava"
"do_nothing"
```



More information on this option is documented in the [example config file](https://github.com/karlstav/cava/blob/master/example_files/config)

## Style
```css
.cava-widget {
    padding: 0;
    margin: 0;
}
.cava-widget .widget-container {}
```
