package main

import (
	"fmt"
	"log"
	"net"
	"net/url"

	"golang.org/x/net/proxy"
)

// getChainDialer 根据配置的远端模式生成 dialer
func getChainDialer() (proxy.Dialer, error) {
	addr := fmt.Sprintf("%s:%d", config.DefaultTarget.IP, config.DefaultTarget.Port)
	if config.RemoteMode == "socks5" {
		return proxy.SOCKS5("tcp", addr, nil, proxy.Direct)
	} else if config.RemoteMode == "http" {
		proxyURL, err := url.Parse("http://" + addr)
		if err != nil {
			return nil, err
		}
		return proxy.FromURL(proxyURL, proxy.Direct)
	}
	return nil, fmt.Errorf("unsupported remote_mode: %s", config.RemoteMode)
}

// dialTarget 根据目标地址判断是直连还是通过链式代理转发
func dialTarget(target string) (net.Conn, error) {
	if isDirectTarget(target) {
		log.Printf("dialTarget %s -> Direct", target)
		return net.Dial("tcp", target)
	}
	dialer, err := getChainDialer()
	if err != nil {
		return nil, err
	}
	//log.Printf("dialTarget %s -> Proxy", target)
	return dialer.Dial("tcp", target)
}
