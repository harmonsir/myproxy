"""
配置数据模型和验证
"""

from dataclasses import asdict, dataclass, field
from ipaddress import ip_address, ip_network
from typing import Any, Dict, List


@dataclass
class Config:
    """主配置类"""
    # 基础配置
    enable_windows_proxy: bool = False
    local_mode: str = "http"  # http, socks5
    src_host: str = "127.0.0.1"
    src_port: int = 1080

    remote_mode: str = "socks5"  # socks5, http
    dst_host: str = "127.0.0.1"
    dst_port: int = 1080

    # 路由配置
    china_ips: str = ""  # 中国IP范围列表
    ipmap: List[str] = field(default_factory=list)  # IP映射规则

    # 高级配置
    header_rewrite: int = 0  # 请求头改写级别
    fake_ip: str = "31.13.77.33"  # 伪装IP

    # Web界面配置
    web_port: int = 8080
    web_host: str = "127.0.0.1"

    # 日志配置
    log_level: str = "INFO"
    log_file: str = "myproxy.log"

    def __post_init__(self):
        """验证配置"""
        # 验证监听地址
        try:
            ip_address(self.src_host)
        except ValueError:
            if self.src_host != "0.0.0.0":
                raise ValueError(f"无效的监听地址: {self.src_host}")

        # 验证端口
        if not (1 <= self.src_port <= 65535):
            raise ValueError(f"无效的监听端口: {self.src_port}")

        # 验证模式
        if self.local_mode not in ["http", "socks5"]:
            raise ValueError(f"无效的本地模式: {self.local_mode}")

        if self.remote_mode not in ["socks5", "http"]:
            raise ValueError(f"无效的远程模式: {self.remote_mode}")

        # 验证伪装IP
        try:
            ip_address(self.fake_ip)
        except ValueError:
            raise ValueError(f"无效的伪装IP: {self.fake_ip}")

        # 验证日志级别
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError(f"无效的日志级别: {self.log_level}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """从字典创建配置"""
        return cls(**data)

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []

        try:
            self.__post_init__()
        except ValueError as e:
            errors.append(str(e))

        # 验证IP映射格式
        for ipmap_rule in self.ipmap:
            if "=" not in ipmap_rule:
                errors.append(f"无效的IP映射格式: {ipmap_rule}")
                continue

            src, dst = ipmap_rule.split("=", 1)
            try:
                ip_address(src.strip())
                ip_address(dst.strip())
            except ValueError:
                errors.append(f"无效的IP映射地址: {ipmap_rule}")

        return errors

    def merge(self, other: "Config") -> "Config":
        """合并配置，other的值会覆盖当前配置"""
        current_dict = self.to_dict()
        other_dict = other.to_dict()

        # 简单合并
        for key, value in other_dict.items():
            current_dict[key] = value

        return Config.from_dict(current_dict)


class ConfigValidator:
    """配置验证器"""

    @staticmethod
    def validate_port(port: int) -> bool:
        """验证端口"""
        return 1 <= port <= 65535

    @staticmethod
    def validate_ip(ip: str) -> bool:
        """验证IP地址"""
        try:
            ip_address(ip)
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_ip_range(ip_range: str) -> bool:
        """验证IP范围"""
        try:
            if "/" in ip_range:
                ip_network(ip_range, strict=False)
            else:
                ip_address(ip_range)
            return True
        except ValueError:
            return False

    @staticmethod
    def validate_ipmap_rule(rule: str) -> bool:
        """验证IP映射规则"""
        if "=" not in rule:
            return False

        src, dst = rule.split("=", 1)
        return (ConfigValidator.validate_ip(src.strip()) and
                ConfigValidator.validate_ip(dst.strip()))
