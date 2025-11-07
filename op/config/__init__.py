"""
配置管理模块
"""

from .manager import ConfigManager
from .schema import Config, ConfigValidator


RunTimeConfig = ConfigManager()

__all__ = ["Config", "ConfigValidator", "ConfigManager", "RunTimeConfig"]
