package main

import (
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"
)

var currentListener net.Listener
var listenerMutex sync.Mutex

func closePreviousListener() {
	listenerMutex.Lock()
	defer listenerMutex.Unlock()
	if currentListener != nil {
		_ = currentListener.Close()
		currentListener = nil
		log.Println("🔌 Previous listener closed")
	}
}

func startHTTPProxy() {
	addr := fmt.Sprintf("%s:%d", config.ListenOn, config.ListenPort)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("HTTP proxy failed to listen: %v", err)
	}
	log.Printf("Starting HTTP proxy on %s", addr)

	listenerMutex.Lock()
	currentListener = ln
	listenerMutex.Unlock()

	http.Serve(ln, http.HandlerFunc(httpProxyHandler))
}

func startSocks5Proxy() {
	addr := fmt.Sprintf("%s:%d", config.ListenOn, config.ListenPort)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("SOCKS5 proxy failed to listen: %v", err)
	}
	log.Printf("Starting SOCKS5 proxy on :%s", addr)

	listenerMutex.Lock()
	currentListener = ln
	listenerMutex.Unlock()

	for {
		conn, err := ln.Accept()
		if err != nil {
			log.Println("Accept error:", err)
			return
		}
		go handleSocks5Connection(conn)
	}
}

func getListenAddr(cfg Config) string {
	return fmt.Sprintf("%s:%d", cfg.ListenOn, cfg.ListenPort)
}
