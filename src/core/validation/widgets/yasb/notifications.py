from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class NotificationsIconsConfig(CustomBaseModel):
    new: str = "\udb80\udc9e"
    default: str = "\udb80\udc9a"


class NotificationsCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_label"


class NotificationsConfig(CustomBaseModel):
    label: str = "{count} 条新通知"
    label_alt: str = "{count} 条新通知"
    class_name: str = ""
    hide_empty: bool = False
    tooltip: bool = True
    icons: NotificationsIconsConfig = NotificationsIconsConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: NotificationsCallbacksConfig = NotificationsCallbacksConfig()
