from core.utils.shell_utils import shell_open
from core.widgets.services.quick_launch.base_provider import BaseProvider, ProviderResult
from core.widgets.services.quick_launch.providers.resources.icons import (
    ICON_SETTINGS,
    ICON_SETTINGS_PAGE_ABOUT,
    ICON_SETTINGS_PAGE_ACCESSIBILITY,
    ICON_SETTINGS_PAGE_ACCOUNTS,
    ICON_SETTINGS_PAGE_BLUETOOTH,
    ICON_SETTINGS_PAGE_CAMERA,
    ICON_SETTINGS_PAGE_COLORS,
    ICON_SETTINGS_PAGE_DATE_TIME,
    ICON_SETTINGS_PAGE_DEFAULT_APPS,
    ICON_SETTINGS_PAGE_DISPLAY,
    ICON_SETTINGS_PAGE_ETHERNET,
    ICON_SETTINGS_PAGE_FOCUS,
    ICON_SETTINGS_PAGE_INSTALLED_APPS,
    ICON_SETTINGS_PAGE_LANGUAGE_REGION,
    ICON_SETTINGS_PAGE_LOCK_SCREEN,
    ICON_SETTINGS_PAGE_MOBILE_HOTSPOT,
    ICON_SETTINGS_PAGE_MOUSE,
    ICON_SETTINGS_PAGE_MULTITASKING,
    ICON_SETTINGS_PAGE_NIGHT_LIGHT,
    ICON_SETTINGS_PAGE_NOTIFICATIONS,
    ICON_SETTINGS_PAGE_PERSONALIZATION,
    ICON_SETTINGS_PAGE_POWER_BATTERY,
    ICON_SETTINGS_PAGE_PRINTERS_SCANNERS,
    ICON_SETTINGS_PAGE_PRIVACY_SECURITY,
    ICON_SETTINGS_PAGE_PROXY,
    ICON_SETTINGS_PAGE_SIGN_IN_OPTIONS,
    ICON_SETTINGS_PAGE_SOUND,
    ICON_SETTINGS_PAGE_START,
    ICON_SETTINGS_PAGE_STARTUP_APPS,
    ICON_SETTINGS_PAGE_STORAGE,
    ICON_SETTINGS_PAGE_TASKBAR,
    ICON_SETTINGS_PAGE_TOUCHPAD,
    ICON_SETTINGS_PAGE_TYPING,
    ICON_SETTINGS_PAGE_VPN,
    ICON_SETTINGS_PAGE_WI_FI,
    ICON_SETTINGS_PAGE_WINDOWS_SECURITY,
    ICON_SETTINGS_PAGE_WINDOWS_UPDATE,
)

_SETTINGS_PAGES = [
    {
        "keywords": ["wifi", "wi-fi", "wireless", "network", "无线", "网络"],
        "title": "Wi-Fi",
        "description": "网络和 Internet > Wi-Fi",
        "icon": ICON_SETTINGS_PAGE_WI_FI,
        "uri": "ms-settings:network-wifi",
    },
    {
        "keywords": ["bluetooth", "蓝牙"],
        "title": "Bluetooth",
        "description": "蓝牙和设备",
        "icon": ICON_SETTINGS_PAGE_BLUETOOTH,
        "uri": "ms-settings:bluetooth",
    },
    {
        "keywords": ["display", "screen", "monitor", "resolution", "scale", "scaling", "显示", "屏幕", "显示器", "分辨率", "缩放"],
        "title": "显示",
        "description": "系统 > 显示",
        "icon": ICON_SETTINGS_PAGE_DISPLAY,
        "uri": "ms-settings:display",
    },
    {
        "keywords": ["sound", "audio", "speaker", "volume", "microphone", "声音", "音频", "扬声器", "音量", "麦克风"],
        "title": "声音",
        "description": "系统 > 声音",
        "icon": ICON_SETTINGS_PAGE_SOUND,
        "uri": "ms-settings:sound",
    },
    {
        "keywords": ["notifications", "notification", "通知"],
        "title": "通知",
        "description": "系统 > 通知",
        "icon": ICON_SETTINGS_PAGE_NOTIFICATIONS,
        "uri": "ms-settings:notifications",
    },
    {
        "keywords": ["power", "battery", "energy", "power plan", "电源", "电池", "能源", "电源计划"],
        "title": "电源和电池",
        "description": "系统 > 电源和电池",
        "icon": ICON_SETTINGS_PAGE_POWER_BATTERY,
        "uri": "ms-settings:powersleep",
    },
    {
        "keywords": ["storage", "disk", "space", "cleanup", "存储", "磁盘", "空间", "清理"],
        "title": "存储",
        "description": "系统 > 存储",
        "icon": ICON_SETTINGS_PAGE_STORAGE,
        "uri": "ms-settings:storagesense",
    },
    {
        "keywords": ["multitasking", "snap", "virtual desktop", "多任务处理", "贴靠", "虚拟桌面"],
        "title": "多任务处理",
        "description": "系统 > 多任务处理",
        "icon": ICON_SETTINGS_PAGE_MULTITASKING,
        "uri": "ms-settings:multitasking",
    },
    {
        "keywords": ["vpn"],
        "title": "VPN",
        "description": "网络和 Internet > VPN",
        "icon": ICON_SETTINGS_PAGE_VPN,
        "uri": "ms-settings:network-vpn",
    },
    {
        "keywords": ["proxy", "代理"],
        "title": "代理",
        "description": "网络和 Internet > 代理",
        "icon": ICON_SETTINGS_PAGE_PROXY,
        "uri": "ms-settings:network-proxy",
    },
    {
        "keywords": ["personalization", "theme", "themes", "wallpaper", "background", "desktop background", "个性化", "主题", "壁纸", "背景", "桌面背景"],
        "title": "个性化",
        "description": "个性化",
        "icon": ICON_SETTINGS_PAGE_PERSONALIZATION,
        "uri": "ms-settings:personalization",
    },
    {
        "keywords": ["colors", "colour", "accent", "dark mode", "light mode", "颜色", "强调色", "深色模式", "浅色模式"],
        "title": "颜色",
        "description": "个性化 > 颜色",
        "icon": ICON_SETTINGS_PAGE_COLORS,
        "uri": "ms-settings:colors",
    },
    {
        "keywords": ["lock screen", "lockscreen", "锁屏", "锁定屏幕"],
        "title": "锁屏界面",
        "description": "个性化 > 锁屏界面",
        "icon": ICON_SETTINGS_PAGE_LOCK_SCREEN,
        "uri": "ms-settings:lockscreen",
    },
    {
        "keywords": ["taskbar"],
        "title": "Taskbar",
        "description": "个性化 > 任务栏",
        "icon": ICON_SETTINGS_PAGE_TASKBAR,
        "uri": "ms-settings:taskbar",
    },
    {
        "keywords": ["start menu", "start", "开始菜单", "开始"],
        "title": "开始",
        "description": "个性化 > 开始",
        "icon": ICON_SETTINGS_PAGE_START,
        "uri": "ms-settings:personalization-start",
    },
    {
        "keywords": ["apps", "installed apps", "programs", "uninstall", "add remove", "应用", "已安装的应用", "程序", "卸载", "添加删除"],
        "title": "已安装的应用",
        "description": "应用 > 已安装的应用",
        "icon": ICON_SETTINGS_PAGE_INSTALLED_APPS,
        "uri": "ms-settings:appsfeatures",
    },
    {
        "keywords": ["default apps", "defaults", "file association", "默认应用", "文件关联"],
        "title": "默认应用",
        "description": "应用 > 默认应用",
        "icon": ICON_SETTINGS_PAGE_DEFAULT_APPS,
        "uri": "ms-settings:defaultapps",
    },
    {
        "keywords": ["startup apps", "startup", "启动应用", "启动"],
        "title": "启动应用",
        "description": "应用 > 启动",
        "icon": ICON_SETTINGS_PAGE_STARTUP_APPS,
        "uri": "ms-settings:startupapps",
    },
    {
        "keywords": ["accounts", "account", "user", "profile", "账户", "用户", "配置文件", "你的信息"],
        "title": "账户",
        "description": "账户 > 你的信息",
        "icon": ICON_SETTINGS_PAGE_ACCOUNTS,
        "uri": "ms-settings:yourinfo",
    },
    {
        "keywords": ["signin", "sign in", "password", "pin", "hello", "登录", "登录选项", "密码"],
        "title": "登录选项",
        "description": "账户 > 登录选项",
        "icon": ICON_SETTINGS_PAGE_SIGN_IN_OPTIONS,
        "uri": "ms-settings:signinoptions",
    },
    {
        "keywords": ["date", "time", "timezone", "clock", "time zone", "日期", "时间", "时区", "时钟"],
        "title": "日期和时间",
        "description": "时间和语言 > 日期和时间",
        "icon": ICON_SETTINGS_PAGE_DATE_TIME,
        "uri": "ms-settings:dateandtime",
    },
    {
        "keywords": ["language", "region", "locale", "input", "语言", "区域", "区域设置", "输入"],
        "title": "语言和区域",
        "description": "时间和语言 > 语言和区域",
        "icon": ICON_SETTINGS_PAGE_LANGUAGE_REGION,
        "uri": "ms-settings:regionlanguage",
    },
    {
        "keywords": ["keyboard", "typing", "键盘", "输入"],
        "title": "输入",
        "description": "时间和语言 > 输入",
        "icon": ICON_SETTINGS_PAGE_TYPING,
        "uri": "ms-settings:typing",
    },
    {
        "keywords": ["update", "windows update", "check for updates", "更新", "Windows 更新", "检查更新"],
        "title": "Windows 更新",
        "description": "Windows 更新",
        "icon": ICON_SETTINGS_PAGE_WINDOWS_UPDATE,
        "uri": "ms-settings:windowsupdate",
    },
    {
        "keywords": ["privacy", "permissions", "隐私", "权限", "安全"],
        "title": "隐私和安全性",
        "description": "隐私和安全性",
        "icon": ICON_SETTINGS_PAGE_PRIVACY_SECURITY,
        "uri": "ms-settings:privacy",
    },
    {
        "keywords": ["windows security", "virus", "antivirus", "defender", "firewall", "protection", "Windows 安全中心", "病毒", "防病毒", "防火墙", "保护"],
        "title": "Windows 安全中心",
        "description": "隐私和安全性 > Windows 安全中心",
        "icon": ICON_SETTINGS_PAGE_WINDOWS_SECURITY,
        "uri": "ms-settings:windowsdefender",
    },
    {
        "keywords": ["mouse", "cursor", "pointer", "鼠标", "光标", "指针"],
        "title": "鼠标",
        "description": "蓝牙和设备 > 鼠标",
        "icon": ICON_SETTINGS_PAGE_MOUSE,
        "uri": "ms-settings:mousetouchpad",
    },
    {
        "keywords": ["touchpad", "触摸板"],
        "title": "触摸板",
        "description": "蓝牙和设备 > 触摸板",
        "icon": ICON_SETTINGS_PAGE_TOUCHPAD,
        "uri": "ms-settings:devices-touchpad",
    },
    {
        "keywords": ["printers", "printer", "scanners", "打印机", "扫描仪"],
        "title": "打印机和扫描仪",
        "description": "蓝牙和设备 > 打印机和扫描仪",
        "icon": ICON_SETTINGS_PAGE_PRINTERS_SCANNERS,
        "uri": "ms-settings:printers",
    },
    {
        "keywords": ["camera", "webcam", "相机", "摄像头"],
        "title": "相机",
        "description": "蓝牙和设备 > 相机",
        "icon": ICON_SETTINGS_PAGE_CAMERA,
        "uri": "ms-settings:camera",
    },
    {
        "keywords": ["accessibility", "ease of access", "narrator", "辅助功能", "轻松使用", "讲述人"],
        "title": "辅助功能",
        "description": "辅助功能",
        "icon": ICON_SETTINGS_PAGE_ACCESSIBILITY,
        "uri": "ms-settings:easeofaccess",
    },
    {
        "keywords": ["about", "system info", "device name", "rename pc", "specs", "specifications", "关于", "系统信息", "设备名称", "重命名电脑", "规格"],
        "title": "系统信息",
        "description": "系统 > 系统信息",
        "icon": ICON_SETTINGS_PAGE_ABOUT,
        "uri": "ms-settings:about",
    },
    {
        "keywords": ["night light", "nightlight", "blue light", "夜间模式", "蓝光"],
        "title": "夜间模式",
        "description": "系统 > 显示 > 夜间模式",
        "icon": ICON_SETTINGS_PAGE_NIGHT_LIGHT,
        "uri": "ms-settings:nightlight",
    },
    {
        "keywords": ["focus", "do not disturb", "focus assist", "专注", "请勿打扰", "专注助手"],
        "title": "专注",
        "description": "系统 > 专注",
        "icon": ICON_SETTINGS_PAGE_FOCUS,
        "uri": "ms-settings:quiethours",
    },
    {
        "keywords": ["ethernet", "wired", "lan", "以太网", "有线", "局域网"],
        "title": "以太网",
        "description": "网络和 Internet > 以太网",
        "icon": ICON_SETTINGS_PAGE_ETHERNET,
        "uri": "ms-settings:network-ethernet",
    },
    {
        "keywords": ["mobile hotspot", "hotspot", "tethering", "移动热点", "热点", "网络共享"],
        "title": "移动热点",
        "description": "网络和 Internet > 移动热点",
        "icon": ICON_SETTINGS_PAGE_MOBILE_HOTSPOT,
        "uri": "ms-settings:network-mobilehotspot",
    },
]


class SettingsProvider(BaseProvider):
    """Quick access to Windows Settings pages."""

    name = "settings"
    display_name = "Windows 设置"
    input_placeholder = "搜索 Windows 设置..."
    icon = ICON_SETTINGS

    def match(self, text: str) -> bool:
        if self.prefix and text.strip().startswith(self.prefix):
            return True
        text_lower = text.strip().lower()
        if len(text_lower) < 2:
            return False
        for page in _SETTINGS_PAGES:
            for kw in page["keywords"]:
                if text_lower in kw or kw.startswith(text_lower):
                    return True
        return False

    def get_results(self, text: str, **kwargs) -> list[ProviderResult]:
        query = (
            self.get_query_text(text).lower()
            if self.prefix and text.strip().startswith(self.prefix)
            else text.strip().lower()
        )

        if not query:
            return [
                ProviderResult(
                    title=page["title"],
                    description=page["description"],
                    icon_char=page["icon"],
                    provider=self.name,
                    action_data={"uri": page["uri"]},
                )
                for page in _SETTINGS_PAGES
            ]

        results = []
        for page in _SETTINGS_PAGES:
            matched = any(query in kw or kw.startswith(query) for kw in page["keywords"])
            if not matched:
                matched = query in page["title"].lower()
            if matched:
                results.append(
                    ProviderResult(
                        title=page["title"],
                        description=page["description"],
                        icon_char=page["icon"],
                        provider=self.name,
                        action_data={"uri": page["uri"]},
                    )
                )
        return results

    def execute(self, result: ProviderResult) -> bool:
        uri = result.action_data.get("uri", "")
        if not uri:
            return False
        shell_open(uri)
        return True
