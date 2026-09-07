from typing import Literal

from pydantic import Field

from core.validation.widgets.base_model import (
    CallbacksConfig,
    CustomBaseModel,
    KeybindingConfig,
)


class CategoryConfig(CustomBaseModel):
    label: str


class TodoIconsConfig(CustomBaseModel):
    add: str = "新建任务"
    edit: str = "编辑"
    delete: str = "删除"
    date: str = "\ue641"
    category: str = "\uf412"
    checked: str = "\udb80\udd34"
    unchecked: str = "\udb80\udd30"
    sort: str = "\ueab4"
    no_tasks: str = "\uf4a0"


class TodoMenuConfig(CustomBaseModel):
    blur: bool = True
    round_corners: bool = True
    round_corners_type: Literal["normal", "small"] = "normal"
    border_color: str = "system"
    alignment: str = "left"
    direction: str = "down"
    offset_top: int = 6
    offset_left: int = 0


class CallbacksTodoConfig(CallbacksConfig):
    on_left: str = "toggle_menu"
    on_middle: str = "do_nothing"
    on_right: str = "toggle_label"


class TodoConfig(CustomBaseModel):
    label: str = "\uf4a0 {count}/{completed}"
    label_alt: str = "\uf4a0 任务：{count}"
    data_path: str = ""
    menu: TodoMenuConfig = TodoMenuConfig()
    icons: TodoIconsConfig = TodoIconsConfig()
    categories: dict[str, CategoryConfig] = Field(
        default={
            "default": CategoryConfig(label="常规"),
            "urgent": CategoryConfig(label="紧急"),
            "important": CategoryConfig(label="重要"),
            "soon": CategoryConfig(label="即将完成"),
            "today": CategoryConfig(label="当天结束前"),
        }
    )
    keybindings: list[KeybindingConfig] = []
    callbacks: CallbacksTodoConfig = CallbacksTodoConfig()
