from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class BluetoothIconsConfig(CustomBaseModel):
    bluetooth_on: str = "\ue702"
    bluetooth_off: str = "\ue702"
    bluetooth_connected: str = "\ue702"


class BluetoothBatteryIconsConfig(CustomBaseModel):
    empty: str = "\ueba0"
    low: str = "\ueba2"
    medium: str = "\ueba5"
    high: str = "\ueba8"
    full: str = "\uebaa"


class BluetoothDeviceIconsConfig(CustomBaseModel):
    headphones: str = "\ue7f6"
    headset: str = "\ue95b"
    speaker: str = "\ue7f5"
    phone: str = "\ue8ea"
    tablet: str = "\ue70a"
    laptop: str = "\ue7f8"
    computer: str = "\ue950"
    keyboard: str = "\ue765"
    mouse: str = "\ue962"
    controller: str = "\ue7fc"
    watch: str = "\ue918"
    camera: str = "\ue722"
    generic: str = "\ue702"
    battery: BluetoothBatteryIconsConfig = BluetoothBatteryIconsConfig()
    scan: str = "\ue72c"


class BluetoothDeviceAliasConfig(CustomBaseModel):
    name: str
    alias: str


class BluetoothLabelsConfig(CustomBaseModel):
    title: str = "蓝牙"
    your_devices: str = "你的设备"
    new_devices: str = "新设备"
    not_connected: str = "未连接"
    connected: str = "已连接"
    more_settings: str = "更多蓝牙设置"
    connect: str = "连接"
    disconnect: str = "断开连接"
    connecting: str = "正在连接"
    disconnecting: str = "正在断开连接"
    pair: str = "配对"
    manage: str = "管理"
    power_on: str = "开启"
    power_off: str = "关闭"


class BluetoothMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: str = "normal"
    border_color: str = "System"
    alignment: str = "right"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0
    labels: BluetoothLabelsConfig = BluetoothLabelsConfig()
    device_icons: BluetoothDeviceIconsConfig = BluetoothDeviceIconsConfig()


class BluetoothCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_menu"


class BluetoothConfig(CustomBaseModel):
    label: str = "\ue702"
    label_alt: str = "\ue702"
    class_name: str = ""
    label_no_device: str = "没有已连接的设备"
    label_device_separator: str = ", "
    max_length: int | None = None
    max_length_ellipsis: str = "..."
    tooltip: bool = True
    icons: BluetoothIconsConfig = BluetoothIconsConfig()
    device_aliases: list[BluetoothDeviceAliasConfig] = []
    keybindings: list[KeybindingConfig] = []
    callbacks: BluetoothCallbacksConfig = BluetoothCallbacksConfig()
    menu_config: BluetoothMenuConfig = BluetoothMenuConfig()
