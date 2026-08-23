from typing import Annotated, Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class CavaCallbacksConfig(CallbacksConfig):
    on_right: str = "reload_cava"


class CavaConfig(CustomBaseModel):
    class_name: str = ""
    source: str = "auto"
    bar_height: int = Field(default=20, ge=1)
    min_bar_height: int = Field(default=1, ge=0)
    bars_number: int = Field(default=10, ge=1)
    output_bit_format: Literal["8bit", "16bit"] = "16bit"
    orientation: Literal["top", "bottom"] = "bottom"
    bar_spacing: int = 1
    bar_width: int = 3
    sleep_timer: int = Field(default=0, ge=0)
    output_timeout: float = Field(default=3.0, gt=0)
    signal_timeout: float = Field(default=3.0, gt=0)
    cava_peak_threshold: float = Field(default=1e-4, ge=0, le=1)
    system_peak_threshold: float = Field(default=1e-4, ge=0, le=1)
    cava_stuck_high_threshold: float = Field(default=0.7, ge=0, le=1)
    system_silence_threshold: float = Field(default=0.001, ge=0, le=1)
    stuck_high_timeout: float = Field(default=5.0, gt=0)
    sensitivity: int = 100
    lower_cutoff_freq: int = 50
    higher_cutoff_freq: int = 10000
    framerate: int = Field(default=60, ge=1)
    noise_reduction: int = 77
    channels: str = "stereo"
    mono_option: str = "average"
    reverse: int = 0
    waveform: int = 0
    foreground: str = "#ffffff"
    gradient: int = 1
    gradient_color_1: str | None = None
    gradient_color_2: str | None = None
    gradient_color_3: str | None = None
    monstercat: int = 1
    waves: int = 0
    hide_empty: bool = False
    bar_type: Literal["bars", "bars_mirrored", "waves", "waves_mirrored"] = "bars"
    edge_fade: Annotated[int, Field(ge=0)] | tuple[
        Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]
    ] = 0
    keybindings: list[KeybindingConfig] = []
    callbacks: CavaCallbacksConfig = CavaCallbacksConfig()
