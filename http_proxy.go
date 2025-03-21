package main

import (
	"io"
	"log"
	"net"
	"net/http"
	"strings"
)

// httpProxyHandler 处理 HTTP 代理请求，包括 CONNECT 和普通 HTTP 请求
func httpProxyHandler(w http.ResponseWriter, req *http.Request) {
	target := req.Host
	if req.URL.Host != "" {
		target = req.URL.Host
	}
	log.Printf("HTTP proxy request for %s", target)
	if strings.ToUpper(req.Method) == "CONNECT" {
		handleHTTPConnect(w, req)
		return
	}
	// 非 CONNECT 请求，使用自定义 transport，通过 dialTarget 建立连接
	transport := &http.Transport{
		Dial: func(network, addr string) (net.Conn, error) {
			return dialTarget(addr)
		},
	}
	resp, err := transport.RoundTrip(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	copyHeader(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

// handleHTTPConnect 处理 HTTPS 的 CONNECT 请求
func handleHTTPConnect(w http.ResponseWriter, req *http.Request) {
	target := req.Host
	conn, err := dialTarget(target)
	if err != nil {
		http.Error(w, err.Error(), http.StatusServiceUnavailable)
		return
	}
	// 告诉客户端隧道已建立
	w.WriteHeader(http.StatusOK)
	hijacker, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "Hijacking not supported", http.StatusInternalServerError)
		return
	}
	clientConn, _, err := hijacker.Hijack()
	if err != nil {
		http.Error(w, err.Error(), http.StatusServiceUnavailable)
		return
	}
	go transfer(conn, clientConn)
	go transfer(clientConn, conn)
}
