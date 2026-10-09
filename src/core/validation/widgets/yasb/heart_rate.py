from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import CallbacksConfig, CustomBaseModel, KeybindingConfig

Statistic = Literal["current", "avg", "min", "max", "median", "stddev", "range", "sample_count"]


class HeartRateGraphConfig(CustomBaseModel):
    """Time-based graph options; height is always allocated by the bar layout."""

    enabled: bool = True
    width: int = Field(default=120, ge=16, le=2000)
    window_seconds: int = Field(default=60, ge=1, le=3600)
    min_y_range: float = Field(default=20, ge=1, le=65535)
    show_grid: bool = False
    show_average_line: bool = False
    show_latest_point: bool = True
    gap_on_disconnect: bool = True


class HeartRateStatisticsConfig(CustomBaseModel):
    """Ordered statistics; spacing is horizontal and never increases bar height."""

    statistics: list[Statistic] = Field(default_factory=lambda: ["avg", "max"], max_length=16)
    separator: str = " · "
    spacing: int = Field(default=0, ge=0, le=50)


class HeartRateDisplayConfig(CustomBaseModel):
    """Two layouts sharing the same source and statistics window."""

    default_mode: Literal["normal", "detailed"] = "normal"
    normal: HeartRateStatisticsConfig = Field(default_factory=HeartRateStatisticsConfig)
    detailed: HeartRateStatisticsConfig = Field(
        default_factory=lambda: HeartRateStatisticsConfig(
            statistics=["current", "avg", "min", "max", "median", "stddev", "range", "sample_count"],
            separator=" │ ",
        )
    )


class HeartRateConnectionConfig(CustomBaseModel):
    """Timeouts in milliseconds; reconnect delay starts after attempt cleanup."""

    auto_connect: bool = True
    reconnect_interval: int = Field(default=2000, ge=100, le=300000)
    connect_timeout: int = Field(default=8000, ge=100, le=120000)
    stale_timeout: int = Field(default=10000, ge=100, le=300000)
    scan_timeout: int = Field(default=5000, ge=100, le=120000)
    scan_concurrency: int = Field(default=2, ge=1, le=4)


class HeartRateMenuConfig(CustomBaseModel):
    """Existing YASB popup positioning and native appearance options."""

    blur: bool = True
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "System"
    alignment: Literal["left", "center", "right"] = "right"
    direction: Literal["up", "down"] = "down"
    offset_top: int = 6
    offset_left: int = 0


class HeartRateCallbacksConfig(CallbacksConfig):
    on_left: str = "toggle_device_menu"
    on_right: str = "toggle_display_mode"


class HeartRateConfig(CustomBaseModel):
    """BLE heart rate widget configuration validated by WidgetBuilder."""

    class_name: str = "heart-rate-widget"
    graph: HeartRateGraphConfig = Field(default_factory=HeartRateGraphConfig)
    display: HeartRateDisplayConfig = Field(default_factory=HeartRateDisplayConfig)
    connection: HeartRateConnectionConfig = Field(default_factory=HeartRateConnectionConfig)
    callbacks: HeartRateCallbacksConfig = Field(default_factory=HeartRateCallbacksConfig)
    menu_config: HeartRateMenuConfig = Field(default_factory=HeartRateMenuConfig)
    keybindings: list[KeybindingConfig] = Field(default_factory=list)
