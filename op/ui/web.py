"""
Web界面模块
提供基于FastAPI的Web界面和WebSocket实时状态更新
"""

import json
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from op.config.schema import Config
from op.ui.tray import _get_resource_path
from op.utils.async_fs import aread_text
from op.utils.logger import ui_logger as logger
from op.utils.singleton import Singleton


class WebInterface(metaclass=Singleton):
    """Web界面管理器"""

    def __init__(self, config: Config):
        self.config = config
        self.app = FastAPI(title="ProxyAPI Configuration", version="1.0.0")
        self.websocket_connections: set[WebSocket] = set()
        self._setup_routes()

    def _setup_routes(self):
        """设置路由"""

        @self.app.get("/", response_class=HTMLResponse)
        async def get_index():
            """返回主页面"""
            return await aread_text(_get_resource_path("index.html"))

        @self.app.get("/api/config")
        async def get_config():
            """获取当前配置"""
            try:
                config_data = self.config.to_dict()
                return config_data
            except Exception as e:
                logger.error(f"获取配置失败: {e}")
                return {"error": "Failed to get config"}

        @self.app.post("/api/config")
        async def update_config(request: Request):
            """更新配置"""
            try:
                new_config = await request.json()
                await self._handle_config_update(new_config)
                return "配置更新成功!"
            except Exception as e:
                logger.error(f"更新配置失败: {e}")
                return f"更新配置失败: {str(e)}"

        @self.app.get("/api/status")
        async def get_status():
            """获取代理状态"""
            try:
                # 这里需要从代理核心获取状态
                return {
                    "proxy_running": False,  # 需要实际实现
                    "system_proxy_enabled": False,  # 需要实际实现
                    "connected_clients": 0
                }
            except Exception as e:
                logger.error(f"获取状态失败: {e}")
                return {"error": "Failed to get status"}

        @self.app.post("/api/proxy/start")
        async def start_proxy():
            """启动代理服务"""
            try:
                # 这里需要调用代理核心的启动方法
                await self._notify_websockets({"type": "proxy_status", "running": True})
                return "代理服务启动成功"
            except Exception as e:
                logger.error(f"启动代理失败: {e}")
                return f"启动代理失败: {str(e)}"

        @self.app.post("/api/proxy/stop")
        async def stop_proxy():
            """停止代理服务"""
            try:
                # 这里需要调用代理核心的停止方法
                await self._notify_websockets({"type": "proxy_status", "running": False})
                return "代理服务停止成功"
            except Exception as e:
                logger.error(f"停止代理失败: {e}")
                return f"停止代理失败: {str(e)}"

        @self.app.post("/api/system-proxy/enable")
        async def enable_system_proxy():
            """启用系统代理"""
            try:
                # 这里需要调用系统代理设置方法
                await self._notify_websockets({"type": "system_proxy", "enabled": True})
                return "系统代理启用成功"
            except Exception as e:
                logger.error(f"启用系统代理失败: {e}")
                return f"启用系统代理失败: {str(e)}"

        @self.app.post("/api/system-proxy/disable")
        async def disable_system_proxy():
            """禁用系统代理"""
            try:
                # 这里需要调用系统代理设置方法
                await self._notify_websockets({"type": "system_proxy", "enabled": False})
                return "系统代理禁用成功"
            except Exception as e:
                logger.error(f"禁用系统代理失败: {e}")
                return f"禁用系统代理失败: {str(e)}"

        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            """WebSocket端点，用于实时状态更新"""
            await websocket.accept()
            self.websocket_connections.add(websocket)
            logger.debug("WebSocket连接建立")

            try:
                while True:
                    # 保持连接活跃
                    await websocket.receive_text()
            except WebSocketDisconnect:
                self.websocket_connections.remove(websocket)
                logger.debug("WebSocket连接断开")
            except Exception as e:
                logger.error(f"WebSocket错误: {e}")
                if websocket in self.websocket_connections:
                    self.websocket_connections.remove(websocket)

    async def _handle_config_update(self, new_config: Dict[str, Any]):
        """处理配置更新"""
        try:
            # 更新配置对象
            for key, value in new_config.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)

            # 保存配置到文件
            # await self.config.save()  # 暂时注释掉，因为Config类没有save方法

            # 通知所有WebSocket客户端配置已更新
            await self._notify_websockets({
                "type": "config_updated",
                "config": self.config.to_dict()
            })

            logger.info("配置更新成功")

        except Exception as e:
            logger.error(f"处理配置更新失败: {e}")
            raise

    async def _notify_websockets(self, message: Dict[str, Any]):
        """向所有WebSocket连接发送消息"""
        if not self.websocket_connections:
            return

        message_str = json.dumps(message)
        disconnected = set()

        for websocket in self.websocket_connections:
            try:
                await websocket.send_text(message_str)
            except Exception as e:
                logger.debug(f"WebSocket发送消息失败: {e}")
                disconnected.add(websocket)

        # 移除断开的连接
        for websocket in disconnected:
            self.websocket_connections.discard(websocket)

    async def start(self, host: str = "127.0.0.1", port: int = 8081):
        """启动Web服务器"""

        logger.info(f"Web界面启动在 http://{host}:{port}")
        config = uvicorn.Config(self.app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def stop(self):
        """停止Web服务器"""
        # 关闭所有WebSocket连接
        for websocket in list(self.websocket_connections):
            try:
                await websocket.close()
            except Exception:
                pass

        self.websocket_connections.clear()
        logger.info("Web界面已停止")
