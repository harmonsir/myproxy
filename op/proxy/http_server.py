from __future__ import annotations

import asyncio
from asyncio import start_server, StreamReader, StreamWriter
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Dict, Optional

from op.config import Config
# 仍然复用你现有的 handle_client 逻辑
from op.proxy.http_handlers import handle_client  # 比如把 handle_client 等搬到这个模块里
from op.routing.manager import RoutingManager
from op.utils.logger import proxy_logger as logger
from op.utils.singleton import Singleton


# 如果还没拆文件，就把 import 换成: from .http_server import handle_client


class HTTPProxyServer(metaclass=Singleton):
    """
    Asyncio HTTP 代理服务（生产可用版骨架）

    - 单一职责：只负责监听端口、管理生命周期、做基本的连接统计；
      具体转发逻辑仍由 handle_client 完成。
    - 提供 start/serve_forever/stop 接口，方便被 ProxyCore 或独立脚本复用。
    """

    def __init__(
        self,
        config: Config,
        routing_engine: RoutingManager,
        client_handler: Optional[
            Callable[[StreamReader, StreamWriter, RoutingManager], Awaitable[None]]
        ] = None,
    ) -> None:
        self.config = config
        self.routing_engine = routing_engine

        # 允许注入自定义 handler，默认用你的 handle_client
        self._client_handler = client_handler or handle_client

        self._server: Optional[asyncio.base_events.Server] = None
        self._running: bool = False

        # 简单的连接统计信息
        self._total_connections: int = 0
        self._active_connections: int = 0
        self._failed_connections: int = 0

        # 用于保护统计数据
        self._lock = asyncio.Lock()

    async def _handle_new_client(self, reader, writer):
        async with self._connection_scope(writer.get_extra_info("peername")):
            await handle_client(reader, writer, self.routing_engine)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and self._server is not None

    async def start(self) -> None:
        """
        只负责监听端口，不阻塞事件循环。
        如需阻塞式运行，请调用 serve_forever()。
        """
        if self.is_running:
            logger.warning("HTTP proxy server is already running")
            return

        host, port = self.config.src_host, self.config.src_port

        try:
            self._server = await start_server(
                self._handle_new_client,
                host,
                port,
                # 可按需调整 backlog / SSL 等参数
            )

            sockets = self._server.sockets or []
            api_addr = ", ".join(str(sock.getsockname()) for sock in sockets)
            logger.info(f"serving async HTTP proxy on {api_addr}")

            self._running = True

        except OSError as e:
            logger.critical(
                f"Could not start HTTP proxy server on {host}:{port}: {e}. "
                f"Is the port already in use?"
            )
            # 生产实践里通常选择抛异常，让上层决定是否退出
            raise
        except Exception as e:
            logger.critical(f"Unexpected error while starting HTTP proxy server: {e}")
            raise

    async def serve_forever(self) -> None:
        """
        阻塞当前协程，直到服务器被关闭。
        一般用于顶层脚本：await server.serve_forever()
        """
        if not self._server:
            await self.start()

        assert self._server is not None  # for type checkers

        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            self._running = False
            logger.info("HTTP proxy server stopped serving")

    async def stop(self) -> None:
        """
        优雅关闭服务器：停止接受新连接，等待现有连接完成。
        """
        if not self._server:
            return

        logger.info("Stopping HTTP proxy server...")

        self._server.close()
        try:
            await self._server.wait_closed()
        except Exception as e:
            logger.warning(f"Error while waiting for HTTP server to close: {e}")

        self._server = None
        self._running = False

        logger.info("HTTP proxy server fully stopped")

    async def reload_config(self, new_config: Config) -> None:
        """
        重载配置 + 路由引擎。端口变更由上层决定是否重启。
        """
        old_host, old_port = self.config.src_host, self.config.src_port

        self.config = new_config
        if self.routing_engine:
            await self.routing_engine.reload_config(new_config)

        logger.info("HTTP proxy server reloaded config")

        # 如果监听地址变更，提示上层考虑重启
        if (old_host, old_port) != (new_config.src_host, new_config.src_port):
            logger.warning(
                "HTTP proxy bind address changed "
                f"from {old_host}:{old_port} to {new_config.src_host}:{new_config.src_port}. "
                "You may need to restart the server to apply this change."
            )

    # ------------------------------------------------------------------
    # 状态 & 统计接口（方便 ProxyCore 调用）
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """
        返回轻量级状态信息（同步）。
        """
        host, port = self.config.src_host, self.config.src_port
        return {
            "running": self.is_running,
            "listen_address": f"{host}:{port}",
            "connections": {
                "total": self._total_connections,
                "active": self._active_connections,
                "failed": self._failed_connections,
            },
        }

    async def get_stats(self) -> Dict[str, Any]:
        """
        预留统计接口（异步），以后可扩展 bytes_sent/bytes_recv 等。
        先给个兼容 ProxyCore 的结构。
        """
        async with self._lock:
            return {
                "connections": self._total_connections,
                "active": self._active_connections,
                "failed": self._failed_connections,
                # 先占坑，后面如果在 _transfer_data 里统计字节数可以填上
                "bytes_sent": 0,
                "bytes_received": 0,
            }

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _handle_new_client(
        self,
        reader: StreamReader,
        writer: StreamWriter,
    ) -> None:
        """
        start_server 的回调包装：
        - 做基本的连接计数
        - 捕获异常
        - 委托给真正的业务 handler (handle_client)
        """
        addr = writer.get_extra_info("peername")

        async with self._connection_scope(addr):
            try:
                await self._client_handler(reader, writer, self.routing_engine)
            except asyncio.CancelledError:
                # 关 server/任务取消时会走到这里
                logger.debug(f"HTTP client handler cancelled for {addr}")
                raise
            except Exception as e:
                self._increment_failed()
                logger.error(f"Unhandled exception in HTTP client handler {addr}: {e}")
                # 确保连接被关闭
                try:
                    if not writer.is_closing():
                        writer.close()
                        await writer.wait_closed()
                except Exception:
                    pass

    # --- 连接计数工具方法 -------------------------------------------------

    @asynccontextmanager
    async def _connection_scope(self, addr: Any):
        """
        进入/退出一个连接时，安全更新统计信息。
        """
        async with self._lock:
            self._total_connections += 1
            self._active_connections += 1

        logger.debug(f"New HTTP proxy connection from {addr}")

        try:
            yield
        finally:
            async with self._lock:
                self._active_connections -= 1
            logger.debug(f"HTTP proxy connection closed from {addr}")

    def _increment_failed(self) -> None:
        # 失败统计不需要锁的强一致，简单一点即可
        self._failed_connections += 1


async def dev():
    from op.config import ConfigManager
    from op.routing.manager import RoutingManager

    config_manager = ConfigManager()
    await config_manager.initialize()

    config = await config_manager.load_config()
    routing_manager = RoutingManager(config)
    await routing_manager.initialize()

    server = HTTPProxyServer(config, routing_manager)

    # 如果你需要系统级代理
    from op.system.proxy import ProxyAPI

    proxy_addr = f"{config.src_host}:{config.src_port}"
    ProxyAPI.enable_proxy(proxy_addr)

    await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(dev())
