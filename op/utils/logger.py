"""
日志模块
"""

import logging
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "myproxy",
    level: str = "INFO",
    log_file: Optional[str] = None,
    console: bool = True,
) -> logging.Logger:
    """设置日志记录器"""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # 清除现有处理器
    # logger.handlers.clear()

    # 设置日志格式
    formatter = logging.Formatter(
        "%(levelname)s - %(asctime)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台处理器
    if console:
        # console_handler = logging.StreamHandler(sys.stdout)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# 预设的日志记录器
op_logger = setup_logger(name="core_main", level="DEBUG", log_file="proxy.log")
proxy_logger = setup_logger("proxy")
config_logger = setup_logger("config")
routing_logger = setup_logger("routing")
system_logger = setup_logger("system")
ui_logger = setup_logger("ui")

# 减少第三方库的日志输出
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.INFO)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
