# Heart Rate Widget

Displays live heart rate from any standard Bluetooth Low Energy (BLE) heart rate device, such as chest straps and
smart watches. The widget uses the standard Heart Rate Service (`0x180D`) and Heart Rate Measurement characteristic
(`0x2A37`) through [bleak](https://github.com/hbldh/bleak) and works without vendor software.

The normal layout shows a real-time sparkline on the left and the current heart rate plus a configurable summary on the
right. A left click opens the BLE device manager popup; a right click switches between the normal layout and a compact
detailed statistics layout. Both layouts share the same sampling data and time window, so switching never touches the
BLE connection.

```yaml
heart_rate:
  type: "yasb.heart_rate.HeartRateWidget"
  options:
    class_name: "heart-rate-widget"
    graph:
      enabled: true
      width: 120
      window_seconds: 60
      min_y_range: 20
      show_grid: false
      show_average_line: false
      show_latest_point: true
      gap_on_disconnect: true
    display:
      default_mode: "normal"
      normal:
        statistics:
          - avg
          - max
      detailed:
        statistics:
          - current
          - avg
          - min
          - max
          - median
          - stddev
          - range
          - sample_count
    connection:
      auto_connect: true
      reconnect_interval: 2000
      connect_timeout: 8000
      stale_timeout: 10000
      scan_timeout: 5000
      scan_concurrency: 2
    callbacks:
      on_left: "toggle_device_menu"
      on_middle: "do_nothing"
      on_right: "toggle_display_mode"
```

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `class_name` | string | `"heart-rate-widget"` | Additional CSS classes for the widget. |
| `graph.enabled` | boolean | `true` | Show the sparkline in the normal layout. |
| `graph.width` | integer | `120` | Sparkline width in pixels. There is no height option; height always follows the bar layout. |
| `graph.window_seconds` | integer | `60` | Time window for the graph and all statistics. |
| `graph.min_y_range` | number | `20` | Minimum visible BPM span so small fluctuations are not exaggerated. |
| `graph.show_grid` | boolean | `false` | Draw low-contrast horizontal grid lines. |
| `graph.show_average_line` | boolean | `false` | Draw a dashed average heart rate line. |
| `graph.show_latest_point` | boolean | `true` | Draw a dot on the newest sample. |
| `graph.gap_on_disconnect` | boolean | `true` | Break the line between connection sessions. The line is always broken across raw time gaps. |
| `display.default_mode` | `"normal"` or `"detailed"` | `"normal"` | Initial layout. Right click toggles it at runtime. |
| `display.normal.statistics` | list | `["avg", "max"]` | Statistics under the current value, in display order. |
| `display.normal.separator` | string | `" · "` | Separator between summary statistics. |
| `display.normal.spacing` | integer | `0` | Extra spacing between summary statistics in pixels. |
| `display.detailed.statistics` | list | `["current", "avg", "min", "max", "median", "stddev", "range", "sample_count"]` | Statistics for the detailed layout. |
| `display.detailed.separator` | string | `" │ "` | Separator between detailed statistics. |
| `display.detailed.spacing` | integer | `0` | Extra spacing between detailed statistics in pixels. |
| `connection.auto_connect` | boolean | `true` | Reconnect the saved default device after YASB starts. |
| `connection.reconnect_interval` | integer (ms) | `2000` | Wait after a failed or lost connection before the next attempt. |
| `connection.connect_timeout` | integer (ms) | `8000` | Timeout for connecting and subscribing to notifications. |
| `connection.stale_timeout` | integer (ms) | `10000` | Time without a valid measurement before data is marked stale. The BLE link itself is not dropped. |
| `connection.scan_timeout` | integer (ms) | `5000` | How long an advertisement scan collects results. |
| `connection.scan_concurrency` | integer (1-4) | `2` | Number of parallel GATT verification connections during a deep scan. |
| `callbacks.on_left` | string | `"toggle_device_menu"` | Open/close the device manager popup. |
| `callbacks.on_middle` | string | `"do_nothing"` | No action by default. |
| `callbacks.on_right` | string | `"toggle_display_mode"` | Switch between normal and detailed layouts. |

### Statistics

All statistics are computed from valid measurements inside the shared `window_seconds` time window. Missing values are
never treated as zero, and gaps from disconnections are never filled with synthetic samples.

| Key | Meaning |
|---|---|
| `current` | Newest valid measurement. Displays `--` while connecting, disconnected or stale. |
| `avg` | Arithmetic mean of all samples in the window (not time-weighted). |
| `min` / `max` | Lowest / highest sample in the window. |
| `median` | Median sample. |
| `stddev` | Population standard deviation of the window. |
| `range` | `max - min`. |
| `sample_count` | Number of valid samples in the window. |

## Device Management

A left click opens the device popup:

- **开始扫描** performs a lightweight advertisement scan. Devices that advertise the Heart Rate Service are listed
  incrementally with name, BLE address and RSSI.
- **完整扫描并验证** additionally connects to every candidate with limited parallelism and verifies that the Heart
  Rate Measurement characteristic supports notifications. Devices that do not advertise the service are included.
- Selecting a device and pressing **连接** makes it the single active heart rate source.
- **断开连接** performs a manual disconnect. Manually disconnected devices are not reconnected automatically until
  YASB restarts or the device is selected again.
- **设为默认** marks the device that is restored on the next YASB start.
- **移除已保存设备** removes the persisted record.
- The verification result, RSSI and connection state of every row update in place; the list is never rebuilt while
  scanning, and closing the popup never drops an established connection.

Closing the popup stops an in-progress scan, but a device that is already connected keeps streaming.

## Persistence

After the first successful connection the device is stored next to your YASB configuration in
`%USERPROFILE%\.config\yasb\heart_rate_devices.json` (or `$YASB_CONFIG_HOME`):

```json
{
  "DEVICE_IDENTIFIER": {
    "name": "vivo WATCH 5",
    "address": "DEVICE_IDENTIFIER",
    "auto_connect": true,
    "last_connected": 1789000000.0
  }
}
```

Writes are atomic and runtime objects are never persisted. If the file cannot be read or is corrupted, the widget keeps
running and reports a storage error instead of overwriting the file; fix or delete the file to continue saving devices.

## Notes

- `connection` options are shared per YASB process: when the widget is used on multiple bars, every instance must use
  the same `connection` section. A mismatching instance is skipped with a validation error in the log.
- The BLE client runs in a dedicated background thread with its own asyncio loop, so scanning, connecting and
  reconnecting never block the UI thread. The UI updates at most 5 times per second.
- `BleakScanner` advertisements are the primary discovery source. Not every device advertises the Heart Rate Service,
  so use the deep scan when a device is missing from a lightweight scan.

## Example Style

```css
.heart-rate-widget {
    padding: 0 8px;
}

.heart-rate-widget.disconnected {
    color: #8a8a8a;
}

.heart-rate-widget.connecting,
.heart-rate-widget.reconnecting {
    color: #8a8a8a;
}

.heart-rate-widget.stale {
    color: #b08a5a;
}

.heart-rate-widget .sparkline {
    color: #ff5d7a;
}

.heart-rate-widget .separator {
    color: rgba(255, 255, 255, 0.15);
    margin: 6px 8px;
}

.heart-rate-widget .current {
    font-size: 20px;
    font-weight: 600;
}

.heart-rate-widget .stat {
    color: rgba(255, 255, 255, 0.65);
    font-size: 11px;
}

/* Every statistic has its own class: .stat.current, .stat.avg, .stat.min,
   .stat.max, .stat.median, .stat.stddev, .stat.range, .stat.sample_count */
.heart-rate-widget .stat.avg {
    color: #9ecbff;
}

.heart-rate-menu {
    background-color: rgba(20, 20, 20, 0.9);
}

.heart-rate-menu .title {
    font-weight: 600;
}
```

The widget frame receives the state class at runtime: `.connected`, `.disconnected`, `.connecting`, `.reconnecting`
and `.stale`. The graph color follows the widget's text color (`color`); the grid and average line can be styled through
`.sparkline .grid` and `.sparkline .average-line`.
