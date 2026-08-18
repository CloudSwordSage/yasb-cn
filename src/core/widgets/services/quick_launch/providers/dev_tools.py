import base64
import hashlib
import json
import random
import secrets
import string
import time
import urllib.parse
import uuid
from datetime import UTC, datetime

from PyQt6.QtWidgets import QApplication

from core.widgets.services.quick_launch.base_provider import (
    BaseProvider,
    ProviderMenuAction,
    ProviderMenuActionResult,
    ProviderResult,
)
from core.widgets.services.quick_launch.providers.resources.icons import ICON_DEV_TOOLS

_LOREM_WORDS = (
    "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam "
    "quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo "
    "consequat duis aute irure dolor in reprehenderit in voluptate velit esse "
    "cillum dolore eu fugiat nulla pariatur excepteur sint occaecat cupidatat "
    "non proident sunt in culpa qui officia deserunt mollit anim id est laborum"
).split()

_TOOLS: dict[str, dict[str, str]] = {
    "uuid": {
        "name": "UUID 生成器",
        "description": "生成随机 UUID v4 值",
    },
    "hash": {
        "name": "哈希生成器",
        "description": "生成文本的 MD5、SHA1、SHA256、SHA512 哈希值",
    },
    "base64": {
        "name": "Base64 编码/解码",
        "description": "编码或解码 Base64 字符串",
    },
    "url": {
        "name": "URL 编码/解码",
        "description": "对 URL 字符串进行百分号编码或解码",
    },
    "jwt": {
        "name": "JWT 解码器",
        "description": "解码 JWT 令牌载荷（不验证）",
    },
    "lorem": {
        "name": "Lorem Ipsum",
        "description": "生成占位文本",
    },
    "ts": {
        "name": "时间戳转换器",
        "description": "在 Unix 时间戳与日期之间转换",
    },
    "pw": {
        "name": "密码生成器",
        "description": "生成安全的随机密码",
    },
}


class DevToolsProvider(BaseProvider):
    """Developer utilities accessible from Quick Launch.

    Type the prefix (default ``dev``) to see available tools, then pick one
    or type a tool name directly, e.g. ``dev uuid``, ``dev hash hello``.
    """

    name = "dev_tools"
    display_name = "开发工具"
    icon = ICON_DEV_TOOLS
    input_placeholder = "选择工具或输入命令..."

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def match(self, text: str) -> bool:
        if self.prefix:
            stripped = text.strip()
            return stripped == self.prefix or stripped.startswith(self.prefix + " ")
        return True

    def get_results(self, text: str, **kwargs) -> list[ProviderResult]:
        query = self.get_query_text(text).strip()
        parts = query.split(None, 1)

        if not query:
            return self._tool_tiles()

        tool_key = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        handler = {
            "uuid": self._uuid_results,
            "hash": self._hash_results,
            "base64": self._base64_results,
            "url": self._url_results,
            "jwt": self._jwt_results,
            "lorem": self._lorem_results,
            "ts": self._timestamp_results,
            "pw": self._password_results,
        }.get(tool_key)

        if handler:
            return handler(arg)

        filtered = self._filter_tools(query)
        if filtered:
            return filtered
        return self._tool_tiles()

    def execute(self, result: ProviderResult) -> bool | None:
        data = result.action_data
        copy_text = data.get("copy")
        if copy_text is not None:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(str(copy_text))
            return True
        return None

    def get_context_menu_actions(self, result):
        actions: list[ProviderMenuAction] = []
        data = result.action_data
        if data.get("copy") is not None:
            actions.append(ProviderMenuAction(id="copy", label="复制到剪贴板"))
        return actions

    def execute_context_menu_action(self, action_id, result):
        data = result.action_data
        if action_id == "copy":
            copy_text = data.get("copy", "")
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(str(copy_text))
            return ProviderMenuActionResult(close_popup=True)
        return ProviderMenuActionResult()

    def get_query_text(self, text: str) -> str:
        if self.prefix and text.strip().startswith(self.prefix):
            return text.strip()[len(self.prefix) :].strip()
        return text.strip()

    def _tool_tiles(self) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for key, info in _TOOLS.items():
            results.append(
                ProviderResult(
                    title=info["name"],
                    description=info["description"],
                    icon_char=ICON_DEV_TOOLS,
                    provider=self.name,
                    action_data={"_home": True, "prefix": self.prefix, "initial_text": key},
                )
            )
        return results

    def _filter_tools(self, query: str) -> list[ProviderResult]:
        q = query.lower()
        results: list[ProviderResult] = []
        for key, info in _TOOLS.items():
            if q in key or q in info["name"].lower() or q in info["description"].lower():
                results.append(
                    ProviderResult(
                        title=info["name"],
                        description=info["description"],
                        icon_char=ICON_DEV_TOOLS,
                        provider=self.name,
                        action_data={"_home": True, "prefix": self.prefix, "initial_text": key},
                    )
                )
        return results

    def _make_result(self, title: str, description: str, copy_text: str) -> ProviderResult:
        return ProviderResult(
            title=title,
            description=description,
            icon_char=ICON_DEV_TOOLS,
            provider=self.name,
            action_data={"copy": copy_text},
        )

    def _uuid_results(self, arg: str) -> list[ProviderResult]:
        count = 5
        if arg.isdigit():
            count = min(int(arg), 20)
        results: list[ProviderResult] = []
        for _ in range(count):
            val = str(uuid.uuid4())
            results.append(self._make_result(val, "点击复制 UUID v4", val))
        return results

    def _hash_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“hash”后输入文本", "例如：dev hash hello world", "")]
        data = arg.encode("utf-8")
        results: list[ProviderResult] = []
        for name, func in [
            ("MD5", hashlib.md5),
            ("SHA1", hashlib.sha1),
            ("SHA256", hashlib.sha256),
            ("SHA512", hashlib.sha512),
        ]:
            digest = func(data).hexdigest()
            results.append(self._make_result(digest, f"{name} - 点击复制", digest))
        return results

    def _base64_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“base64”后输入文本", "编码为 Base64；粘贴 Base64 内容可解码。", "")]
        results: list[ProviderResult] = []
        encoded = base64.b64encode(arg.encode("utf-8")).decode("ascii")
        results.append(self._make_result(encoded, "Base64 已编码 - 点击复制", encoded))
        try:
            decoded = base64.b64decode(arg).decode("utf-8")
            results.append(self._make_result(decoded, "Base64 已解码 - 点击复制", decoded))
        except Exception:
            pass
        return results

    def _url_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“url”后输入文本", "对字符串进行 URL 编码或解码", "")]
        results: list[ProviderResult] = []
        encoded = urllib.parse.quote(arg, safe="")
        results.append(self._make_result(encoded, "URL 已编码 - 点击复制", encoded))
        try:
            decoded = urllib.parse.unquote(arg)
            if decoded != arg:
                results.append(self._make_result(decoded, "URL 已解码 - 点击复制", decoded))
        except Exception:
            pass
        return results

    def _jwt_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“jwt”后粘贴 JWT 令牌", "解码载荷（不验证）", "")]
        try:
            parts = arg.split(".")
            if len(parts) < 2:
                return [self._make_result("JWT 无效", "应为 header.payload.signature 格式", "")]
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
            pretty = json.dumps(payload, indent=2, ensure_ascii=False)
            results: list[ProviderResult] = []
            results.append(self._make_result("JWT 载荷", "点击复制已解码的 JSON", pretty))
            for key, value in payload.items():
                display_val = str(value)
                if key in ("exp", "iat", "nbf") and isinstance(value, (int, float)):
                    try:
                        dt = datetime.fromtimestamp(value, tz=UTC)
                        display_val = f"{value} ({dt.strftime('%Y-%m-%d %H:%M:%S UTC')})"
                    except Exception:
                        pass
                results.append(self._make_result(f"{key}: {display_val}", "点击复制值", str(value)))
            return results
        except Exception:
            return [self._make_result("无法解码 JWT", "请确认令牌有效", "")]

    def _lorem_results(self, arg: str) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        counts = [1, 2, 3, 5]
        for n in counts:
            text = self._generate_lorem(n)
            label = f"{n} 段"
            desc = text[:80] + "..." if len(text) > 80 else text
            results.append(self._make_result(label, desc, text))
        word_counts = [10, 25, 50]
        for n in word_counts:
            words = " ".join(random.choices(_LOREM_WORDS, k=n))
            words = words[0].upper() + words[1:] + "."
            results.append(self._make_result(f"{n} 个词", words[:80] + "..." if len(words) > 80 else words, words))
        return results

    def _generate_lorem(self, paragraphs: int) -> str:
        paras: list[str] = []
        for _ in range(paragraphs):
            sentence_count = random.randint(4, 8)
            sentences: list[str] = []
            for _ in range(sentence_count):
                length = random.randint(6, 15)
                words = " ".join(random.choices(_LOREM_WORDS, k=length))
                words = words[0].upper() + words[1:] + "."
                sentences.append(words)
            paras.append(" ".join(sentences))
        return "\n\n".join(paras)

    def _timestamp_results(self, arg: str) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        now = time.time()
        now_int = int(now)
        now_dt = datetime.fromtimestamp(now, tz=UTC)

        results.append(
            self._make_result(
                f"当前：{now_int}",
                now_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                str(now_int),
            )
        )
        results.append(
            self._make_result(
                f"当前（毫秒）：{int(now * 1000)}",
                "毫秒时间戳",
                str(int(now * 1000)),
            )
        )
        results.append(
            self._make_result(
                f"ISO 8601: {now_dt.isoformat()}",
                "点击复制",
                now_dt.isoformat(),
            )
        )

        if arg:
            arg_stripped = arg.strip()
            try:
                ts_val = float(arg_stripped)
                if ts_val > 1e12:
                    ts_val = ts_val / 1000
                dt = datetime.fromtimestamp(ts_val, tz=UTC)
                local_dt = datetime.fromtimestamp(ts_val)
                results.append(
                    self._make_result(
                        f"UTC：{dt.strftime('%Y-%m-%d %H:%M:%S')}",
                        f"Unix {int(ts_val)} - 点击复制",
                        dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    )
                )
                results.append(
                    self._make_result(
                        f"本地：{local_dt.strftime('%Y-%m-%d %H:%M:%S')}",
                        "本地时区 - 点击复制",
                        local_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                )
                results.append(
                    self._make_result(
                        f"ISO: {dt.isoformat()}",
                        "点击复制 ISO 8601",
                        dt.isoformat(),
                    )
                )
            except ValueError, OverflowError, OSError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
                    try:
                        dt = datetime.strptime(arg_stripped, fmt).replace(tzinfo=UTC)
                        ts_int = int(dt.timestamp())
                        results.append(
                            self._make_result(
                                f"Unix：{ts_int}",
                                f"来自 {arg_stripped} - 点击复制",
                                str(ts_int),
                            )
                        )
                        results.append(
                            self._make_result(
                                f"毫秒：{ts_int * 1000}",
                                "点击复制",
                                str(ts_int * 1000),
                            )
                        )
                        break
                    except ValueError:
                        continue

        return results

    def _password_results(self, arg: str) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        length = 16
        if arg.isdigit():
            length = max(4, min(int(arg), 128))

        chars_all = string.ascii_letters + string.digits + string.punctuation
        chars_alpha = string.ascii_letters + string.digits
        chars_hex = string.hexdigits[:16]

        pw_full = "".join(secrets.choice(chars_all) for _ in range(length))
        pw_alpha = "".join(secrets.choice(chars_alpha) for _ in range(length))
        pw_hex = "".join(secrets.choice(chars_hex) for _ in range(length))
        passphrase = "-".join("".join(random.choices(string.ascii_lowercase, k=random.randint(4, 7))) for _ in range(4))

        results.append(self._make_result(pw_full, f"完整（{length} 个字符）- 字母、数字和符号", pw_full))
        results.append(self._make_result(pw_alpha, f"字母数字（{length} 个字符）- 字母和数字", pw_alpha))
        results.append(self._make_result(pw_hex, f"十六进制（{length} 个字符）", pw_hex))
        results.append(self._make_result(passphrase, "密码短语 - 4 个随机词", passphrase))
        return results
