<p align="center">
    <picture>
      <source media="(prefers-color-scheme: light)" srcset="./docs/assets/readme/hero-light.png" />
      <img src="./docs/assets/readme/hero-dark.png" />
  </picture>
</p>
<h1 align="center">
  <span>YASB Reborn</span>
</h1>
<p align="center">
  <span align="center">YASB（Yet Another Status Bar，又一个状态栏）是一个高度可配置的 Windows 状态栏，由 Python 编写，支持许多小组件，易于主题设置，并且可以进行深度定制。</span>
</p>
<p align="center">
  <span align="center">此仓库是 <a href="https://github.com/amnweb/yasb">YASB</a> 的中文本地化仓库，用于存储本地化后的代码。</span>
</p>

## 📋 安装

为了快速开始，您可以选择以下安装方法之一：
<br/><br/>
<details open>
<summary><strong>从 GitHub 下载 YASB .msi</strong></summary>
<br/>
请访问 <a href="https://github.com/amnweb/yasb/releases/latest">上游 YASB GitHub 发布</a>，点击资产以显示下载，选择与您的架构和安装范围匹配的安装程序。对于大多数设备，这是 x64 个人安装程序。
<br/>
本地化仓库的安装文件暂未构建, 准备跟上游2.0.7同步构建
</details>

<details>
<summary><strong>源码安装</strong></summary>
<br/>
请从源码安装 YASB。在命令行或 PowerShell 中运行以下命令：

```powershell
git clone https://github.com/amnweb/yasb.git
cd yasb
uv venv venv --python=python3.14
.venv\Scripts\activate
uv pip install .[packaging]
cd src
python build.py build
python build.py bdist_msi
```
最终的安装程序可以在 `dist/out/` 目录中找到。
</details>

## 💻 Demo
![Dark Themea](https://raw.githubusercontent.com/amnweb/yasb/main/docs/assets/readme/demo-dark.jpg)
![Light Theme](https://raw.githubusercontent.com/amnweb/yasb/main/docs/assets/readme/demo-light.jpg)

## 本地化仓库新增小部件
| Widget                                                | Description                                                           |
| ----------------------------------------------------- | --------------------------------------------------------------------- |
| [Input Mode](./docs/widgets/(Widget)-Input-Mode.md)   | 显示当前活动的 Windows 输入法转换模式。                               |
| [Terminal](./docs/widgets/(Widget)-Terminal.md)       | 在多个终端之间切换并启动选中的终端。                                  |
| [Codex Usage](./docs/widgets/(Widget)-Codex-Usage.md) | 显示 ChatGPT Codex 用量(tips: 未经过详细测试, 可能不稳定, 不建议使用) |

## 本地bug修复过的小部件
| Widget                                      | Description                  | Docs changed |
| ------------------------------------------- | ---------------------------- | ------------ |
| [Volume](./docs/widgets/(Widget)-Volume.md) | 显示并控制系统音量。         | 否           |
| [Cava](./docs/widgets/(Widget)-Cava.md)     | 使用 Cava 显示音频可视化器。 | 是           |
| [Media](./docs/widgets/(Widget)-Media.md)   | 显示媒体控件和信息。         | 否           |

### 修复说明

#### Volume & Media

Windows 应用可能在启动、切歌或切换播放设备时重建音频会话。原实现会长期持有旧的音量接口，并可能优先选中非活动会话，导致 `Volume`、`Media` 和 `Media Lite` 中的应用音量滑块失效、控制错误会话或只调整同一应用的部分声音。

修复后，组件会在打开菜单、读取状态和执行音量操作时重新解析当前会话：

- 优先使用 `State == Active` 的音频会话，并忽略已过期会话；
- 按 AUMID 或可执行文件识别应用，不再将单个 PID 直接等同于应用；
- 同步调整同一应用的全部活动会话，不再使用 `PID + GroupingParam` 进行 first-wins 去重；
- 旧接口失效或应用重建会话后，会继续查找可用的新会话。

#### Cava

原实现遇到频繁重载、Cava 输出停滞、进程异常退出、系统恢复或默认音频设备切换时，可能残留多个 `cava.exe`、无法自动恢复，或在退出时卡住界面线程。此外，Cava 进程仍持续输出时，无法识别“系统有声但波形全零”或“系统静音但波形持续高位”等采集异常；全零音频帧不会触发重绘，部分非法配置和单色渐变也可能造成空转或绘制异常。

修复后，Cava 小组件会统一管理后台进程并安全恢复：

- 使用单一进程所有权、generation 和独立停止事件串行化启动、停止与重载；旧工作线程未确认退出时不会启动新进程；
- 为工作线程、`terminate`、`kill` 和进程回收设置有限等待，并在输出停滞、进程异常退出、系统唤醒或默认音频设备变化后自动重启；
- 退出和组件销毁时会清理进程及系统回调，首次清理未完成时保留后续重试路径；
- 通过 Windows Core Audio endpoint peak 对比 Cava 输出，持续检测“系统有声但 Cava 全零”和“系统静音但 Cava 卡高”；正常静音不会触发恢复，检测阈值与超时时间均可配置；
- 仅在收到当前 generation 的有效信号后重置重启退避，并记录 PID、generation、峰值、信号时长和明确的重启原因，避免旧帧误报恢复；
- 全零帧也会刷新画面，并校验柱数、帧率、位格式、边缘淡出等配置；单色渐变不再触发除零错误。

#### Cava 崩溃（跨线程信号 / use-after-destruction）

**根因**：`CavaProcessManager` 的管道读线程会直接发射绑定到 `CavaWidget` 的 Qt 信号（`samplesUpdated.emit`），pycaw/comtypes 的 COM 回调（`_CavaAudioDeviceCallback`）和系统唤醒事件过滤器（`_CavaSystemEventFilter`）则会发射 `endpointChanged.emit`。当组件被销毁时（`closeEvent` 关闭，或任务栏用 `deleteLater()` 移除），这些跨线程发射仍可能触碰已经释放的 QObject，导致原生 `0xC0000005` 崩溃（Qt/SIP 生命周期 use-after-destruction）。

修复（`src/core/widgets/yasb/cava.py`）：

- 读线程用 `_state_lock` 与 `stop()` 串行化“是否发射”的判定，一旦发起停止/重载/销毁就不再发布音频帧，避免发射到正在拆除的 QObject；
- 重写 `CavaWidget.event()` 拦截 `QEvent.DeferredDelete`：在惰性删除真正销毁对象之前先调用 `shutdown()`，停止工作线程（`join` 确认退出）并注销 COM/原生设备回调，确保没有任何跨线程信号发射到即将被释放的 QObject；
- `closeEvent`/`shutdown` 保持确定性清理，`_make_cava_cleanup` 幂等且保留失败重试路径，避免重复注销或残留 `cava.exe`。

## 🛠️ 上游 YASB 中当前可用的小部件列表。

| Widget                                                                                            | Description                                                                                                   |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| [Active Windows Title](https://github.com/amnweb/yasb/wiki/(Widget)-Active-Windows-Title)         | Displays the title of the currently active window.                                                            |
| [Applications](https://github.com/amnweb/yasb/wiki/(Widget)-Applications)                         | Shows a list of predefined applications.                                                                      |
| [Battery](https://github.com/amnweb/yasb/wiki/(Widget)-Battery)                                   | Displays the current battery status.                                                                          |
| [Bluetooth](https://github.com/amnweb/yasb/wiki/(Widget)-Bluetooth)                               | Shows the current Bluetooth status and connected devices.                                                     |
| [Brightness](https://github.com/amnweb/yasb/wiki/(Widget)-Brightness)                             | Displays and change the current brightness level.                                                             |
| [Cava](https://github.com/amnweb/yasb/wiki/(Widget)-Cava)                                         | Displays audio visualizer using Cava.                                                                         |
| [Claude Usage](https://github.com/amnweb/yasb/wiki/(Widget)-Claude-Usage)                         | Shows your Claude subscription usage.                                                                         |
| [Copilot](https://github.com/amnweb/yasb/wiki/(Widget)-Copilot)                                   | GitHub Copilot usage with a detailed menu showing statistics                                                  |
| [CPU](https://github.com/amnweb/yasb/wiki/(Widget)-CPU)                                           | Shows the current CPU usage and information.                                                                  |
| [Clock](https://github.com/amnweb/yasb/wiki/(Widget)-Clock)                                       | Displays the current time and date, with customizable formats.                                                |
| [Control Center](https://github.com/amnweb/yasb/wiki/(Widget)-Control-Center)                     | A customizable quick-settings control center with quick actions, sliders, and media controls.                 |
| [Custom](https://github.com/amnweb/yasb/wiki/(Widget)-Custom)                                     | Create a custom widget.                                                                                       |
| [Do Not Disturb](https://github.com/amnweb/yasb/wiki/(Widget)-Dnd)                                | Monitor and toggle Windows Focus Assist (Do Not Disturb).                                                     |
| [Github](https://github.com/amnweb/yasb/wiki/(Widget)-Github)                                     | Shows notifications from GitHub.                                                                              |
| [GlazeWM Binding Mode](https://github.com/amnweb/yasb/wiki/(Widget)-GlazeWM-Binding-Mode)         | GlazeWM binding mode widget.                                                                                  |
| [GlazeWM Tiling Direction](https://github.com/amnweb/yasb/wiki/(Widget)-GlazeWM-Tiling-Direction) | GlazeWM tiling direction widget.                                                                              |
| [GlazeWM Workspaces](https://github.com/amnweb/yasb/wiki/(Widget)-GlazeWM-Workspaces)             | GlazeWM workspaces widget.                                                                                    |
| [Glucose Monitor](https://github.com/amnweb/yasb/wiki/(Widget)-Glucose-Monitor)                   | Nightscout CGM Widget.                                                                                        |
| [Grouper](https://github.com/amnweb/yasb/wiki/(Widget)-Grouper)                                   | Groups multiple widgets together in a container.                                                              |
| [GPU](https://github.com/amnweb/yasb/wiki/(Widget)-GPU)                                           | Displays GPU utilization, temperature, and memory usage.                                                      |
| [Home](https://github.com/amnweb/yasb/wiki/(Widget)-Home)                                         | A customizable home widget menu.                                                                              |
| [Disk](https://github.com/amnweb/yasb/wiki/(Widget)-Disk)                                         | Displays disk usage information.                                                                              |
| [Language](https://github.com/amnweb/yasb/wiki/(Widget)-Language)                                 | Shows the current input language and allows switching between languages.                                      |
| [Launchpad](https://github.com/amnweb/yasb/wiki/(Widget)-Launchpad)                               | A customizable launchpad for quick access to applications.                                                    |
| [Libre Hardware Monitor](https://github.com/amnweb/yasb/wiki/(Widget)-Libre-HW-Monitor)           | Connects to Libre Hardware Monitor to get sensor data.                                                        |
| [Media](https://github.com/amnweb/yasb/wiki/(Widget)-Media)                                       | Displays media controls and information.                                                                      |
| [Media Lite](https://github.com/amnweb/yasb/wiki/(Widget)-Media-Lite)                             | A vertical and minimal album-style media widget.                                                              |
| [Memory](https://github.com/amnweb/yasb/wiki/(Widget)-Memory)                                     | Shows current memory usage and information.                                                                   |
| [Microphone](https://github.com/amnweb/yasb/wiki/(Widget)-Microphone)                             | Displays the current microphone status.                                                                       |
| [Notifications](https://github.com/amnweb/yasb/wiki/(Widget)-Notifications)                       | Shows the number of notifications from Windows.                                                               |
| [Notes](https://github.com/amnweb/yasb/wiki/(Widget)-Notes)                                       | A simple notes widget that allows you to add, delete, and view notes.                                         |
| [OBS](https://github.com/amnweb/yasb/wiki/(Widget)-Obs)                                           | Integrates with OBS Studio to show various streaming information.                                             |
| [Open Meteo](https://github.com/amnweb/yasb/wiki/(Widget)-Open-Meteo)                             | Displays weather information using the Open Meteo API.                                                        |
| [Power Plan](https://github.com/amnweb/yasb/wiki/(Widget)-Power-Plan)                             | Displays the current power plan and allows switching between plans.                                           |
| [Server Monitor](https://github.com/amnweb/yasb/wiki/(Widget)-Server-Monitor)                     | Monitors server status.                                                                                       |
| [Systray](https://github.com/amnweb/yasb/wiki/(Widget)-Systray)                                   | Displays system tray icons.                                                                                   |
| [Traffic](https://github.com/amnweb/yasb/wiki/(Widget)-Traffic)                                   | Displays network traffic information.                                                                         |
| [Todo](https://github.com/amnweb/yasb/wiki/(Widget)-Todo)                                         | Organizes your tasks and to-do lists.                                                                         |
| [Taskbar](https://github.com/amnweb/yasb/wiki/(Widget)-Taskbar)                                   | A customizable taskbar for launching applications.                                                            |
| [Pomodoro](https://github.com/amnweb/yasb/wiki/(Widget)-Pomodoro)                                 | A Pomodoro timer widget.                                                                                      |
| [Power Menu](https://github.com/amnweb/yasb/wiki/(Widget)-Power-Menu)                             | A menu for power options.                                                                                     |
| [Quick Launch](https://github.com/amnweb/yasb/wiki/(Widget)-Quick-Launch)                         | A powerful and customizable quick launcher widget, supporting many different plugins.                         |
| [Recycle Bin](https://github.com/amnweb/yasb/wiki/(Widget)-Recycle-Bin)                           | Shows the status of the recycle bin.                                                                          |
| [Update Checker](https://github.com/amnweb/yasb/wiki/(Widget)-Update-Check)                       | Checks for available updates using Windows Update and Winget.                                                 |
| [Visual Studio Code](https://github.com/amnweb/yasb/wiki/(Widget)-VSCode)                         | Shows recently opened folders in Visual Studio Code.                                                          |
| [Volume](https://github.com/amnweb/yasb/wiki/(Widget)-Volume)                                     | Shows and controls the system volume.                                                                         |
| [Wallpapers](https://github.com/amnweb/yasb/wiki/(Widget)-Wallpapers)                             | Wallpapers manager widget.                                                                                    |
| [Weather](https://github.com/amnweb/yasb/wiki/(Widget)-Weather)                                   | Displays current weather information.                                                                         |
| [WiFi](https://github.com/amnweb/yasb/wiki/(Widget)-WiFi)                                         | Shows the current WiFi status and available networks.                                                         |
| [WHKD](https://github.com/amnweb/yasb/wiki/(Widget)-Whkd)                                         | Shows the current hotkey binding mode of WHKD.                                                                |
| [Windows-Desktops](https://github.com/amnweb/yasb/wiki/(Widget)-Windows-Desktops)                 | Windows virtual desktops widget.                                                                              |
| [Window Controls](https://github.com/amnweb/yasb/wiki/(Widget)-Window-Controls)                   | Window Controls widget provides buttons for minimizing, maximizing/restoring, and closing the focused window. |
| [Window Switcher](https://github.com/amnweb/yasb/wiki/(Widget)-Window-Switcher)                   | A fast, lightweight app switcher.                                                                             |
| [Komorebi Control](https://github.com/amnweb/yasb/wiki/(Widget)-Komorebi-Control)                 | Komorebi control widget.                                                                                      |
| [Komorebi Layout](https://github.com/amnweb/yasb/wiki/(Widget)-Komorebi-Layout)                   | Shows the current layout of Komorebi.                                                                         |
| [Komorebi Stack](https://github.com/amnweb/yasb/wiki/(Widget)-Komorebi-Stack)                     | Shows windows in the current Komorebi stack.                                                                  |
| [Komorebi Workspaces](https://github.com/amnweb/yasb/wiki/(Widget)-Komorebi-Workspaces)           | Komorebi workspaces widget.                                                                                   |
