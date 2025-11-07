"""
配置管理器 - 修复版
"""

import asyncio
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

# 修复导入路径
from op.utils.async_fs import async_open
from op.utils.logger import config_logger as logger
from op.utils.singleton import Singleton
from .schema import Config


class ConfigManager(metaclass=Singleton):
    """配置管理器"""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置目录路径，默认为用户目录下的.myproxy
        """
        self.config_dir = config_dir or Path.home() / ".myproxy"
        self.config_path = self.config_dir / "config.yaml"
        self.backup_dir = self.config_dir / "backups"

        # 当前配置
        self._config: Optional[Config] = None
        self._config_lock = asyncio.Lock()

        # 配置变更监听器
        self._change_listeners: List[Callable[[Config], None]] = []

        # 配置文件监控
        self._file_watcher_task: Optional[asyncio.Task] = None
        self._last_modified: Optional[float] = None

    async def initialize(self) -> None:
        """初始化配置管理器"""
        try:
            logger.info("开始初始化配置管理器...")

            # 创建配置目录
            self.config_dir.mkdir(exist_ok=True)
            self.backup_dir.mkdir(exist_ok=True)
            logger.info(f"配置目录创建成功: {self.config_dir}")

            # 加载配置
            await self.load_config()

            # 启动文件监控, TODO：移除
            # self._file_watcher_task = asyncio.create_task(self._watch_config_file())

            logger.info("配置管理器初始化完成")

        except Exception as e:
            logger.error(f"配置管理器初始化失败: {e}")
            raise

    async def load_config(self) -> Config:
        """
        加载配置文件
        
        Returns:
            Config: 配置对象
        """
        async with self._config_lock:
            try:
                logger.info(f"加载配置文件: {self.config_path}")

                if self.config_path.exists():
                    async with async_open(self.config_path) as f:
                        content = await f.read()

                    data = yaml.safe_load(content)
                    if data:
                        self._config = Config.from_dict(data)
                        logger.info("从文件加载配置成功")
                    else:
                        self._config = Config()
                        logger.info("配置文件为空，使用默认配置")
                else:
                    # 创建默认配置
                    logger.info("配置文件不存在，创建默认配置")
                    self._config = Config()
                    await self.save_config(self._config)

                # 记录文件修改时间
                if self.config_path.exists():
                    self._last_modified = self.config_path.stat().st_mtime

                logger.info("配置加载完成")
                return self._config

            except Exception as e:
                traceback.print_exc()
                logger.error(f"加载配置失败: {e}")
                # 加载失败时使用默认配置
                self._config = Config()
                return self._config

    async def save_config(self, config: Config, create_backup: bool = True) -> bool:
        """
        保存配置文件
        
        Args:
            config: 配置对象
            create_backup: 是否创建备份
            
        Returns:
            bool: 保存是否成功
        """
        async with self._config_lock:
            try:
                logger.info("开始保存配置...")

                # 验证配置
                errors = config.validate()
                if errors:
                    logger.error(f"配置验证失败: {errors}")
                    return False

                # 创建备份
                if create_backup and self.config_path.exists():
                    backup_path = self.backup_dir / f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
                    await self._backup_config(self.config_path, backup_path)

                # 保存配置
                data = config.to_dict()
                yaml_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)

                async with async_open(self.config_path, "w", encoding="utf-8") as f:
                    await f.write(yaml_content)

                # 更新当前配置
                self._config = config
                self._last_modified = self.config_path.stat().st_mtime

                # 通知监听器
                await self._notify_change_listeners(config)

                logger.info("配置保存完成")
                return True

            except Exception as e:
                logger.error(f"保存配置失败: {e}")
                return False

    async def _backup_config(self, source: Path, backup: Path) -> None:
        """备份配置文件"""
        try:
            async with async_open(source, "r", encoding="utf-8") as src:
                content = await src.read()

            async with async_open(backup, "w", encoding="utf-8") as dst:
                await dst.write(content)

            logger.info(f"配置已备份到: {backup}")

        except Exception as e:
            logger.warning(f"备份配置失败: {e}")

    async def _watch_config_file(self) -> None:
        """监控配置文件变更"""
        while True:
            try:
                await asyncio.sleep(1)  # 每秒检查一次

                if self.config_path.exists():
                    current_mtime = self.config_path.stat().st_mtime
                    if self._last_modified and current_mtime > self._last_modified:
                        logger.info("检测到配置文件变更，重新加载")
                        await self.load_config()

            except Exception as e:
                logger.error(f"配置文件监控出错: {e}")
                await asyncio.sleep(5)  # 出错后等待5秒再继续

    def get_config(self) -> Config:
        """获取当前配置"""
        return self._config or Config()

    async def update_config(self, updates: Dict[str, Any]) -> bool:
        """
        更新配置
        
        Args:
            updates: 配置更新字典
            
        Returns:
            bool: 更新是否成功
        """
        try:
            current = self.get_config()
            current_dict = current.to_dict()

            # 应用更新
            for key, value in updates.items():
                if key == "default_target" and isinstance(value, dict):
                    current_dict["default_target"].update(value)
                else:
                    current_dict[key] = value

            new_config = Config.from_dict(current_dict)
            return await self.save_config(new_config)

        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return False

    async def reset_to_default(self) -> bool:
        """重置为默认配置"""
        try:
            default_config = Config()
            return await self.save_config(default_config)

        except Exception as e:
            logger.error(f"重置配置失败: {e}")
            return False

    def add_change_listener(self, listener: Callable[[Config], None]) -> None:
        """添加配置变更监听器"""
        self._change_listeners.append(listener)

    def remove_change_listener(self, listener: Callable[[Config], None]) -> None:
        """移除配置变更监听器"""
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)

    async def _notify_change_listeners(self, config: Config) -> None:
        """通知所有监听器配置已变更"""
        for listener in self._change_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(config)
                else:
                    listener(config)
            except Exception as e:
                logger.error(f"配置变更监听器出错: {e}")

    async def export_config(self, export_path: Path, format: str = "yaml") -> bool:
        """
        导出配置
        
        Args:
            export_path: 导出路径
            format: 导出格式 ("yaml" 或 "json")
            
        Returns:
            bool: 导出是否成功
        """
        try:
            config = self.get_config()
            data = config.to_dict()

            if format.lower() == "json":
                content = json.dumps(data, indent=2, ensure_ascii=False)
            else:
                content = yaml.dump(data, default_flow_style=False, allow_unicode=True)

            async with async_open(export_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(f"配置已导出到: {export_path}")
            return True

        except Exception as e:
            logger.error(f"导出配置失败: {e}")
            return False

    async def import_config(self, import_path: Path, format: str = "yaml") -> bool:
        """
        导入配置
        
        Args:
            import_path: 导入路径
            format: 导入格式 ("yaml" 或 "json")
            
        Returns:
            bool: 导入是否成功
        """
        try:
            async with async_open(import_path, "r", encoding="utf-8") as f:
                content = await f.read()

            if format.lower() == "json":
                data = json.loads(content)
            else:
                data = yaml.safe_load(content)

            if data:
                config = Config.from_dict(data)
                return await self.save_config(config)

            return False

        except Exception as e:
            logger.error(f"导入配置失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if self._file_watcher_task:
            self._file_watcher_task.cancel()
            try:
                await self._file_watcher_task
            except asyncio.CancelledError:
                pass

        logger.info("配置管理器已清理")
