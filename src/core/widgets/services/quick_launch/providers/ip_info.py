import ipaddress
import json
import logging
import socket
import subprocess
import urllib.error
import urllib.request

from PyQt6.QtWidgets import QApplication

from core.widgets.services.quick_launch.base_provider import (
    BaseProvider,
    ProviderMenuAction,
    ProviderMenuActionResult,
    ProviderResult,
)
from core.widgets.services.quick_launch.providers.resources.icons import ICON_IP_INFO

_TOOLS: dict[str, dict[str, str]] = {
    "info": {
        "name": "我的网络接口",
        "description": "显示本地网络接口的 IP 和 MAC 地址",
    },
    "public": {
        "name": "公网 IP",
        "description": "获取外部 IP 地址（需要联网）",
    },
    "calc": {
        "name": "子网计算器",
        "description": "根据 CIDR 计算网络、广播地址和主机范围",
    },
    "check": {
        "name": "IP 检查",
        "description": "分析 IP 地址（类型、类别、二进制、十六进制）",
    },
    "dns": {
        "name": "DNS 查询",
        "description": "将主机名解析为 IP 地址",
    },
    "mac": {
        "name": "MAC 地址",
        "description": "列出所有网络适配器的 MAC 地址",
    },
}


def _parse_ipconfig() -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = result.stdout
    except Exception:
        return []

    adapters: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not line.startswith(" ") and not line.startswith("\t"):
            if "adapter" in line.lower():
                if current.get("name"):
                    adapters.append(current)
                name = line.split("adapter", 1)[-1].strip().rstrip(":")
                current = {"name": name}
            continue
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        if "physical address" in key and "mac" not in current:
            current["mac"] = val.upper()
        elif "ipv4 address" in key and "ipv4" not in current:
            current["ipv4"] = val.split("(")[0].strip()
        elif ("link-local ipv6" in key or "ipv6 address" in key) and "ipv6" not in current:
            current["ipv6"] = val.split("%")[0].strip()
        elif "subnet mask" in key and "mask" not in current:
            current["mask"] = val
        elif "description" in key and "desc" not in current:
            current["desc"] = val

    if current.get("name"):
        adapters.append(current)

    return [a for a in adapters if a.get("ipv4") or a.get("mac")]


class IpInfoProvider(BaseProvider):
    """IP and network information utilities.

    Type the prefix (default ``ip``) to see available tools, then pick one
    or type a sub-command directly, e.g. ``ip info``, ``ip calc 10.0.0.0/24``.
    """

    name = "ip_info"
    display_name = "IP / 网络信息"
    icon = ICON_IP_INFO
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
            "info": self._info_results,
            "public": self._public_results,
            "calc": self._calc_results,
            "check": self._check_results,
            "dns": self._dns_results,
            "mac": self._mac_results,
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
                    icon_char=ICON_IP_INFO,
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
                        icon_char=ICON_IP_INFO,
                        provider=self.name,
                        action_data={"_home": True, "prefix": self.prefix, "initial_text": key},
                    )
                )
        return results

    def _make_result(self, title: str, description: str, copy_text: str) -> ProviderResult:
        return ProviderResult(
            title=title,
            description=description,
            icon_char=ICON_IP_INFO,
            provider=self.name,
            action_data={"copy": copy_text},
        )

    def _info_results(self, arg: str) -> list[ProviderResult]:
        adapters = _parse_ipconfig()
        if not adapters:
            return [self._make_result("未找到网络接口", "无法读取 ipconfig 输出", "")]

        results: list[ProviderResult] = []
        hostname = socket.gethostname()
        results.append(self._make_result(f"主机名：{hostname}", "点击复制", hostname))

        for adapter in adapters:
            name = adapter.get("name", "Unknown")
            desc = adapter.get("desc", "")
            ipv4 = adapter.get("ipv4", "")
            ipv6 = adapter.get("ipv6", "")
            mask = adapter.get("mask", "")
            mac = adapter.get("mac", "")

            label = name
            if desc:
                label = f"{name} ({desc[:40]})" if len(desc) > 40 else f"{name} ({desc})"

            parts: list[str] = []
            if ipv4:
                parts.append(ipv4)
            if mask:
                parts.append(f"掩码 {mask}")
            if mac:
                parts.append(mac)
            detail = " | ".join(parts)

            copy_val = ipv4 or mac or name
            results.append(self._make_result(label, detail, copy_val))

            if ipv6:
                results.append(self._make_result(f"  IPv6：{ipv6}", f"{name} - 点击复制", ipv6))

        return results

    def _public_results(self, arg: str) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        try:
            req = urllib.request.Request(
                "http://ip-api.com/json/?fields=query,isp,org,city,regionName,country,timezone,as",
                headers={"User-Agent": "yasb-quick-launch/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            ip = data.get("query", "未知")
            results.append(self._make_result(f"公网 IP：{ip}", "点击复制", ip))

            isp = data.get("isp", "")
            if isp:
                results.append(self._make_result(f"ISP：{isp}", "点击复制", isp))

            org = data.get("org", "")
            if org and org != isp:
                results.append(self._make_result(f"组织：{org}", "点击复制", org))

            city = data.get("city", "")
            region = data.get("regionName", "")
            country = data.get("country", "")
            location_parts = [p for p in [city, region, country] if p]
            if location_parts:
                loc = ", ".join(location_parts)
                results.append(self._make_result(f"位置：{loc}", "点击复制", loc))

            tz = data.get("timezone", "")
            if tz:
                results.append(self._make_result(f"时区：{tz}", "点击复制", tz))

            asn = data.get("as", "")
            if asn:
                results.append(self._make_result(f"AS：{asn}", "点击复制", asn))

        except urllib.error.URLError as e:
            reason = getattr(e, "reason", str(e))
            logging.warning("IP Info: failed to fetch public IP: %s", reason)
            results.append(self._make_result("无法获取公网 IP", "请检查网络连接", ""))
        except Exception as e:
            logging.debug("IP Info: unexpected error fetching public IP: %s", e)
            results.append(self._make_result("无法获取公网 IP", str(e), ""))

        return results

    def _calc_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“calc”后输入 CIDR 表示法", "例如：ip calc 192.168.1.0/24", "")]

        try:
            network = ipaddress.ip_network(arg.strip(), strict=False)
        except ValueError:
            return [self._make_result("CIDR 表示法无效", f"无法解析“{arg}”", "")]

        results: list[ProviderResult] = []
        results.append(
            self._make_result(
                f"网络：{network.network_address}",
                f"/{network.prefixlen}",
                str(network.network_address),
            )
        )

        if isinstance(network, ipaddress.IPv4Network):
            results.append(
                self._make_result(
                    f"广播地址：{network.broadcast_address}",
                    "点击复制",
                    str(network.broadcast_address),
                )
            )
            results.append(
                self._make_result(
                    f"子网掩码：{network.netmask}",
                    f"通配符掩码：{network.hostmask}",
                    str(network.netmask),
                )
            )
            results.append(
                self._make_result(
                    f"通配符掩码：{network.hostmask}",
                    "点击复制",
                    str(network.hostmask),
                )
            )

        num_hosts = (
            network.num_addresses - 2
            if network.prefixlen < 31 and isinstance(network, ipaddress.IPv4Network)
            else network.num_addresses
        )
        results.append(
            self._make_result(
                f"主机总数：{num_hosts:,}",
                f"地址总数：{network.num_addresses:,}",
                str(num_hosts),
            )
        )

        if isinstance(network, ipaddress.IPv4Network) and network.prefixlen < 31:
            hosts = list(network.hosts())
            if hosts:
                first = str(hosts[0])
                last = str(hosts[-1])
                range_str = f"{first} - {last}"
                results.append(
                    self._make_result(
                        f"主机范围：{range_str}",
                        "点击复制",
                        range_str,
                    )
                )

        results.append(
            self._make_result(
                f"CIDR: {network.with_prefixlen}",
                "点击复制",
                network.with_prefixlen,
            )
        )

        return results

    def _check_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“check”后输入 IP 地址", "例如：ip check 192.168.1.1", "")]

        try:
            addr = ipaddress.ip_address(arg.strip())
        except ValueError:
            return [self._make_result("IP 地址无效", f"无法解析“{arg}”", "")]

        results: list[ProviderResult] = []
        results.append(self._make_result(str(addr), f"版本：IPv{addr.version}", str(addr)))

        if addr.is_private:
            results.append(self._make_result("类型：私有", "RFC 1918 私有地址", "Private"))
        elif addr.is_loopback:
            results.append(self._make_result("类型：回送", "回送地址", "Loopback"))
        elif addr.is_link_local:
            results.append(self._make_result("类型：链路本地", "链路本地地址", "Link-Local"))
        elif addr.is_multicast:
            results.append(self._make_result("类型：多播", "多播地址", "Multicast"))
        elif addr.is_reserved:
            results.append(self._make_result("类型：保留", "保留地址", "Reserved"))
        else:
            results.append(self._make_result("类型：公网", "可全局路由的地址", "Public"))

        if addr.version == 4:
            first_octet = int(str(addr).split(".")[0])
            if first_octet <= 127:
                ip_class = "A"
            elif first_octet <= 191:
                ip_class = "B"
            elif first_octet <= 223:
                ip_class = "C"
            elif first_octet <= 239:
                ip_class = "D（多播）"
            else:
                ip_class = "E（保留）"
            results.append(self._make_result(f"类别：{ip_class}", "点击复制", ip_class))

            octets = str(addr).split(".")
            binary = ".".join(format(int(o), "08b") for o in octets)
            results.append(self._make_result(f"二进制：{binary}", "点击复制", binary))

            hex_str = ".".join(format(int(o), "02X") for o in octets)
            results.append(self._make_result(f"十六进制：{hex_str}", "点击复制", hex_str))

            int_val = int(addr)
            results.append(self._make_result(f"整数：{int_val}", "点击复制", str(int_val)))
        else:
            expanded = addr.exploded
            results.append(self._make_result(f"展开形式：{expanded}", "点击复制", expanded))
            int_val = int(addr)
            results.append(self._make_result(f"整数：{int_val}", "点击复制", str(int_val)))

        results.append(
            self._make_result(
                f"反向 DNS：{addr.reverse_pointer}",
                "点击复制",
                addr.reverse_pointer,
            )
        )

        return results

    def _dns_results(self, arg: str) -> list[ProviderResult]:
        if not arg:
            return [self._make_result("在“dns”后输入主机名", "例如：ip dns google.com", "")]

        hostname = arg.strip()
        results: list[ProviderResult] = []

        try:
            addr_infos = socket.getaddrinfo(hostname, None)
            seen: set[str] = set()
            ipv4_addrs: list[str] = []
            ipv6_addrs: list[str] = []

            for family, _, _, _, sockaddr in addr_infos:
                ip = sockaddr[0]
                if ip in seen:
                    continue
                seen.add(ip)
                if family == socket.AF_INET:
                    ipv4_addrs.append(ip)
                elif family == socket.AF_INET6:
                    ipv6_addrs.append(ip)

            results.append(
                self._make_result(
                    f"DNS：{hostname}",
                    f"找到 {len(ipv4_addrs)} 个 IPv4 地址和 {len(ipv6_addrs)} 个 IPv6 地址",
                    hostname,
                )
            )

            for ip in ipv4_addrs:
                results.append(self._make_result(f"IPv4：{ip}", "点击复制", ip))

            for ip in ipv6_addrs:
                results.append(self._make_result(f"IPv6：{ip}", "点击复制", ip))

        except socket.gaierror:
            results.append(self._make_result(f"无法解析“{hostname}”", "DNS 查询失败", ""))
        except Exception as e:
            logging.debug("IP Info: DNS lookup error: %s", e)
            results.append(self._make_result("DNS 查询失败", str(e), ""))

        return results

    def _mac_results(self, arg: str) -> list[ProviderResult]:
        adapters = _parse_ipconfig()
        mac_adapters = [a for a in adapters if a.get("mac")]

        if not mac_adapters:
            return [self._make_result("未找到 MAC 地址", "无法读取网络适配器", "")]

        results: list[ProviderResult] = []
        for adapter in mac_adapters:
            name = adapter.get("name", "未知")
            mac = adapter.get("mac", "")
            desc = adapter.get("desc", "")
            detail = desc if desc else name
            results.append(self._make_result(f"{name}: {mac}", detail, mac))

        return results
