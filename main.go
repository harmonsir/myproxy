package main

import (
	"log"
	"strings"
)

var currentListenAddr string

func main() {
	if err := loadConfig(); err != nil {
		log.Fatalf("Error loading config: %v", err)
	}
	initChinaIPs()

	currentListenAddr = getListenAddr(config)

	go startConfigWebServer()
	go startTray()
	go startProxy()

	if strings.ToLower(config.LocalMode) != "socks5" && config.EnableWindowsProxy {
		go enableWindowsSystemProxy()
		go setProxyOverride()
	} else {
		go disableWindowsSystemProxy()
	}

	for {
		select {
		case <-proxyRestartChan:
			log.Println("🔁 Restarting proxy service...")
			go startProxy()
		}
	}
}

func startProxy() {
	closePreviousListener()

	addr := getListenAddr(config)
	currentListenAddr = addr

	requestTrayStatusUpdate() // 托盘状态更新（统一调用）

	mode := strings.ToLower(config.LocalMode)
	switch mode {
	case "http":
		startHTTPProxy()
	case "socks5":
		startSocks5Proxy()
	default:
		log.Printf("Unsupported local_mode: %s", config.LocalMode)
	}
}
