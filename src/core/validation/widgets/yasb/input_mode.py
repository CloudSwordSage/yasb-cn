from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig


class InputModeLabelsConfig(CustomBaseModel):
    native: str = "中"
    alphanumeric: str = "英"
    unknown: str = "?"


class InputModeConfig(CustomBaseModel):
    label: str = "{input_mode_label}"
    class_name: str = ""
    input_mode_labels: InputModeLabelsConfig = InputModeLabelsConfig()
    keybindings: list[KeybindingConfig] = []
    callbacks: CallbacksConfig = CallbacksConfig()
