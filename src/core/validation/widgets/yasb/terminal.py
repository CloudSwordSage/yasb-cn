from pydantic import Field, model_validator

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig


class TerminalEntryConfig(CustomBaseModel):
    name: str = Field(min_length=1)
    short: str = ""
    icon: str = ""
    launcher: str | None = None
    command: str | None = Field(default=None, min_length=1)
    alternate_command: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def check_launch_command(self) -> TerminalEntryConfig:
        """Require a primary or alternate command for each terminal."""
        if self.command is None and self.alternate_command is None:
            raise ValueError("at least one of command or alternate_command is required")
        return self


class TerminalCallbacksConfig(CallbacksConfig):
    on_left: str = "launch"
    on_middle: str = "toggle_label"
    on_right: str = "launch_alternate"


class TerminalConfig(CustomBaseModel):
    label: str = "<span>{icon}</span> {name}"
    label_alt: str = "{command}"
    class_name: str = ""
    launcher: str | None = None
    terminals: list[TerminalEntryConfig] = Field(min_length=1)
    keybindings: list[KeybindingConfig] = []
    callbacks: TerminalCallbacksConfig = TerminalCallbacksConfig()
