"""
Windows注册表操作模块 - 简化且健壮的版本

使用 winreg.OpenKeyEx 和 winreg.CreateKeyEx 遵循最佳实践。
"""

import logging
import winreg
from typing import Any, Literal, Tuple

from op.utils.logger import system_logger as logger
from op.utils.singleton import Singleton


# --- 注册表视图常量 ---
REG_VIEW_64BIT = winreg.KEY_WOW64_64KEY
REG_VIEW_32BIT = winreg.KEY_WOW64_32KEY

# --- 注册表权限常量 ---
REG_READ = winreg.KEY_READ
REG_WRITE = winreg.KEY_WRITE  # 包含 KEY_SET_VALUE 和 KEY_CREATE_SUB_KEY

# --- 注册表根键映射 (使用字符串名称作为键) ---
HKEYS = {
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    # HKEY_USERS 和 HKEY_CURRENT_CONFIG 略
}

HKEY_CU = "HKEY_CURRENT_USER"


def join_key_path(*args: str) -> str:
    """组合注册表路径"""
    return "\\".join(map(str, args))


def parse_key_path(key_path: str) -> Tuple[int, str]:
    """
    解析注册表路径，将字符串路径拆分为 HKEY 句柄和子键路径。
    """
    if not isinstance(key_path, str) or "\\" not in key_path:
        raise ValueError(f"Invalid registry key path format: {key_path}. Must contain '\\'.")

    hkey_name_raw, subkey = key_path.split("\\", 1)
    hkey_name = hkey_name_raw.upper().strip()

    hkey = HKEYS.get(hkey_name)
    if hkey is None:
        raise ValueError(f"Invalid registry root key: {hkey_name_raw}")

    return hkey, subkey


class RegistryManager(metaclass=Singleton):
    """Windows注册表管理器"""

    def _get_access_mask(self, base_access: int, view: Literal[32, 64]) -> int:
        """组合访问权限和注册表视图掩码"""
        if view == 32:
            return base_access | REG_VIEW_32BIT
        # 默认或 64
        return base_access | REG_VIEW_64BIT

    def set_value(
        self, key_path: str, value_name: str, value: Any, value_type: int, view: Literal[32, 64] = 64) -> bool:
        """
        设置注册表值。

        :param key_path: 注册表路径，例如 "HKCU\\Software\\MyApp"
        :param value_name: 值名称
        :param value: 要设置的值
        :param value_type: 注册表值类型 (如 winreg.REG_SZ, winreg.REG_DWORD)
        :param view: 注册表视图 (32 或 64)
        :return: 是否成功
        """
        try:
            hkey, subkey = parse_key_path(key_path)
            access_mask = self._get_access_mask(REG_WRITE, view)

            # 使用 CreateKeyEx 确保路径存在，并以写入权限打开
            # CreateKeyEx 隐含了 KEY_WRITE 权限
            with winreg.CreateKeyEx(hkey, subkey, 0, access_mask) as key:
                winreg.SetValueEx(key, value_name, 0, value_type, value)

            logger.info(f"成功设置注册表值: {key_path}\\{value_name}")
            return True
        except ValueError as e:
            logger.error(f"路径解析错误: {e}")
            return False
        except Exception as e:
            logger.error(f"设置注册表值失败: {key_path}\\{value_name} - {e}", exc_info=False)
            return False

    def get_value(self, key_path: str, value_name: str, default: Any = None, view: Literal[32, 64] = 64) -> Any:
        """
        获取注册表值。

        :param key_path: 注册表路径
        :param value_name: 值名称
        :param default: 获取失败或值不存在时的默认值
        :param view: 注册表视图 (32 或 64)
        :return: 注册表值或默认值
        """
        try:
            hkey, subkey = parse_key_path(key_path)
            access_mask = self._get_access_mask(REG_READ, view)

            with winreg.OpenKeyEx(hkey, subkey, 0, access_mask) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                return value
        except FileNotFoundError:
            # 键或值不存在，这是 winreg 抛出的常见错误
            logger.debug(f"注册表键或值不存在: {key_path}\\{value_name}")
            return default
        except ValueError as e:
            logger.error(f"路径解析错误: {e}")
            return default
        except Exception as e:
            logger.error(f"获取注册表值失败: {key_path}\\{value_name} - {e}", exc_info=False)
            return default

    def delete_value(self, key_path: str, value_name: str, view: Literal[32, 64] = 64) -> bool:
        """
        删除注册表值。

        :param key_path: 注册表路径
        :param value_name: 要删除的值名称
        :param view: 注册表视图 (32 或 64)
        :return: 是否成功 (包括值不存在的情况)
        """
        try:
            hkey, subkey = parse_key_path(key_path)
            access_mask = self._get_access_mask(REG_WRITE, view)

            # 需要写入权限来删除值
            with winreg.OpenKeyEx(hkey, subkey, 0, access_mask) as key:
                winreg.DeleteValue(key, value_name)

            logger.info(f"成功删除注册表值: {key_path}\\{value_name}")
            return True
        except FileNotFoundError:
            # 如果值不存在，视为删除成功 (幂等性)
            logger.warning(f"尝试删除不存在的注册表值: {key_path}\\{value_name}")
            return True
        except ValueError as e:
            logger.error(f"路径解析错误: {e}")
            return False
        except Exception as e:
            # 其他错误，如权限不足
            logger.error(f"删除注册表值失败: {key_path}\\{value_name} - {e}", exc_info=False)
            return False


RegEditor = RegistryManager()

# --- 示例用法 (需要运行环境支持 logger 模块) ---
if __name__ == "__main__":
    # 简单的日志配置
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_path = join_key_path("HKCU", r"Software\MyTestAppForRegManager")
    test_name = "TestValue"

    # 1. 设置值 (如果 MyTestAppForRegManager 不存在，会被创建)
    success = RegEditor.set_value(
        key_path=test_path,
        value_name=test_name,
        value="Hello Registry!",
        value_type=winreg.REG_SZ
    )
    if success:
        # 2. 获取值
        value = RegEditor.get_value(test_path, test_name, default="DEFAULT_MISSING")
        logger.info(f"获取到的值: {value}")

        # 3. 删除值
        RegEditor.delete_value(test_path, test_name)
