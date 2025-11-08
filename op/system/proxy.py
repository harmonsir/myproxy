"""Windows系统代理管理"""
import ctypes
import os
import subprocess
import traceback
from ctypes import wintypes
from sys import getdefaultencoding
from typing import Optional
from winreg import REG_DWORD, REG_SZ

from op.system.registry import HKEY_CU, join_key_path, RegEditor
from op.utils.logger import system_logger as logger
from op.utils.singleton import Singleton


address_patterns = [
    "localhost",
    "127.*",
    "10.*",
    "172.16.*",
    "172.17.*",
    "172.18.*",
    "172.19.*",
    "172.20.*",
    "172.21.*",
    "172.22.*",
    "172.23.*",
    "172.24.*",
    "172.25.*",
    "172.26.*",
    "172.27.*",
    "172.28.*",
    "172.29.*",
    "172.30.*",
    "172.31.*",
    "192.168.*",
    "<local>",
    "pylab.me",
    "*.pylab.me",
    "trip2w.com",
    "*.trip2w.com",
]

DEFAULT_OVERRIDE = ";".join(address_patterns)

REG_IE_KEY = join_key_path(HKEY_CU, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")


class WindowsProxyManager(metaclass=Singleton):
    """Windows系统代理管理器"""

    def __init__(self):
        self._original_settings: Optional[dict] = None

    def enable_proxy(self, proxy_address: str) -> bool:
        """
        启用系统代理
        
        :param proxy_address: 代理地址，格式为 "host:port"
        :return: 是否成功
        """
        if os.name != "nt":
            logger.warning("系统代理功能仅在Windows上可用")
            return False

        try:
            # 启用WinHTTP代理（使用netsh命令）
            is_enable_win_http = False
            # if not self._enable_winhttp_proxy(proxy_address):
            #     logger.error("启用WinHTTP代理失败")
            #     is_enable_win_http = True
            # return False

            # 启用系统级代理（注册表方式）
            is_enable_win_proxy = self._enable_system_proxy_registry(proxy_address)

            logger.info(
                f"代理已启用: {proxy_address} | "
                f"WinHTTP代理: {is_enable_win_http} | "
                f"系统级代理: {is_enable_win_proxy}"
            )
            return any([is_enable_win_http, is_enable_win_proxy])

        except Exception as e:
            logger.error(f"启用系统代理失败: {e}")
            return False

    def disable_proxy(self) -> bool:
        """
        禁用系统代理
        
        :return: 是否成功
        """
        if os.name != "nt":
            logger.warning("系统代理功能仅在Windows上可用")
            return False

        is_disable_win_http = False

        # 禁用WinHTTP代理（使用netsh命令）
        # if not self._disable_winhttp_proxy():
        #     logger.error("禁用WinHTTP代理失败")
        # return False
        # 禁用系统级代理（注册表方式）
        is_disable_win_proxy = self._disable_system_proxy_registry()

        flag = any([is_disable_win_http, is_disable_win_proxy])
        logger.info(
            f"禁用代理结果: {flag} => WinHTTP代理: {is_disable_win_http} | 系统级代理: {is_disable_win_proxy}"
        )
        return flag

    def _enable_winhttp_proxy(self, proxy_address: str) -> bool:
        """
        使用netsh命令启用WinHTTP代理
        
        :param proxy_address: 代理地址
        :return: 是否成功
        """

        # 构建netsh命令：netsh winhttp set proxy 127.0.0.1:8080
        cmd = ["netsh", "winhttp", "set", "proxy", proxy_address]
        logger.debug(" ".join(cmd))
        try:

            # 执行命令，隐藏窗口
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                # 尝试使用 Windows 默认编码或通用编码
                encoding="utf-8" if getdefaultencoding() == "utf-8" else "gbk",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            if result.returncode == 0:
                logger.info(f"WinHTTP代理已设置为: {proxy_address}")
                return True
            else:
                logger.error(f"设置WinHTTP代理失败: {result.stdout}")
                return True  # TODO

        except Exception as e:
            logger.error(f"执行WinHTTP代理设置命令失败: {e}")
            return False

    def _disable_winhttp_proxy(self) -> bool:
        """
        使用netsh命令重置WinHTTP代理
        
        :return: 是否成功
        """

        # 构建netsh命令：netsh winhttp reset proxy
        cmd = ["netsh", "winhttp", "reset", "proxy"]
        try:

            # 执行命令，隐藏窗口
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8" if getdefaultencoding() == "utf-8" else "gbk",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )

            if result.returncode == 0:
                logger.info("WinHTTP代理已重置为默认 (无代理)")
                return True
            else:
                logger.error(f"重置WinHTTP代理失败: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"执行WinHTTP代理重置命令失败: {e}")
            return False

    def _enable_system_proxy_registry(self, proxy_address: str) -> bool:
        """
        使用注册表启用系统级代理
        
        :param proxy_address: 代理地址
        :return: 是否成功
        """
        try:
            # 打开注册表
            result = all([
                RegEditor.set_value(REG_IE_KEY, "ProxyEnable", 1, REG_DWORD),
                RegEditor.set_value(REG_IE_KEY, "ProxyServer", proxy_address, REG_SZ),
                RegEditor.set_value(REG_IE_KEY, "ProxyOverride", DEFAULT_OVERRIDE, REG_SZ),
            ])

            if result:
                # 通知系统设置已更改
                self._notify_system_change()

                logger.info(f"系统级代理已启用: {proxy_address}")
                return True

        except Exception as e:
            logger.error(f"启用系统级代理失败: {e}")
            return False

    def _disable_system_proxy_registry(self) -> bool:
        """
        使用注册表禁用系统级代理
        
        :return: 是否成功
        """
        try:
            # 打开注册表
            result = RegEditor.set_value(REG_IE_KEY, "ProxyEnable", 0, REG_DWORD)
            if result:
                # 通知系统设置已更改
                self._notify_system_change()
                logger.info("系统级代理已禁用")
                return True
        except Exception as e:
            logger.error(f"禁用系统级代理失败: {e}")
        return False

    def get_system_proxy_status(self) -> dict:
        """
        获取当前系统代理状态
        
        :return: 代理状态信息
        """
        if os.name != "nt":
            return {"enabled": False, "platform": "non-windows"}

        try:
            status = {"enabled": False, "server": "", "platform": "windows"}

            try:
                status["enabled"] = bool(RegEditor.get_value(REG_IE_KEY, "ProxyEnable"))
            except Exception:
                traceback.print_exc()

            try:
                status["server"] = RegEditor.get_value(REG_IE_KEY, "ProxyServer")
            except FileNotFoundError:
                traceback.print_exc()

            return status

        except ImportError:
            return {"enabled": False, "platform": "winreg-unavailable"}
        except Exception as e:
            logger.error(f"获取系统代理状态失败: {e}")
            return {"enabled": False, "platform": "windows", "error": str(e)}

    def _notify_system_change(self):
        """通知系统代理设置已更改"""
        try:
            # 定义Windows API函数
            user32 = ctypes.windll.user32
            user32.SendMessageTimeoutW.restype = wintypes.DWORD
            user32.SendMessageTimeoutW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                wintypes.LPARAM, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
            ]

            # 发送设置更改消息
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x1A
            SMTO_NORMAL = 0x0

            result = ctypes.wintypes.DWORD()
            user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                "Internet Settings",
                SMTO_NORMAL,
                5000,
                ctypes.byref(result)
            )

            logger.debug("系统代理设置更改通知已发送")

        except Exception as e:
            logger.debug(f"通知系统设置更改失败: {e}")

    def is_proxy_enabled(self) -> bool:
        """
        检查系统代理是否启用
        
        :return: 是否启用
        """
        status = self.get_system_proxy_status()
        return status.get("enabled", False)


# 全局代理管理器实例
ProxyAPI = WindowsProxyManager()
