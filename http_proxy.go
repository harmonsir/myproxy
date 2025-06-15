package main

import (
	"io"
	"log"
	"net"
	"net/http"
	"strings"
)

var (
	ipHeaders = []string{
		//"Forwarded": `for=${fakeIP}`, //https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Forwarded
		"CF-Connecting-IP",
		"True-Client-IP",
		"X-Client-IP",
		"X-Forwarded",
		//"Fastly-Client-IP",
		"X-Cluster-Client-IP",
		"X-Original-Forwarded-For",

		"Via",
		"CLIENT_IP",
		"REMOTE_HOST",
		"REMOTE_ADDR",
		"X_FORWARDED_FOR",
		"X-Forwarded-For",
		"X-Real-IP",
	}
)

func shouldRewriteHeader(host string) bool {
	if config.HeaderRewrite == 0 {
		return false
	}
	if config.HeaderRewrite == 1 {
		return true
	}
	if config.HeaderRewrite == 2 {
		hostOnly, _, _ := net.SplitHostPort(host)
		if ip := net.ParseIP(hostOnly); ip != nil {
			return !IsPrivateIP(ip)
		}
		// 若是域名，解析 IP 并判断
		ips, err := net.LookupIP(hostOnly)
		if err != nil {
			return true // 保守起见，失败时仍进行修改
		}
		for _, ip := range ips {
			if !IsPrivateIP(ip) {
				return true
			}
		}
		return false
	}
	return false
}

// ✅ 改写请求头
func modifyHeaders(req *http.Request) {
	req.Header.Set("DNT", "1")
	for _, k := range ipHeaders {
		req.Header.Set(k, config.FakeIP)
	}
}

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

	// 改写请求头
	if shouldRewriteHeader(req.Host) {
		modifyHeaders(req)
	}

	resp, err := transport.RoundTrip(req)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	copyHeaders(w.Header(), resp.Header)
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

	// 开始双向转发数据
	done := make(chan struct{})
	go transferData(conn, clientConn, done)
	go transferData(clientConn, conn, done)
	<-done
}
