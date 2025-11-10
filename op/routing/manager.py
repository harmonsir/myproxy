"""
路由管理器
整合IP范围管理、路由决策功能，使用系统DNS
"""

import ipaddress
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from op.utils.helpers import resolve_domain
from op.utils.logger import routing_logger as logger
from op.utils.singleton import Singleton
from .ip_ranges import IPRangeManager


class RoutingDecision(metaclass=Singleton):
    """路由决策引擎"""

    def __init__(self, config, ip_manager: Optional[IPRangeManager] = None):
        self.config = config
        self.bypass_rules: List[Dict] = []
        self.proxy_rules: List[Dict] = []
        self.ipmap_rules: Dict[str, str] = {}

        self.ip_manager = ip_manager
        self._load_rules()

    def _load_rules(self) -> None:
        """加载路由规则"""
        # 加载IP映射规则
        ipmap = getattr(self.config, "ipmap", [])
        if ipmap:
            for rule in ipmap:
                if "=" in rule:
                    src, dst = rule.split("=", 1)
                    self.ipmap_rules[src.strip()] = dst.strip()

    def should_bypass(self, hostname: str, ip: str = None) -> bool:
        """判断是否应该绕过代理
            规则：
                .cn结尾，bypass
                china ips，bypass
        """

        # 检查IP映射规则
        if hostname.endswith(".cn"):
            return True

        if hostname in self.ipmap_rules:
            mapped_ip = self.ipmap_rules[hostname]
            if mapped_ip == "direct":
                return True
            elif mapped_ip == "proxy":
                return False

        ips = ip or resolve_domain(hostname)
        # 检查IP是否在中国范围内
        if ips and self.ip_manager:
            logger.debug(f"get ip is :{ip}")
            return any(self.ip_manager.is_in_china(ip) for ip in ips)

        return False

    def get_mapped_ip(self, hostname: str) -> Optional[str]:
        """获取映射的IP地址"""
        return self.ipmap_rules.get(hostname)


class RoutingManager(metaclass=Singleton):
    """路由管理器 - 统一入口"""

    def __init__(self, config):
        self.config = config
        self.ip_manager: IPRangeManager = IPRangeManager(config)
        self.decision: RoutingDecision = RoutingDecision(config, ip_manager=self.ip_manager)
        self._initialized = False

    async def initialize(self) -> None:
        """初始化路由管理器"""
        if self._initialized:
            return

        await self.ip_manager.initialize()
        self._initialized = True
        logger.info("Routing manager initialized")

    @lru_cache(maxsize=256)
    def should_bypass_proxy(self, hostname: str, ip: str = None) -> bool:
        """判断是否应该绕过代理"""
        if not self._initialized:
            logger.warning("Routing manager not initialized")
            return False

        return self.decision.should_bypass(hostname, ip)

    def should_rewrite_headers(self, hostname: str, client_ip: str) -> Tuple[bool, str]:
        """判断是否需要重写请求头"""
        header_rewrite = getattr(self.config, "header_rewrite", 0)
        fake_ip = getattr(self.config, "fake_ip", "31.13.77.33")

        if header_rewrite == 0:
            return False, fake_ip
        elif header_rewrite == 1:
            return True, fake_ip
        elif header_rewrite == 2:
            # 局域网不修改
            try:
                ip_obj = ipaddress.ip_address(client_ip)
                return not ip_obj.is_private, fake_ip
            except ValueError:
                return True, fake_ip
        else:
            return False, fake_ip

    async def decide_routing(self, hostname: str, port: int, client_ip: str = None) -> Tuple[str, Dict]:
        """
        路由决策函数，兼容HTTPProxyServer的接口

        Returns:
            Tuple[str, Dict]: (route_type, route_params)
            - route_type: "direct" 或 "proxy"
            - route_params: 路由参数字典
        """
        # logger.debug(f"+++ decide_routing -> client_ip:{client_ip} | hostname:{hostname} | port:{port}")

        if self.should_bypass_proxy(hostname):
            return "direct", {}
        else:
            return "proxy", {
                "target_host": hostname,
                "target_port": port,
                **self.proxy_config,
            }

    @property
    @lru_cache(maxsize=2)
    def proxy_config(self):
        remote_mode = getattr(self.config, "remote_mode", "socks5")
        dst_host = getattr(self.config, "dst_host", "127.0.0.1")
        dst_port = getattr(self.config, "dst_port", 1080)
        return {
            "host": dst_host,
            "port": dst_port,
            "proxy_type": remote_mode

        }

    async def reload_config(self, new_config) -> None:
        """重新加载配置"""
        self.config = new_config
        self.ip_manager = IPRangeManager(new_config)
        self.decision = RoutingDecision(new_config)
        self.decision.ip_manager = self.ip_manager
        await self.initialize()
        logger.info("Routing manager reloaded with new config")
