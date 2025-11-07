"""
代理核心逻辑 - 修复版本
"""
import traceback
from typing import Any, Dict, Optional

from op.config.schema import Config
from op.routing.manager import RoutingManager
from op.utils.logger import proxy_logger as logger
from op.utils.singleton import Singleton
from .http_server import HTTPProxyServer
from .socks5_server import SOCKS5ProxyServer


class ProxyCore(metaclass=Singleton):
    """代理核心管理器"""

    def __init__(self, config: Config):
        self.config = config
        self.http_server: Optional[HTTPProxyServer] = None
        self.socks5_server: Optional[SOCKS5ProxyServer] = None
        self.routing_engine: Optional[RoutingManager] = None
        self.running = False
        self._servers: Dict[str, Any] = {}  # 改为Any类型以兼容不同的服务器类型
        self._tasks: list = []

    async def initialize(self):
        """初始化代理核心"""
        try:
            # 初始化路由引擎
            self.routing_engine = RoutingManager(self.config)
            await self.routing_engine.initialize()
            logger.info("路由引擎初始化完成")

            # 根据配置初始化代理服务器
            if self.config.local_mode == "http":
                self.http_server = HTTPProxyServer(self.config, self.routing_engine)
                # await self.http_server.initialize()
                logger.info("HTTP代理服务器初始化完成")

            elif self.config.local_mode == "socks5":
                self.socks5_server = SOCKS5ProxyServer(self.config, self.routing_engine)
                await self.socks5_server.initialize()
                logger.info("SOCKS5代理服务器初始化完成")

            logger.info("代理核心初始化完成")

        except Exception as e:
            traceback.print_exc()
            logger.error(f"代理核心初始化失败: {e}")
            raise

    async def before_start(self):
        """启动代理服务"""
        if self.running:
            logger.warning("代理服务已在运行")
            return

        try:
            if self.http_server:
                # server = await self.http_server.start()
                # self._servers["http"] = server
                self._tasks.append(self.http_server.serve_forever)
                logger.info(f"HTTP代理服务器启动于 {self.config.src_host}:{self.config.src_port}")

            if self.socks5_server:
                # server = await self.socks5_server.start()
                # self._servers["socks5"] = server
                self._tasks.append(self.socks5_server.start)
                logger.info(f"SOCKS5代理服务器启动于 {self.config.src_host}:{self.config.src_port}")

            # await gather(*self._tasks)
            self.running = True
            logger.info("代理服务启动完成")

        except Exception as e:
            traceback.print_exc()
            logger.error(f"启动代理服务失败: {e}")
            await self.stop()
            raise

    async def stop(self):
        """停止代理服务"""
        if not self.running:
            return

        self.running = False

        try:
            # 停止所有服务器
            for name, server in self._servers.items():
                try:
                    if hasattr(server, "close"):
                        server.close()
                        if hasattr(server, "wait_closed"):
                            await server.wait_closed()
                    elif hasattr(server, "stop"):
                        await server.stop()
                    logger.info(f"{name}代理服务器已停止")
                except Exception as e:
                    logger.warning(f"停止{name}服务器时出错: {e}")

            self._servers.clear()

            logger.info("代理服务已停止")

        except Exception as e:
            logger.error(f"停止代理服务时出错: {e}")

    async def update_config(self, new_config: Config):
        """更新配置"""
        try:
            old_config = self.config
            self.config = new_config

            # 检查是否需要重启服务
            need_restart = (
                old_config.src_host != new_config.src_host or
                old_config.src_port != new_config.src_port or
                old_config.local_mode != new_config.local_mode
            )

            if need_restart and self.running:
                logger.info("配置变更需要重启代理服务")
                await self.stop()
                await self.initialize()
                await self.before_start()
            else:
                # 只更新路由引擎配置
                if self.routing_engine:
                    await self.routing_engine.reload_config(new_config)

            logger.info("代理配置更新完成")

        except Exception as e:
            logger.error(f"更新代理配置失败: {e}")
            raise

    def get_status(self) -> Dict[str, Any]:
        """获取代理状态"""
        status = {
            "running": self.running,
            "mode": self.config.local_mode,
            "listen_address": f"{self.config.src_host}:{self.config.src_port}",
            "servers": {}
        }

        if self.http_server:
            status["servers"]["http"] = self.http_server.get_status()

        if self.socks5_server:
            status["servers"]["socks5"] = self.socks5_server.get_status()

        if self.routing_engine:
            status["routing"] = {
                "initialized": self.routing_engine._initialized
            }

        return status

    async def get_stats(self) -> Dict[str, Any]:
        """获取代理统计信息"""
        stats = {
            "uptime": 0,  # 需要实现运行时间统计
            "connections": {
                "total": 0,
                "active": 0,
                "failed": 0
            },
            "traffic": {
                "bytes_sent": 0,
                "bytes_received": 0
            }
        }

        # 从各个服务器收集统计信息
        if self.http_server:
            http_stats = await self.http_server.get_stats()
            stats["connections"]["total"] += http_stats.get("connections", 0)
            stats["traffic"]["bytes_sent"] += http_stats.get("bytes_sent", 0)
            stats["traffic"]["bytes_received"] += http_stats.get("bytes_received", 0)

        if self.socks5_server:
            socks5_stats = await self.socks5_server.get_stats()
            stats["connections"]["total"] += socks5_stats.get("connections", 0)
            stats["traffic"]["bytes_sent"] += socks5_stats.get("bytes_sent", 0)
            stats["traffic"]["bytes_received"] += socks5_stats.get("bytes_received", 0)

        return stats
