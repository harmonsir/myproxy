"""
IP范围管理模块
负责加载、管理和查询IPv4/IPv6地址范围
基于Go版本的geoip.go迁移而来
"""

import bisect
import os
import socket
import struct
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple, Union

import requests

from op.config import RunTimeConfig
from op.utils.logger import routing_logger as logger
from op.utils.singleton import Singleton


LOCAL_CIDRS = [
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "127.0.0.0/8",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]


@dataclass
class IPv4Range:
    """IPv4地址范围"""

    # 移除 __init__，使用 dataclass 默认生成，更简洁
    start: int
    end: int

    def __lt__(self, other):
        """用于 bisect 查找"""
        return self.start < other.start


@dataclass
class IPv6Range:
    """IPv6地址范围"""

    # 移除 __init__，使用 dataclass 默认生成
    start: bytes
    end: bytes

    def __lt__(self, other):
        """用于 bisect 查找，直接使用 bytes 的高效内置比较"""
        return self.start < other.start


def ip_to_uint32(ip: str) -> int:
    """将IPv4地址转换为32位整数"""
    try:
        # 使用 struct.unpack 效率高于多次位运算
        return struct.unpack("!I", socket.inet_aton(ip))[0]
    except socket.error:
        raise ValueError(f"Invalid IPv4 address: {ip}")


@lru_cache(maxsize=128)
def get_ip_data(ip: str) -> Union[int, bytes]:
    return ip_to_uint32(ip) if "." in ip else socket.inet_pton(socket.AF_INET6, ip)


class IPRangeManager(metaclass=Singleton):
    """IP范围管理器"""

    def __init__(self, config):
        self.config = config
        # 使用 List[IPv4Range] 和 List[IPv6Range] 保持类型一致性
        self.ipv4_ranges: List[IPv4Range] = []
        self.ipv6_ranges: List[IPv6Range] = []
        self._sorted = False

    async def initialize(self):
        """初始化IP范围管理器"""
        try:
            await self.load_china_ips(self.config.china_ips)
            # 先加载配置的，再添加本地的，统一排序
            self._append_local_network_ranges()
            self._sort_ranges()
            logger.info("IP范围管理器初始化完成")
        except Exception as e:
            logger.error(f"IP范围管理器初始化失败: {e}")
            raise

    async def cleanup(self):
        """清理资源"""
        try:
            self.ipv4_ranges.clear()
            self.ipv6_ranges.clear()
            self._sorted = False
            logger.info("IP范围管理器已清理")
        except Exception as e:
            logger.error(f"IP范围管理器清理失败: {e}")

    async def load_china_ips(self, china_ips_config: str):
        """加载中国IP配置"""
        if not china_ips_config:
            return

        try:
            # 如果是文件路径
            if os.path.exists(china_ips_config):
                self.load_ranges_from_file(china_ips_config)
            # 如果是URL
            elif china_ips_config.startswith((r"http://", r"https://")):
                self.load_ranges_cached(china_ips_config)
            # 如果是CIDR字符串
            else:
                # 解析逗号分隔的CIDR
                cidrs = [cidr.strip() for cidr in china_ips_config.split(",") if cidr.strip()]
                for cidr in cidrs:
                    if "/" in cidr:
                        ip, prefix = cidr.split("/", 1)
                        self.add_ipnet_to_ranges((ip.strip(), int(prefix)))

                # 排序将在 initialize 结束时统一进行，这里可以省略，但在纯字符串配置下保留也无妨
                self._sort_ranges()
                logger.info(f"加载了 {len(cidrs)} 个中国IP范围")

        except Exception as e:
            logger.warning(f"加载中国IP配置失败: {e}")

    @property
    def ranges(self):
        """获取所有范围（用于兼容性）"""
        return {
            "ipv4": self.ipv4_ranges,
            "ipv6": self.ipv6_ranges
        }

    def add_ipnet_to_ranges(self, ipnet: Tuple[str, int]) -> None:
        """将IP网络添加到范围列表"""
        ip_str, prefix_len = ipnet

        try:
            # 尝试解析为IPv4
            if "." in ip_str:
                ip_int = ip_to_uint32(ip_str)
                # 32位掩码
                mask = (0xFFFFFFFF << (32 - prefix_len)) & 0xFFFFFFFF
                start = ip_int & mask
                # (~mask & 0xFFFFFFFF) 得到主机位全1
                end = start | (~mask & 0xFFFFFFFF)
                self.ipv4_ranges.append(IPv4Range(start, end))
            else:
                # IPv6处理
                ip_bytes = socket.inet_pton(socket.AF_INET6, ip_str)
                mask_bytes = bytearray(16)

                # 计算掩码
                for i in range(prefix_len // 8):
                    mask_bytes[i] = 0xFF
                if prefix_len % 8 != 0:
                    mask_bytes[prefix_len // 8] = (0xFF << (8 - prefix_len % 8)) & 0xFF

                # 计算起始和结束地址
                start_bytes = bytearray(ip_bytes)
                end_bytes = bytearray(ip_bytes)

                for i in range(16):
                    start_bytes[i] = ip_bytes[i] & mask_bytes[i]
                    # ~mask_bytes[i] & 0xFF 得到反掩码，主机位全1
                    end_bytes[i] = ip_bytes[i] | (~mask_bytes[i] & 0xFF)

                self.ipv6_ranges.append(IPv6Range(bytes(start_bytes), bytes(end_bytes)))

        except (socket.error, ValueError) as e:
            logger.warning(f"Skipping invalid CIDR {ip_str}/{prefix_len}: {e}")

    def load_ranges_from_file(self, filename: str) -> None:
        """从文件加载IP范围"""
        logger.info(f"Loading IP ranges from: {filename}")

        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    try:
                        # 解析CIDR格式
                        if "/" in line:
                            ip, prefix = line.split("/", 1)
                            prefix = int(prefix)
                            self.add_ipnet_to_ranges((ip.strip(), prefix))
                        else:
                            logger.warning(f"Invalid line format (expected CIDR): {line}")
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Skipping invalid line {line}: {e}")

        except FileNotFoundError:
            raise FileNotFoundError(f"IP ranges file not found: {filename}")
        except Exception as e:
            raise Exception(f"Error loading IP ranges: {e}")

        # load_ranges_from_file 被 load_ranges_cached 和 initialize 调用
        # 统一在 initialize 结束时排序，减少重复排序
        logger.info(f"Loaded {len(self.ipv4_ranges)} IPv4 ranges and {len(self.ipv6_ranges)} IPv6 ranges")

    def _sort_ranges(self) -> None:
        """排序IP范围"""
        self.ipv4_ranges.sort()
        self.ipv6_ranges.sort()
        self._sorted = True

    def _append_local_network_ranges(self) -> None:
        """添加本地网络范围"""

        for cidr in LOCAL_CIDRS:
            ip, prefix = cidr.split("/", 1)
            self.add_ipnet_to_ranges((ip.strip(), int(prefix)))

        # 不在这里排序，统一在 initialize 结束时排序

    def load_ranges_cached(self, source: str, cache_file: str = "cache_ipranges.txt") -> None:
        """从远程或本地加载IP范围，支持缓存"""
        cache_file = RunTimeConfig.config_dir / cache_file
        local_file = cache_file

        if source.startswith(("http://", "https://")):
            # 远程文件处理
            need_update = True

            # 使用一个合理的超时时间，如7天
            CACHE_EXPIRY = 7 * 24 * 3600

            # 检查缓存文件是否存在且有效
            if os.path.exists(cache_file):
                file_age = time.time() - os.path.getmtime(cache_file)
                if file_age < CACHE_EXPIRY:
                    logger.info(f"Using cache file {cache_file} (valid)")
                    need_update = False
                else:
                    logger.info(f"Cache file {cache_file} is outdated, attempting update")

            if need_update:
                logger.info(f"Fetching remote file: {source}")
                try:
                    # 使用会话以支持连接池，提高效率（如果后续有其他请求）
                    session = requests.Session()
                    response = session.get(source, timeout=30)
                    response.raise_for_status()

                    # 写入缓存文件
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(response.text)

                    logger.info(f"Cache updated: {cache_file}")

                except Exception as e:
                    logger.warning(f"Remote load failed: {e}")
                    if os.path.exists(cache_file):
                        logger.info(f"Falling back to cache file: {cache_file}")
                    else:
                        # 仅在无缓存时才抛出异常
                        raise Exception(f"Remote load failed and no cache available: {e}")
        else:
            # 本地文件
            local_file = source

        self.load_ranges_from_file(local_file)

    def is_ip_in_range(self, ip_data: Union[int, bytes]) -> bool:
        """
        🚀 核心高性能查询方法
        检查预处理的 IP 数据 (int 或 bytes) 是否在范围内
        :param ip_data: IPv4 (int) 或 IPv6 (bytes)
        """
        # 确保范围已排序，这是二分查找的前提
        if not self._sorted:
            logger.warning("Ranges are not sorted. Sorting now.")
            self._sort_ranges()

        if isinstance(ip_data, int):  # IPv4 (int)
            ip_int = ip_data

            # 使用一个 IPv4Range 对象作为查找键 (仅用于比较 start 属性)
            # i 是第一个 start >= ip_int 的索引
            i = bisect.bisect_left(self.ipv4_ranges, IPv4Range(ip_int, ip_int))

            # 标准的区间查找逻辑：IP 只能落在 i-1 范围
            if i > 0:
                range_obj = self.ipv4_ranges[i - 1]
                # 检查 ip_int 是否在 [start, end] 之间
                return range_obj.start <= ip_int <= range_obj.end
            return False

        elif isinstance(ip_data, bytes):  # IPv6 (bytes)
            ip_bytes = ip_data

            # 使用一个 IPv6Range 对象作为查找键 (仅用于比较 start 属性)
            # i 是第一个 start >= ip_bytes 的索引
            i = bisect.bisect_left(self.ipv6_ranges, IPv6Range(ip_bytes, ip_bytes))

            # 标准的区间查找逻辑：IP 只能落在 i-1 范围
            if i > 0:
                range_obj = self.ipv6_ranges[i - 1]
                # 利用 bytes 的高效原生比较
                return range_obj.start <= ip_bytes <= range_obj.end
            return False

        else:
            logger.error(f"Invalid IP data type for lookup: {type(ip_data)}")
            return False

    def is_in_china(self, ip: str) -> bool:
        """
        检查IP (str) 是否在范围内
        此方法保留兼容性，但内部调用高效方法
        """
        try:
            ip_data = get_ip_data(ip)
            return self.is_ip_in_range(ip_data)

        except (socket.error, ValueError) as e:
            logger.warning(f"Invalid IP address {ip}: {e}")
            return False

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "ipv4_ranges": len(self.ipv4_ranges),
            "ipv6_ranges": len(self.ipv6_ranges),
            "sorted": self._sorted
        }
