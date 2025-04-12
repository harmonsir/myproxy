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

	UpdateTray(StatusStarting)

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
			UpdateTray(StatusRestarting)
			go startProxy()
		}
	}
}

func startProxy() {
	closePreviousListener()

	addr := getListenAddr(config)
	currentListenAddr = addr

	mode := strings.ToLower(config.LocalMode)
	switch mode {
	case "http":
		UpdateTray(StatusRunningHTTP)
		startHTTPProxy()
	case "socks5":
		UpdateTray(StatusRunningSocks5)
		startSocks5Proxy()
	default:
		UpdateTray(StatusError)
		log.Printf("Unsupported local_mode: %s", config.LocalMode)
	}
}
