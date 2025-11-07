"""
工具函数模块
"""

import ipaddress
import re
import socket
import sys
from functools import lru_cache
from typing import List, Tuple


def validate_python_version() -> bool:
    """验证Python版本是否满足要求"""
    return sys.version_info >= (3, 12)


def get_local_ip() -> str:
    """获取本机IP地址"""
    try:
        # 创建一个UDP socket连接到公网地址，获取本地IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


def parse_ip_range(range_str: str) -> List[ipaddress.IPv4Network]:
    """解析IP范围字符串，返回网络列表"""
    networks = []
    parts = range_str.split(',')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        try:
            # 支持CIDR格式 (如 192.168.1.0/24)
            if '/' in part:
                networks.append(ipaddress.ip_network(part, strict=False))
            # 支持IP范围格式 (如 192.168.1.1-192.168.1.254)
            elif '-' in part:
                start_ip, end_ip = part.split('-')
                start_ip = start_ip.strip()
                end_ip = end_ip.strip()

                start = ipaddress.ip_address(start_ip)
                end = ipaddress.ip_address(end_ip)

                # 将IP范围转换为CIDR网络列表
                for net in ipaddress.summarize_address_range(start, end):
                    networks.append(net)
            # 支持单个IP
            else:
                ip = ipaddress.ip_address(part)
                networks.append(ipaddress.ip_network(f"{ip}/32", strict=False))
        except ValueError as e:
            # 忽略无效的IP格式
            continue

    return networks


def ip_in_networks(ip: str, networks: List[ipaddress.IPv4Network]) -> bool:
    """检查IP是否在指定网络列表中"""
    try:
        ip_obj = ipaddress.ip_address(ip)
        for network in networks:
            if ip_obj in network:
                return True
        return False
    except ValueError:
        return False


def format_bytes(bytes_count: int) -> str:
    """格式化字节数为人类可读格式"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} PB"


def is_port_available(port: int, host: str = '127.0.0.1') -> bool:
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(start_port: int = 1080, max_attempts: int = 100) -> int:
    """查找可用端口"""
    for port in range(start_port, start_port + max_attempts):
        if is_port_available(port):
            return port
    return start_port


@lru_cache(maxsize=128)
def resolve_domain(domain: str) -> List[str]:
    """解析域名为IP地址列表"""
    try:
        return socket.gethostbyname_ex(domain)[2]
    except socket.gaierror:
        return []


def is_valid_domain(domain: str) -> bool:
    """验证域名格式是否有效"""
    pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
    return bool(re.match(pattern, domain))


def is_valid_ip(ip: str) -> bool:
    """验证IP地址格式是否有效"""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def get_network_interfaces() -> List[Tuple[str, str]]:
    """获取网络接口列表"""
    interfaces = []
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        interfaces.append(('本地连接', local_ip))
    except socket.gaierror:
        pass

    # 添加回环地址
    interfaces.append(('回环地址', '127.0.0.1'))

    return interfaces
