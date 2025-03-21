package main

import (
	"bufio"
	"fmt"
	"io"
	"log"
	"net"
)

// handleSocks5Connection 实现一个最简版 SOCKS5 代理，仅支持 CONNECT 命令和无认证模式
func handleSocks5Connection(conn net.Conn) {
	defer conn.Close()
	buf := bufio.NewReader(conn)
	// 读取握手：版本和方法数量
	header := make([]byte, 2)
	if _, err := io.ReadFull(buf, header); err != nil {
		log.Println("Failed to read SOCKS5 handshake:", err)
		return
	}
	if header[0] != 0x05 {
		log.Println("Unsupported SOCKS version:", header[0])
		return
	}
	nmethods := int(header[1])
	methods := make([]byte, nmethods)
	if _, err := io.ReadFull(buf, methods); err != nil {
		log.Println("Failed to read SOCKS5 methods:", err)
		return
	}
	// 回复：选择无认证方式（0x00）
	if _, err := conn.Write([]byte{0x05, 0x00}); err != nil {
		log.Println("Failed to write SOCKS5 method selection:", err)
		return
	}
	// 读取请求头（前4字节）
	reqHeader := make([]byte, 4)
	if _, err := io.ReadFull(buf, reqHeader); err != nil {
		log.Println("Failed to read SOCKS5 request header:", err)
		return
	}
	if reqHeader[0] != 0x05 {
		log.Println("Invalid SOCKS version in request:", reqHeader[0])
		return
	}
	if reqHeader[1] != 0x01 { // 只支持 CONNECT 命令
		log.Println("Unsupported SOCKS5 command:", reqHeader[1])
		return
	}
	addrType := reqHeader[3]
	var destAddr string
	switch addrType {
	case 0x01: // IPv4
		addrBytes := make([]byte, 4)
		if _, err := io.ReadFull(buf, addrBytes); err != nil {
			log.Println("Failed to read IPv4 address:", err)
			return
		}
		destAddr = net.IP(addrBytes).String()
	case 0x03: // 域名
		domainLen, err := buf.ReadByte()
		if err != nil {
			log.Println("Failed to read domain length:", err)
			return
		}
		domainBytes := make([]byte, domainLen)
		if _, err := io.ReadFull(buf, domainBytes); err != nil {
			log.Println("Failed to read domain:", err)
			return
		}
		destAddr = string(domainBytes)
	case 0x04: // IPv6
		addrBytes := make([]byte, 16)
		if _, err := io.ReadFull(buf, addrBytes); err != nil {
			log.Println("Failed to read IPv6 address:", err)
			return
		}
		destAddr = net.IP(addrBytes).String()
	default:
		log.Println("Unsupported address type:", addrType)
		return
	}
	// 读取目标端口（2字节）
	portBytes := make([]byte, 2)
	if _, err := io.ReadFull(buf, portBytes); err != nil {
		log.Println("Failed to read port:", err)
		return
	}
	port := int(portBytes[0])<<8 | int(portBytes[1])
	target := fmt.Sprintf("%s:%d", destAddr, port)
	log.Printf("SOCKS5 connect target: %s", target)
	remoteConn, err := dialTarget(target)
	if err != nil {
		// 回复失败：一般返回 0x01 表示通用错误
		reply := []byte{0x05, 0x01, 0x00, 0x01, 0, 0, 0, 0, 0, 0}
		conn.Write(reply)
		return
	}
	// 回复成功（此处绑定地址和端口置0）
	reply := []byte{0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0}
	if _, err := conn.Write(reply); err != nil {
		log.Println("Failed to write SOCKS5 reply:", err)
		return
	}
	// 开始双向转发数据
	go transfer(remoteConn, conn)
	go transfer(conn, remoteConn)
}
