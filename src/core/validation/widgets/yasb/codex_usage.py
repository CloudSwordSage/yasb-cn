from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig


class CodexUsageCallbacksConfig(CallbacksConfig):
    on_left: str = "update_label"


class CodexUsageConfig(CustomBaseModel):
    label: str = "Codex {usage[primary][used_percent]}%"
    label_alt: str = "Codex {usage[secondary][used_percent]}%"
    update_interval: int = Field(default=60, ge=10, le=3600)
    command: str = "codex"
    class_name: str = ""
    keybindings: list[KeybindingConfig] = []
    callbacks: CodexUsageCallbacksConfig = CodexUsageCallbacksConfig()
