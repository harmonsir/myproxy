from __future__ import annotations

import asyncio
import struct
from asyncio import StreamReader, StreamWriter
from typing import Dict, List, Optional, Tuple

from op.routing.manager import RoutingManager
from op.utils.logger import proxy_logger as logger


# --- 常量配置（可以按需调参） ---------------------------------------------


SOCKS5_VERSION = 5
SOCKS5_CMD_CONNECT = 1
SOCKS5_ATYP_IPV4 = 1
SOCKS5_ATYP_DOMAIN = 3
SOCKS5_ATYP_IPV6 = 4

SOCKS5_METHOD_NO_AUTH = 0
SOCKS5_METHOD_NO_ACCEPTABLE = 0xFF

SOCKS5_CONNECT_TIMEOUT = 10  # 秒

MAX_REQUEST_LINE = 8 * 1024  # 8KB
MAX_HEADER_SIZE = 64 * 1024  # 64KB
READ_HEADER_TIMEOUT = 15  # 秒
READ_BODY_TIMEOUT = 60  # 秒
CONNECT_IDLE_TIMEOUT = 600  # 秒（CONNECT 隧道空闲超时）

IP_HEADERS = [
    "CF-Connecting-IP", "True-Client-IP", "X-Client-IP", "X-Forwarded",
    "X-Cluster-Client-IP", "X-Original-Forwarded-For", "Via",
    "CLIENT_IP", "REMOTE_HOST", "REMOTE_ADDR", "X_FORWARDED_FOR",
    "X-Forwarded-For", "X-Real-IP",
]

HOP_BY_HOP = [
    "Connection", "Keep-Alive", "Proxy-Authenticate",
    "Proxy-Authorization", "TE", "Trailer",
    "Transfer-Encoding", "Upgrade",
]


# --- 基础工具函数 ---------------------------------------------------------


def _parse_request_line(line: bytes) -> Tuple[str, str, str]:
    """
    解析请求行: "GET http://example.com/path HTTP/1.1"
    返回: (method, uri, version)
    """
    try:
        parts = line.decode("latin-1").strip().split()
        if len(parts) != 3:
            return "", "", ""
        method, uri, version = parts
        return method.upper(), uri, version.upper()
    except Exception:
        return "", "", ""


def _extract_host_port(method: str, uri: str, headers: Dict[str, str]) -> Optional[str]:
    """
    从请求行和 Host 头中提取 target host:port
    - 对于代理请求: uri 可能是完整 URL（http://host:port/path）
    - 对于有些客户端: uri 可能是相对路径，这时用 Host 头
    """
    host_port = ""

    if method == "CONNECT":
        # CONNECT 一般直接是 "host:port"
        host_port = uri
    else:
        if uri.startswith("http://") or uri.startswith("https://"):
            # 形如 http://host:port/path
            # scheme://host[:port]/...
            without_scheme = uri.split("://", 1)[1]
            host_port = without_scheme.split("/", 1)[0]
        else:
            # 相对路径，走 Host 头
            host_port = headers.get("Host", "")

    if not host_port:
        return None

    # 如果没有端口，根据 scheme 兜底
    if ":" not in host_port:
        if uri.startswith("https://") or method == "CONNECT":
            host_port = f"{host_port}:443"
        else:
            host_port = f"{host_port}:80"

    return host_port


def _parse_headers(header_lines: List[bytes]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    for line in header_lines:
        line_str = line.decode("latin-1").rstrip("\r\n")
        if not line_str:
            continue
        if ":" not in line_str:
            logger.warning(f"Could not parse header line: {line_str}")
            continue
        key, value = line_str.split(":", 1)
        # 标准化首字母大写
        key = "-".join(w.capitalize() for w in key.strip().split("-"))
        headers[key] = value.strip()
    return headers


def _modify_headers(headers: Dict[str, str], fake_ip: str) -> None:
    """
    重写 DNT 和 IP 相关头，并移除 hop-by-hop 头。
    """
    headers["Dnt"] = "1"
    for k in IP_HEADERS:
        headers[k] = fake_ip

    # 移除 hop-by-hop
    for h in HOP_BY_HOP:
        if h in headers:
            headers.pop(h, None)


async def _dial_target(host: str, port: int) -> Tuple[StreamReader, StreamWriter]:
    logger.info(f"  [dial_direct]  Connecting to target {host}:{port}")
    return await asyncio.open_connection(host, port)


async def _dial_proxy(proxy_params: Dict, target_host: str, target_port: int) -> Tuple[StreamReader, StreamWriter]:
    """
    通过 SOCKS5 代理建立到 target_host:target_port 的 TCP 连接。

    目前只实现无鉴权 SOCKS5（大多数情况够用）：
      - 不支持用户名密码 / GSSAPI；
      - 只处理 CONNECT 命令。
    """
    proxy_host = proxy_params["host"]
    proxy_port = proxy_params["port"]
    proxy_type = proxy_params["proxy_type"]

    if proxy_type != "socks5":
        # 其他类型暂时直接直连，和原来保持行为一致
        logger.info(f"  [dial_proxy] Fallback direct for proxy_type={proxy_type} {target_host}:{target_port}")
        return await asyncio.open_connection(target_host, target_port)

    logger.info(
        f"  [dial_proxy] SOCKS5 {proxy_host}:{proxy_port} -> {target_host}:{target_port}"
    )

    # 1. 先连上 SOCKS5 服务器
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy_host, proxy_port),
            timeout=SOCKS5_CONNECT_TIMEOUT,
        )
    except Exception as e:
        logger.error(f"  [dial_proxy] Connect to SOCKS5 {proxy_host}:{proxy_port} failed: {e}")
        raise

    try:
        # 2. 发送协商报文：version=5, nmethods=1, methods=[NO_AUTH]
        writer.write(bytes([SOCKS5_VERSION, 1, SOCKS5_METHOD_NO_AUTH]))
        await writer.drain()

        # 3. 读取协商回应
        #   VER | METHOD
        data = await asyncio.wait_for(reader.readexactly(2), timeout=SOCKS5_CONNECT_TIMEOUT)
        ver, method = data[0], data[1]

        if ver != SOCKS5_VERSION or method == SOCKS5_METHOD_NO_ACCEPTABLE:
            raise OSError(f"SOCKS5: no acceptable auth method, ver={ver}, method={method}")

        # 4. 发送 CONNECT 请求
        #   VER | CMD | RSV | ATYP | DST.ADDR | DST.PORT
        addr_bytes: bytes
        atyp: int

        # 简单判断是 IPv4/IPv6 还是域名，这里直接按“有不止数字和点就按域名”来
        try:
            # 如果 parse 成功且包含点数量正常，可以当作 IP；
            # 简化处理：只要里面有非数字/点就当域名
            if any(c for c in target_host if not (c.isdigit() or c == ".")):
                raise ValueError("not pure IPv4")
            # 纯数字+点，当 IPv4
            atyp = SOCKS5_ATYP_IPV4
            addr_bytes = bytes(map(int, target_host.split(".")))
        except Exception:
            # 按域名处理
            atyp = SOCKS5_ATYP_DOMAIN
            host_bytes = target_host.encode("idna")
            if len(host_bytes) > 255:
                raise ValueError("hostname too long for SOCKS5")
            addr_bytes = bytes([len(host_bytes)]) + host_bytes

        port_bytes = struct.pack("!H", int(target_port))

        req = bytes([SOCKS5_VERSION, SOCKS5_CMD_CONNECT, 0x00, atyp]) + addr_bytes + port_bytes
        writer.write(req)
        await writer.drain()

        # 5. 读取 CONNECT 响应
        #   VER | REP | RSV | ATYP | BND.ADDR | BND.PORT
        resp_head = await asyncio.wait_for(reader.readexactly(4), timeout=SOCKS5_CONNECT_TIMEOUT)
        ver, rep, rsv, atyp = resp_head

        if ver != SOCKS5_VERSION or rep != 0x00:
            raise OSError(f"SOCKS5 CONNECT failed, rep={rep}")

        # 根据 ATYP 读取 BND.ADDR
        if atyp == SOCKS5_ATYP_IPV4:
            await reader.readexactly(4)
        elif atyp == SOCKS5_ATYP_IPV6:
            await reader.readexactly(16)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            ln = (await reader.readexactly(1))[0]
            await reader.readexactly(ln)
        else:
            raise OSError(f"SOCKS5 unknown ATYP={atyp}")

        # 读取 BND.PORT
        await reader.readexactly(2)

        # 到这里为止，SOCKS5 隧道已经建立，可以把 (reader, writer) 当作直连 target 使用
        logger.info(f"  [dial_proxy] SOCKS5 tunnel established to {target_host}:{target_port}")
        return reader, writer

    except Exception:
        # 失败时确保关闭 socket
        try:
            writer.close()
        except Exception:
            pass
        raise


async def _read_headers_with_timeout(reader: StreamReader) -> Tuple[bytes, List[bytes]]:
    """
    带超时和大小限制地读取请求行和头部。
    返回: (request_line, header_lines)
    """
    # 读请求行
    request_line = await asyncio.wait_for(reader.readline(), timeout=READ_HEADER_TIMEOUT)
    if len(request_line) > MAX_REQUEST_LINE:
        raise ValueError("Request line too long")

    # 读头部
    header_lines: List[bytes] = []
    total_size = 0
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=READ_HEADER_TIMEOUT)
        if not line or line == b"\r\n":
            break
        header_lines.append(line)
        total_size += len(line)
        if total_size > MAX_HEADER_SIZE:
            raise ValueError("Header section too large")

    return request_line, header_lines


async def _relay_stream(
    reader: StreamReader,
    writer: StreamWriter,
    idle_timeout: Optional[int] = None,
) -> None:
    """
    单方向数据转发: 把 reader 的数据写到 writer.
    可选 idle_timeout: 在这段时间内没有任何数据就结束。
    """
    try:
        while True:
            if idle_timeout:
                data = await asyncio.wait_for(reader.read(65536), timeout=idle_timeout)
            else:
                data = await reader.read(65536)

            if not data:
                break

            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        # 超时或对端关闭，结束即可
        pass
    except Exception as e:
        logger.debug(f"Stream relay error: {e}")
    finally:
        try:
            if not writer.is_closing():
                writer.close()
        except Exception:
            pass


# --- 核心处理逻辑 ---------------------------------------------------------


async def _handle_connect(
    client_reader: StreamReader,
    client_writer: StreamWriter,
    host_port: str,
    routing_engine: RoutingManager,
    client_ip: str,
) -> None:
    """
    HTTPS CONNECT: 纯 TCP 隧道
    """
    target_writer: Optional[StreamWriter] = None
    target_reader: Optional[StreamReader] = None

    try:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)

        route_type, route_params = await routing_engine.decide_routing(host, port, client_ip)

        if route_type == "direct":
            target_reader, target_writer = await _dial_target(host, port)
        else:
            target_reader, target_writer = await _dial_proxy(route_params, host, port)

        # 通知客户端隧道建立
        client_writer.write(
            b"HTTP/1.1 200 Connection Established\r\n"
            b"Proxy-Agent: Asyncio-Proxy\r\n"
            b"\r\n"
        )
        await client_writer.drain()

        # 开始双向转发
        task1 = asyncio.create_task(_relay_stream(client_reader, target_writer, idle_timeout=CONNECT_IDLE_TIMEOUT))
        task2 = asyncio.create_task(_relay_stream(target_reader, client_writer, idle_timeout=CONNECT_IDLE_TIMEOUT))

        await asyncio.wait({task1, task2}, return_when=asyncio.FIRST_COMPLETED)

    except Exception as e:
        logger.error(f"CONNECT error for {host_port}: {e}")
        try:
            if client_writer and not client_writer.is_closing():
                client_writer.write(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Proxy-Agent: Asyncio-Proxy\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                await client_writer.drain()
        except Exception:
            pass
    finally:
        for w in (target_writer, client_writer):
            try:
                if w and not w.is_closing():
                    w.close()
            except Exception:
                pass


async def _handle_http(
    client_reader: StreamReader,
    client_writer: StreamWriter,
    method: str,
    uri: str,
    version: str,
    headers: Dict[str, str],
    host_port: str,
    routing_engine: RoutingManager,
    client_ip: str,
) -> None:
    """
    普通 HTTP 请求：一次请求 -> 一次响应
    不搞 pipelining / keep-alive，简单稳定。
    """
    target_writer: Optional[StreamWriter] = None
    target_reader: Optional[StreamReader] = None

    try:
        host, port_str = host_port.rsplit(":", 1)
        port = int(port_str)

        route_type, route_params = await routing_engine.decide_routing(host, port, client_ip)
        print(f"111: {host}:{port}")

        if route_type == "direct":
            target_reader, target_writer = await _dial_target(host, port)
        else:
            target_reader, target_writer = await _dial_proxy(route_params, host, port)

        # 头部重写
        should_rewrite, fake_ip = routing_engine.should_rewrite_headers(host, client_ip)
        if should_rewrite:
            _modify_headers(headers, fake_ip)

        # 强制关闭连接，简单起见
        headers["Connection"] = "close"

        # 重建 path: 去掉 scheme + host，只保留 path/query
        if uri.startswith("http://") or uri.startswith("https://"):
            # scheme://host[:port]/path...
            without_scheme = uri.split("://", 1)[1]
            parts = without_scheme.split("/", 1)
            if len(parts) == 1:
                path = "/"
            else:
                path = "/" + parts[1]
        else:
            path = uri if uri else "/"

        request_line = f"{method} {path} {version}\r\n"
        target_writer.write(request_line.encode("latin-1"))

        for k, v in headers.items():
            target_writer.write(f"{k}: {v}\r\n".encode("latin-1"))
        target_writer.write(b"\r\n")
        await target_writer.drain()

        # 转发请求 body（只处理 Content-Length，生产环境够用 80% 场景）
        content_length = int(headers.get("Content-Length", "0") or "0")
        remaining = content_length
        while remaining > 0:
            chunk = await asyncio.wait_for(
                client_reader.read(min(65536, remaining)),
                timeout=READ_BODY_TIMEOUT,
            )
            if not chunk:
                break
            remaining -= len(chunk)
            target_writer.write(chunk)
            await target_writer.drain()

        try:
            await target_writer.drain()
            # 尝试 half-close，告诉目标我这边请求发完了
            target_writer.write_eof()
        except (AttributeError, OSError):
            # 某些平台/协议不支持 write_eof
            pass

        # 把响应完整转回客户端
        while True:
            data = await target_reader.read(65536)
            if not data:
                break
            client_writer.write(data)
            await client_writer.drain()

    except Exception as e:
        logger.error(f"HTTP forwarding error for {host_port}: {e}")
        try:
            if client_writer and not client_writer.is_closing():
                client_writer.write(
                    b"HTTP/1.1 502 Bad Gateway\r\n"
                    b"Proxy-Agent: Asyncio-Proxy\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                await client_writer.drain()
        except Exception:
            pass
    finally:
        for w in (target_writer, client_writer):
            try:
                if w and not w.is_closing():
                    w.close()
            except Exception:
                pass


# --- 对外入口：给 HTTPProxyServer 用 -------------------------------------


async def handle_client(
    reader: StreamReader,
    writer: StreamWriter,
    routing_engine: RoutingManager,
) -> None:
    """
    HTTPProxyServer 的统一入口：
    - 读取请求行 + 头
    - 分流到 CONNECT / 普通 HTTP
    - 做基础的错误处理和日志
    """
    addr = writer.get_extra_info("peername")
    client_ip = addr[0] if isinstance(addr, tuple) and addr else "unknown"

    try:
        # 读请求行 & 头部
        request_line, header_lines = await _read_headers_with_timeout(reader)
        if not request_line:
            return

        method, uri, version = _parse_request_line(request_line)
        if not method:
            logger.warning(f"Invalid request line from {addr}: {request_line!r}")
            return

        headers = _parse_headers(header_lines)
        host_port = _extract_host_port(method, uri, headers)
        if not host_port:
            logger.warning(f"Could not determine target host:port for {addr}, uri={uri!r}")
            return

        logger.info(f"Request from {':'.join(map(str, addr))} >> {host_port}")

        # IP 映射（域名 -> 指定 IP）
        hostname = host_port.split(":", 1)[0]
        mapped_ip = routing_engine.decision.get_mapped_ip(hostname)
        if mapped_ip and mapped_ip not in ("direct", "proxy"):
            # 替换为具体 IP
            port = int(host_port.split(":", 1)[1])
            host_port = f"{mapped_ip}:{port}"
            logger.info(f"Mapped {hostname} to {mapped_ip}")

        # 分流 CONNECT / 普通 HTTP
        if method == "CONNECT":
            await _handle_connect(reader, writer, host_port, routing_engine, client_ip)
        else:
            await _handle_http(reader, writer, method, uri, version, headers, host_port, routing_engine, client_ip)

    except asyncio.TimeoutError:
        logger.warning(f"Timeout while reading request from {addr}")
    except Exception as e:
        logger.error(f"Error handling client {addr}: {e}")
    finally:
        try:
            if not writer.is_closing():
                writer.close()
        except Exception:
            pass
