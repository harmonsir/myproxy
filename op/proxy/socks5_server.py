"""
SOCKS5代理服务器实现
"""

import asyncio
import struct
import time
from typing import Any, Dict, Optional, Tuple

from op.config.schema import Config
from op.routing.manager import RoutingManager
from op.utils.logger import proxy_logger as logger
from op.utils.singleton import Singleton


class SOCKS5ProxyServer(metaclass=Singleton):
    """SOCKS5代理服务器"""

    def __init__(self, config: Config, routing_engine: RoutingManager):
        self.config = config
        self.routing_engine = routing_engine
        self.server: Optional[asyncio.Server] = None
        self.running = False

        # 统计信息
        self.stats = {
            'connections': 0,
            'bytes_sent': 0,
            'bytes_received': 0,
            'start_time': 0
        }

    async def initialize(self):
        """初始化SOCKS5代理服务器"""
        try:
            logger.info("SOCKS5代理服务器初始化完成")

        except Exception as e:
            logger.error(f"SOCKS5代理服务器初始化失败: {e}")
            raise

    async def start(self) -> asyncio.Server:
        """启动SOCKS5代理服务器"""
        if self.running:
            logger.warning("SOCKS5代理服务器已在运行")
            return self.server

        try:
            # 创建服务器
            self.server = await asyncio.start_server(
                self._handle_client,
                self.config.src_host,
                self.config.src_port
            )

            self.running = True
            self.stats['start_time'] = time.time()

            logger.info(f"SOCKS5代理服务器启动成功: {self.config.src_host}:{self.config.src_port}")
            return self.server

        except Exception as e:
            logger.error(f"启动SOCKS5代理服务器失败: {e}")
            raise

    async def stop(self):
        """停止SOCKS5代理服务器"""
        if not self.running:
            return

        try:
            self.running = False

            if self.server:
                self.server.close()
                await self.server.wait_closed()

            logger.info("SOCKS5代理服务器已停止")

        except Exception as e:
            logger.error(f"停止SOCKS5代理服务器失败: {e}")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """处理客户端连接"""
        client_addr = writer.get_extra_info('peername')
        logger.debug(f"新的SOCKS5连接: {client_addr}")

        self.stats['connections'] += 1

        try:
            # SOCKS5握手
            if not await self._socks5_handshake(reader, writer):
                return

            # 处理SOCKS5请求
            await self._socks5_request(reader, writer, client_addr)

        except Exception as e:
            logger.error(f"处理SOCKS5客户端失败: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            logger.debug(f"SOCKS5连接关闭: {client_addr}")

    async def _socks5_handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """SOCKS5握手"""
        try:
            # 读取客户端认证方法
            data = await reader.read(2)
            if len(data) != 2:
                return False

            version, nmethods = struct.unpack('!BB', data)
            if version != 0x05:  # SOCKS5版本
                return False

            # 读取认证方法列表
            methods = await reader.read(nmethods)
            if len(methods) != nmethods:
                return False

            # 选择无认证方法 (0x00)
            writer.write(struct.pack('!BB', 0x05, 0x00))
            await writer.drain()

            return True

        except Exception as e:
            logger.debug(f"SOCKS5握手失败: {e}")
            return False

    async def _socks5_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_addr: Tuple):
        """处理SOCKS5请求"""
        try:
            # 读取请求头
            header = await reader.read(4)
            if len(header) != 4:
                await self._send_error_response(writer, 0x01)  # 一般性错误
                return

            version, cmd, rsv, atyp = struct.unpack('!BBBB', header)
            if version != 0x05:
                await self._send_error_response(writer, 0x01)
                return

            if cmd != 0x01:  # 只支持CONNECT命令
                await self._send_error_response(writer, 0x07)  # 命令不支持
                return

            # 解析目标地址
            if atyp == 0x01:  # IPv4
                addr_data = await reader.read(6)  # 4字节IP + 2字节端口
                if len(addr_data) != 6:
                    await self._send_error_response(writer, 0x01)
                    return
                host = '.'.join(map(str, addr_data[:4]))
                port = struct.unpack('!H', addr_data[4:])[0]

            elif atyp == 0x03:  # 域名
                addr_len = (await reader.read(1))[0]
                addr_data = await reader.read(addr_len + 2)  # 域名 + 2字节端口
                if len(addr_data) != addr_len + 2:
                    await self._send_error_response(writer, 0x01)
                    return
                host = addr_data[:addr_len].decode('utf-8')
                port = struct.unpack('!H', addr_data[addr_len:])[0]

            elif atyp == 0x04:  # IPv6
                addr_data = await reader.read(18)  # 16字节IP + 2字节端口
                if len(addr_data) != 18:
                    await self._send_error_response(writer, 0x01)
                    return
                # IPv6地址处理（简化）
                host = '::1'  # 暂时简化
                port = struct.unpack('!H', addr_data[16:])[0]
            else:
                await self._send_error_response(writer, 0x08)  # 地址类型不支持
                return

            # 路由决策
            route_type, route_params = await self.routing_engine.decide_routing(
                host, port, client_addr[0]
            )

            # 建立连接
            if route_type == "direct":
                target_reader, target_writer = await self._connect_direct(host, port)
            else:
                target_reader, target_writer = await self._connect_proxy(route_params)

            if not target_reader or not target_writer:
                await self._send_error_response(writer, 0x04)  # 主机不可达
                return

            # 发送成功响应
            await self._send_success_response(writer)

            # 开始数据转发
            await self._relay_data(reader, writer, target_reader, target_writer)

        except Exception as e:
            logger.error(f"处理SOCKS5请求失败: {e}")
            await self._send_error_response(writer, 0x01)

    async def _connect_direct(self, host: str, port: int) -> Tuple[
        Optional[asyncio.StreamReader], Optional[asyncio.StreamWriter]]:
        """直连目标"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=10
            )
            return reader, writer
        except Exception as e:
            logger.debug(f"直连失败 {host}:{port}: {e}")
            return None, None

    async def _connect_proxy(self, route_params: Dict) -> Tuple[
        Optional[asyncio.StreamReader], Optional[asyncio.StreamWriter]]:
        """通过上游代理连接"""
        try:
            proxy_host = route_params['host']
            proxy_port = route_params['port']
            target_host = route_params['target_host']
            target_port = route_params['target_port']

            # 连接到上游代理
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(proxy_host, proxy_port),
                timeout=10
            )

            # 发送SOCKS5握手
            writer.write(struct.pack('!BB', 0x05, 0x01))  # 版本5，1种方法
            writer.write(struct.pack('!B', 0x00))  # 无认证
            await writer.drain()

            # 读取握手响应
            response = await reader.read(2)
            if len(response) != 2 or response[1] != 0x00:
                writer.close()
                await writer.wait_closed()
                return None, None

            # 发送CONNECT请求
            target_bytes = target_host.encode('utf-8')
            request = struct.pack('!BBBB', 0x05, 0x01, 0x00, 0x03)  # 版本5，CONNECT，域名类型
            request += struct.pack('!B', len(target_bytes))  # 域名长度
            request += target_bytes  # 域名
            request += struct.pack('!H', target_port)  # 端口

            writer.write(request)
            await writer.drain()

            # 读取CONNECT响应
            response = await reader.read(10)  # 最多10字节
            if len(response) < 4 or response[1] != 0x00:
                writer.close()
                await writer.wait_closed()
                return None, None

            return reader, writer

        except Exception as e:
            logger.debug(f"代理连接失败: {e}")
            return None, None

    async def _send_success_response(self, writer: asyncio.StreamWriter):
        """发送成功响应"""
        # 绑定地址为0.0.0.0:0
        response = struct.pack('!BBBB', 0x05, 0x00, 0x00, 0x01)  # 版本5，成功，保留，IPv4
        response += struct.pack('!H', 0)  # IP 0.0.0.0
        response += struct.pack('!H', 0)  # 端口0
        writer.write(response)
        await writer.drain()

    async def _send_error_response(self, writer: asyncio.StreamWriter, error_code: int):
        """发送错误响应"""
        response = struct.pack('!BBBB', 0x05, error_code, 0x00, 0x01)  # 版本5，错误码，保留，IPv4
        response += struct.pack('!H', 0)  # IP 0.0.0.0
        response += struct.pack('!H', 0)  # 端口0
        writer.write(response)
        await writer.drain()

    async def _relay_data(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        target_reader: asyncio.StreamReader,
        target_writer: asyncio.StreamWriter):
        """双向数据转发"""

        async def forward_client_to_target():
            try:
                while True:
                    data = await client_reader.read(8192)
                    if not data:
                        break
                    target_writer.write(data)
                    await target_writer.drain()
                    self.stats['bytes_sent'] += len(data)
            except Exception as e:
                logger.debug(f"客户端到目标转发失败: {e}")
            finally:
                target_writer.close()
                await target_writer.wait_closed()

        async def forward_target_to_client():
            try:
                while True:
                    data = await target_reader.read(8192)
                    if not data:
                        break
                    client_writer.write(data)
                    await client_writer.drain()
                    self.stats['bytes_received'] += len(data)
            except Exception as e:
                logger.debug(f"目标到客户端转发失败: {e}")
            finally:
                client_writer.close()
                await client_writer.wait_closed()

        # 并发执行双向转发
        await asyncio.gather(
            forward_client_to_target(),
            forward_target_to_client(),
            return_exceptions=True
        )

    def get_status(self) -> Dict[str, Any]:
        """获取服务器状态"""
        uptime = time.time() - self.stats['start_time'] if self.stats['start_time'] > 0 else 0
        return {
            'running': self.running,
            'listen_address': f"{self.config.src_host}:{self.config.src_port}",
            'uptime': uptime,
            'connections': self.stats['connections']
        }

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'connections': self.stats['connections'],
            'bytes_sent': self.stats['bytes_sent'],
            'bytes_received': self.stats['bytes_received'],
            'uptime': time.time() - self.stats['start_time'] if self.stats['start_time'] > 0 else 0
        }
