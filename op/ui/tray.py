"""
系统托盘模块
"""
import asyncio
import ctypes
import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from op.utils.logger import ui_logger as logger
from op.utils.singleton import Singleton


try:
    import pystray
    from PIL import Image, ImageDraw


    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False


# --- 配置常量 ---
@dataclass(frozen=True)
class Config:
    """应用配置类"""
    ICON_FILENAME: str = "iconoir--internet.png"


class ConsoleManager:
    """控制台窗口管理器"""

    # Windows API 常量
    SW_HIDE = 0
    SW_SHOW = 5
    SW_RESTORE = 9

    # 获取控制台窗口句柄的函数
    _kernel32 = ctypes.windll.kernel32
    _user32 = ctypes.windll.user32

    @staticmethod
    def get_console_window() -> Optional[int]:
        """获取控制台窗口句柄"""
        try:
            # 获取当前进程的控制台窗口
            hwnd = ConsoleManager._kernel32.GetConsoleWindow()
            return hwnd if hwnd else None
        except Exception:
            return None

    @staticmethod
    def show_console() -> bool:
        """显示控制台窗口"""
        try:
            hwnd = ConsoleManager.get_console_window()
            if hwnd:
                ConsoleManager._user32.ShowWindow(hwnd, ConsoleManager.SW_RESTORE)
                ConsoleManager._user32.ShowWindow(hwnd, ConsoleManager.SW_SHOW)
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def hide_console() -> bool:
        """隐藏控制台窗口"""
        try:
            hwnd = ConsoleManager.get_console_window()
            if hwnd:
                ConsoleManager._user32.ShowWindow(hwnd, ConsoleManager.SW_HIDE)
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def is_console_visible() -> bool:
        """检查控制台窗口是否可见"""
        try:
            hwnd = ConsoleManager.get_console_window()
            if hwnd:
                return bool(ConsoleManager._user32.IsWindowVisible(hwnd))
            return False
        except Exception:
            return False


def _get_resource_path(filename: str) -> Path:
    """获取资源文件路径（处理打包后的路径）"""
    try:
        # PyInstaller 创建临时文件夹，将路径存储在 _MEIPASS 中
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # 正常运行时
        base_path = Path(__file__).parent

    if "ui" in str(base_path):
        base_path = base_path.parent / "static"
    return base_path / filename


class TrayManager(metaclass=Singleton):
    """系统托盘管理器"""

    def __init__(self, proxy_app):
        """初始化托盘管理器
        
        Args:
            proxy_app: 代理应用程序实例
        """
        self.proxy_app = proxy_app
        self.icon = None
        self.running = False
        self.status_proxy_enabled = False
        self.status_mode = "stopped"
        self.status_text = "代理服务已停止"
        self._console_visible = True  # 控制台初始状态

        if not TRAY_AVAILABLE:
            logger.warning("pystray 或 PIL 未安装，系统托盘功能将不可用")
            return

    def initialize(self) -> bool:
        """创建系统托盘图标
        
        Returns:
            bool: 创建是否成功
        """
        if not TRAY_AVAILABLE:
            return False

        try:
            image = self._load_icon()

            # 创建菜单
            menu = pystray.Menu(
                pystray.MenuItem("代理状态", self._show_status, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("切换系统代理", self._toggle_system_proxy),
                pystray.MenuItem("打开配置页面", self._open_config_page),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    text="显示/隐藏控制台",
                    action=self._toggle_console,
                    checked=lambda item: self._console_visible
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit)
            )

            self.icon = pystray.Icon(
                "myproxy",
                image,
                "本地代理服务",
                menu
            )

            logger.info("系统托盘创建成功")
            return True

        except Exception as e:
            logger.error(f"创建系统托盘失败: {e}")
            return False

    async def start(self) -> None:
        await asyncio.to_thread(self._run_tray)

    def _run_tray(self):
        """运行托盘图标"""
        try:
            self.running = True
            self.icon.run()
        except Exception as e:
            logger.error(f"运行系统托盘失败: {e}")
        finally:
            self.running = False

    def _toggle_console(self, icon: pystray.Icon, item) -> None:
        """切换控制台显示/隐藏"""
        if self._console_visible:
            if ConsoleManager.hide_console():
                self._console_visible = False
                logger.info("控制台窗口已隐藏")
        else:
            if ConsoleManager.show_console():
                self._console_visible = True
                logger.info("控制台窗口已显示")

    def _load_icon(self) -> Image.Image:
        """加载托盘图标"""
        try:
            icon_path = _get_resource_path(Config.ICON_FILENAME)
            if icon_path.exists():
                image = Image.open(icon_path)
                logger.info(f"成功加载图标: {icon_path}")
                return image
            else:
                logger.warning(f"图标文件未找到: {icon_path}，使用默认图标")
                return self._create_icon()
        except Exception as e:
            logger.error(f"加载图标失败: {e}")
            return self._create_icon()

    def _create_icon(self):
        """创建托盘图标
        
        Returns:
            Image.Image: 图标图像
        """
        try:
            # 创建一个简单的图标
            size = (64, 64)
            image = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)

            # 根据状态选择颜色
            if self.status_proxy_enabled:
                color = (0, 255, 0, 255)  # 绿色 - 代理启用
            elif self.status_mode == "running":
                color = (255, 255, 0, 255)  # 黄色 - 服务运行中
            else:
                color = (128, 128, 128, 255)  # 灰色 - 已停止

            # 绘制一个简单的圆形图标
            margin = 8
            draw.ellipse(
                [margin, margin, size[0] - margin, size[1] - margin],
                fill=color,
                outline=(255, 255, 255, 255),
                width=2
            )

            return image

        except Exception as e:
            logger.error(f"创建图标失败: {e}")
            # 返回一个简单的默认图标
            return Image.new("RGBA", (64, 64), (128, 128, 128, 255))

    def update_status(self, proxy_enabled: bool, mode: str = "running", status_text: str = None) -> None:
        """更新托盘状态
        
        Args:
            proxy_enabled: 代理是否启用
            mode: 运行模式 (running/stopped)
            status_text: 状态文本
        """
        self.status_proxy_enabled = proxy_enabled
        self.status_mode = mode

        if status_text:
            self.status_text = status_text
        else:
            if proxy_enabled:
                self.status_text = "代理服务运行中"
            elif mode == "running":
                self.status_text = "代理服务已启动"
            else:
                self.status_text = "代理服务已停止"

        # 更新图标
        if self.icon:
            try:
                self.icon.icon = self._create_icon()
                self.icon.title = self.status_text
            except Exception as e:
                logger.error(f"更新托盘状态失败: {e}")

        logger.info(f"托盘状态更新: {self.status_text}")

    def _show_status(self, icon, item) -> None:
        """显示状态信息"""
        try:
            status_msg = f"""代理状态信息:
            
服务状态: {self.status_text}
系统代理: {"启用" if self.status_proxy_enabled else "禁用"}
"""

            # 在Windows上显示消息框
            if os.name == "nt":  # Windows
                import ctypes

                ctypes.windll.user32.MessageBoxW(0, status_msg, "代理状态", 0)
            else:
                logger.info(status_msg)

        except Exception as e:
            logger.error(f"显示状态失败: {e}")

    def _toggle_system_proxy(self, icon, item) -> None:
        """切换系统代理"""
        try:
            if hasattr(self.proxy_app, "toggle_system_proxy"):
                self.proxy_app.toggle_system_proxy()
                self.status_proxy_enabled = not self.status_proxy_enabled
                self.update_status(self.status_proxy_enabled, self.status_mode)
        except Exception as e:
            logger.error(f"切换系统代理失败: {e}")

    def _open_config_page(self, icon, item) -> None:
        """打开配置页面"""
        try:
            url = "http://127.0.0.1:8080"
            webbrowser.open(url)
            logger.info(f"已打开配置页面: {url}")
        except Exception as e:
            logger.error(f"打开配置页面失败: {e}")

    def _quit(self, icon, item) -> None:
        """退出应用程序"""
        try:
            logger.info("正在退出应用程序...")

            # 停止代理服务
            if hasattr(self.proxy_app, "stop"):
                self.proxy_app.stop()

            # 停止托盘
            if self.icon:
                self.icon.stop()

            logger.info("应用程序已退出")

        except Exception as e:
            logger.error(f"退出应用程序失败: {e}")
        finally:
            # 直接终止整个进程（最干净、不会卡住）
            os._exit(0)

    def stop(self) -> None:
        """停止托盘服务"""
        if self.icon:
            try:
                self.icon.stop()
            except Exception as e:
                logger.error(f"停止托盘失败: {e}")

        self.running = False
        logger.info("系统托盘已停止")

    def is_running(self) -> bool:
        """检查托盘是否正在运行
        
        Returns:
            bool: 是否正在运行
        """
        return self.running
