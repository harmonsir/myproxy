"""
async_fs.py

基于线程池封装的异步文件读写工具：
- async_open(...) 返回 AsyncFile，支持 async with / async for
- aread_text / awrite_text：整文件文本读写
- aread_bytes / awrite_bytes：整文件二进制读写

依赖：标准库 asyncio + pathlib + contextlib + typing
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator


class AsyncFile:
    """
    对同步文件对象的简单异步封装。

    特性：
    - read / readline / write / flush / close 都通过 asyncio.to_thread 调用
    - 支持 async for 按行迭代（文本文件场景）
    """

    def __init__(self, fp: Any, loop: "asyncio.AbstractEventLoop"):
        self._fp = fp
        self._loop = loop
        self._binary = "b" in getattr(fp, "mode", "")

    async def read(self, size: int = -1) -> Any:
        """
        读取全部或指定大小内容。
        文本模式返回 str，二进制模式返回 bytes。
        """
        return await asyncio.to_thread(self._fp.read, size)

    async def readline(self) -> Any:
        """
        读取一行内容。
        文本模式返回 str，二进制模式返回 bytes。
        """
        return await asyncio.to_thread(self._fp.readline)

    async def readlines(self) -> list[Any]:
        """
        读取所有行。
        文本模式返回 list[str]，二进制模式返回 list[bytes]。
        """
        return await asyncio.to_thread(self._fp.readlines)

    async def write(self, data: Any) -> int:
        """
        写入数据。
        文本模式通常是 str，二进制模式是 bytes。
        返回写入的字节数/字符数。
        """
        return await asyncio.to_thread(self._fp.write, data)

    async def writelines(self, lines: list[Any]) -> None:
        """
        写入多行数据。
        """
        await asyncio.to_thread(self._fp.writelines, lines)

    async def flush(self) -> None:
        """
        刷新缓冲区。
        """
        await asyncio.to_thread(self._fp.flush)

    async def seek(self, offset: int, whence: int = 0) -> int:
        """
        移动文件指针。
        """
        return await asyncio.to_thread(self._fp.seek, offset, whence)

    async def tell(self) -> int:
        """
        返回当前文件指针位置。
        """
        return await asyncio.to_thread(self._fp.tell)

    async def close(self) -> None:
        """
        关闭文件。
        """
        await asyncio.to_thread(self._fp.close)

    # 让 AsyncFile 本身也可以作为 async context manager 使用（可选）
    async def __aenter__(self) -> "AsyncFile":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # 支持 async for line in f:
    def __aiter__(self) -> "AsyncFile":
        return self

    async def __anext__(self) -> Any:
        line = await self.readline()
        if not line:
            raise StopAsyncIteration
        return line


@asynccontextmanager
async def async_open(
    path: str | Path,
    mode: str = "r",
    encoding="utf-8",
    **kwargs: Any,
) -> "AsyncIterator[AsyncFile]":
    """
    异步版本的 open，返回 AsyncFile。

    用法示例：

    async with async_open("demo.txt", "r", encoding="utf-8") as f:
        async for line in f:
            ...

    本质：在 asyncio.to_thread 中打开文件并执行所有 IO 操作。
    """
    loop = asyncio.get_running_loop()
    file_path = Path(path)

    fp = await asyncio.to_thread(open, file_path, mode=mode, encoding=encoding, **kwargs)
    af = AsyncFile(fp, loop)

    try:
        yield af
    finally:
        await af.close()


# =========================
#  整文件读写工具函数
# =========================


async def aread_text(path: str | Path, encoding: str = "utf-8") -> str:
    """
    读取完整文本文件内容。
    """
    file_path = Path(path)
    return await asyncio.to_thread(file_path.read_text, encoding=encoding)


async def awrite_text(path: str | Path, data: str, encoding: str = "utf-8") -> int:
    """
    写入完整文本文件内容。
    返回写入的字符数。
    """
    file_path = Path(path)
    return await asyncio.to_thread(file_path.write_text, data, encoding=encoding)


async def aread_bytes(path: str | Path) -> bytes:
    """
    读取完整二进制文件。
    """
    file_path = Path(path)
    return await asyncio.to_thread(file_path.read_bytes)


async def awrite_bytes(path: str | Path, data: bytes) -> int:
    """
    写入完整二进制文件。
    返回写入的字节数。
    """
    file_path = Path(path)
    return await asyncio.to_thread(file_path.write_bytes, data)
