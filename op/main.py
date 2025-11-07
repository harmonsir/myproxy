#!/usr/bin/env python3
"""
ProxyApp - 本地代理工具 (Python版本) - 增强版
从Go语言迁移到Python 3.12+
解决日志输出问题的版本
"""
import signal
import sys
import traceback
from asyncio import create_task, gather, run as async_run
from typing import Callable, Optional

from op.config import RunTimeConfig
from op.config.manager import ConfigManager
from op.proxy.core import ProxyCore
from op.system.proxy import ProxyAPI
from op.ui.tray import TrayManager
from op.ui.web import WebInterface
from op.utils.logger import op_logger as logger
from op.utils.singleton import Singleton


class ProxyApp(metaclass=Singleton):
    def __init__(self):
        self.config_manager: Optional[ConfigManager] = None
        self.proxy_core: Optional[ProxyCore] = None
        self.tray_manager: Optional[TrayManager] = None
        self.web_interface: Optional[WebInterface] = None
        self.win_proxy_api: Optional[ProxyAPI] = None
        self.running: bool = False

        self.async_tasks: list[tuple[Callable, Optional[tuple], Optional[dict]]] = []

    @property
    def proxy_addr(self):
        config = self.config_manager.get_config()
        return f"{config.src_host}:{config.src_port}"

    async def initialize(self):
        """初始化所有组件"""
        try:
            logger.info("开始初始化 ProxyApp ...")

            # 初始化配置管理器
            self.config_manager = RunTimeConfig
            await self.config_manager.initialize()
            logger.info("✓ 配置管理器初始化完成")

            # 加载配置
            config = await self.config_manager.load_config()
            logger.info(f"✓ 配置加载完成 - 监听地址: {config.src_host}:{config.src_port}")

            # 初始化代理核心
            self.proxy_core = ProxyCore(config)
            await self.proxy_core.initialize()
            logger.info("✓ 代理核心初始化完成")

            # 初始化系统代理管理器
            self.win_proxy_api = ProxyAPI
            logger.info("✓ 系统代理管理器初始化完成")

            # 初始化Web界面
            self.web_interface = WebInterface(config)
            # 使用配置中的web_host和web_port
            web_host = getattr(config, "web_host", "127.0.0.1")
            web_port = getattr(config, "web_port", 8081)

            self.async_tasks.append((self.web_interface.start, (), dict(host=web_host, port=web_port)))
            logger.info(f"✓ Web界面初始化完成")

            # 如果配置了启用Windows代理，则设置系统代理
            if config.enable_windows_proxy:
                self._enable_proxy()

            # 初始化系统托盘
            self.tray_manager = TrayManager(self)
            self.tray_manager.initialize()

            logger.info("ProxyApp 应用初始化完成")

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            logger.error(traceback.format_exc())
            raise

    async def start(self):
        """启动应用程序"""
        if self.running:
            logger.warning("应用已在运行")
            return

        try:
            await self.initialize()
            # 启动代理服务器
            await self.proxy_core.before_start()
            self.async_tasks.extend([(f, (), {}) for f in self.proxy_core._tasks])
            # 启动系统托盘
            self.async_tasks.append((self.tray_manager.start, (), {}))

            self.running = True

            logger.debug("async_tasks: %s", [str(f.__name__) for f, *_ in self.async_tasks])
            await gather(*[f(*_args, **_kwargs) for f, _args, _kwargs in self.async_tasks])

        except Exception as e:
            traceback.print_exc()
            logger.error(f"启动失败: {e}")
            await self.stop()
            raise

    async def stop(self):
        """停止应用程序"""
        if not self.running:
            return

        self.running = False

        try:
            logger.info("正在停止 ProxyApp...")

            # 停止代理服务器
            if self.proxy_core:
                await self.proxy_core.stop()
                logger.info("✓ 代理服务器已停止")

            # 停止Web界面
            if self.web_interface:
                await self.web_interface.stop()
                logger.info("✓ Web界面已停止")

            # 禁用系统代理
            self._disable_proxy()

            # 停止系统托盘
            if self.tray_manager:
                try:
                    self.tray_manager.stop()
                    logger.info("✓ 系统托盘已停止")
                except Exception as e:
                    logger.warning(f"停止系统托盘失败: {e}")

            # 停止配置管理器
            if self.config_manager:
                await self.config_manager.cleanup()
                logger.info("✓ 配置管理器已停止")

            logger.info("ProxyApp已完全停止")

        except Exception as e:
            logger.error(f"停止过程中出错: {e}")
            logger.error(traceback.format_exc())

    def toggle_system_proxy(self):
        """切换系统代理状态"""
        try:
            config = self.config_manager.get_config()
            if config.enable_windows_proxy:
                self._enable_proxy()
                logger.info("✓ 系统代理已启用")
            else:
                self._disable_proxy()
                logger.info("✓ 系统代理已禁用")
        except Exception as e:
            logger.error(f"切换系统代理失败: {e}")

    # 添加系统代理相关方法
    def _enable_proxy(self):
        """启用系统代理"""
        try:
            config = self.config_manager.get_config()
            if config.enable_windows_proxy:
                ProxyAPI.enable_proxy(self.proxy_addr)
                logger.info("✓ 系统代理已启用")
            else:
                logger.warning("配置中未启用Windows代理")
        except Exception as e:
            logger.error(f"启用系统代理失败: {e}")

    def _disable_proxy(self):
        """禁用系统代理"""
        try:
            ProxyAPI.disable_proxy()
            logger.info("✓ 系统代理已禁用")
        except Exception as e:
            logger.error(f"禁用系统代理失败: {e}")


async def core_main():
    """主函数"""
    logger.info("🚀 启动 ProxyApp (Python版本)")

    app = ProxyApp()

    # 设置信号处理
    def signal_handler(signum, frame, *args, **kwargs):
        logger.info(f"收到信号 {signum}，正在关闭...")
        create_task(app.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"运行时错误: {e}")
        logger.error(traceback.format_exc())
    finally:
        await app.stop()
        logger.info("ProxyApp已关闭")


if __name__ == "__main__":
    try:
        async_run(core_main())
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"程序异常退出: {e}")
        sys.exit(1)
