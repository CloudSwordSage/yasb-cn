import logging

from core.widgets.services.quick_launch.base_provider import BaseProvider, ProviderResult
from core.widgets.services.quick_launch.providers.resources.icons import (
    ICON_HIBERNATE,
    ICON_LOCK,
    ICON_RESTART,
    ICON_SHUTDOWN,
    ICON_SIGN_OUT,
    ICON_SLEEP,
    ICON_SYSTEM,
)

_SYSTEM_COMMANDS = [
    {
        "keywords": ["shutdown", "shut down", "power off", "turn off", "关机", "关闭电脑"],
        "title": "关机",
        "description": "关闭计算机",
        "icon": ICON_SHUTDOWN,
        "action": "shutdown",
    },
    {
        "keywords": ["restart", "reboot", "重启", "重新启动"],
        "title": "重新启动",
        "description": "重新启动计算机",
        "icon": ICON_RESTART,
        "action": "restart",
    },
    {
        "keywords": ["sleep", "stand by", "standby", "睡眠", "待机"],
        "title": "睡眠",
        "description": "让计算机进入睡眠状态",
        "icon": ICON_SLEEP,
        "action": "sleep",
    },
    {
        "keywords": ["hibernate", "休眠"],
        "title": "休眠",
        "description": "让计算机进入休眠状态",
        "icon": ICON_HIBERNATE,
        "action": "hibernate",
    },
    {
        "keywords": ["lock", "lock screen", "锁定", "锁屏"],
        "title": "锁定",
        "description": "锁定工作站",
        "icon": ICON_LOCK,
        "action": "lock",
    },
    {
        "keywords": ["sign out", "signout", "log out", "logout", "log off", "logoff", "注销", "退出登录"],
        "title": "注销",
        "description": "注销当前会话",
        "icon": ICON_SIGN_OUT,
        "action": "signout",
    },
    {
        "keywords": ["force shutdown", "force shut down", "强制关机"],
        "title": "强制关机",
        "description": "强制关机（跳过应用关闭提示）",
        "icon": ICON_SHUTDOWN,
        "action": "force_shutdown",
    },
    {
        "keywords": ["force restart", "force reboot", "强制重启", "强制重新启动"],
        "title": "强制重新启动",
        "description": "强制重新启动（跳过应用关闭提示）",
        "icon": ICON_RESTART,
        "action": "force_restart",
    },
]


class SystemCommandsProvider(BaseProvider):
    """Provide system commands like shutdown, restart, lock, sleep."""

    name = "system_commands"
    display_name = "系统命令"
    input_placeholder = "搜索系统命令..."
    icon = ICON_SYSTEM

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._power_ops = None

    @property
    def power_ops(self):
        if self._power_ops is None:
            from core.widgets.services.power_menu.power_commands import PowerOperations

            self._power_ops = PowerOperations()
        return self._power_ops

    def match(self, text: str) -> bool:
        text = text.strip()
        if self.prefix and text.startswith(self.prefix):
            return True
        # Also match if the text directly matches a system command keyword
        text_lower = text.lower()
        if len(text_lower) >= 3:
            for cmd in _SYSTEM_COMMANDS:
                for kw in cmd["keywords"]:
                    if text_lower in kw or kw.startswith(text_lower):
                        return True
        return False

    def get_results(self, text: str, **kwargs) -> list[ProviderResult]:
        query = (
            self.get_query_text(text).lower() if self.prefix and text.startswith(self.prefix) else text.strip().lower()
        )

        if not query:
            return [
                ProviderResult(
                    title=cmd["title"],
                    description=cmd["description"],
                    icon_char=cmd["icon"],
                    provider=self.name,
                    action_data={"action": cmd["action"]},
                )
                for cmd in _SYSTEM_COMMANDS
            ]

        results = []
        for cmd in _SYSTEM_COMMANDS:
            match_score = 0
            for kw in cmd["keywords"]:
                if query == kw:
                    match_score = 100
                    break
                if kw.startswith(query):
                    match_score = max(match_score, 80)
                elif query in kw:
                    match_score = max(match_score, 60)

            if match_score > 0:
                results.append(
                    (
                        match_score,
                        ProviderResult(
                            title=cmd["title"],
                            description=cmd["description"],
                            icon_char=cmd["icon"],
                            provider=self.name,
                            action_data={"action": cmd["action"]},
                        ),
                    )
                )

        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results]

    def execute(self, result: ProviderResult) -> bool:
        action = result.action_data.get("action", "")
        ops = self.power_ops
        try:
            action_map = {
                "shutdown": ops.shutdown,
                "restart": ops.restart,
                "sleep": ops.sleep,
                "hibernate": ops.hibernate,
                "lock": ops.lock,
                "signout": ops.signout,
                "force_shutdown": ops.force_shutdown,
                "force_restart": ops.force_restart,
            }
            fn = action_map.get(action)
            if fn:
                fn()
        except Exception as e:
            logging.error("System command '%s' failed: %s", action, e)
        return True
