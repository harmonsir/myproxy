package main

import (
	_ "embed"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"sync"

	"gopkg.in/yaml.v2"
)

var configMutex sync.RWMutex
var proxyRestartChan = make(chan bool, 1)

//go:embed static/index.html
var embeddedIndexHTML []byte

func getConfigHandler(w http.ResponseWriter, r *http.Request) {
	configMutex.RLock()
	defer configMutex.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(config)
}

func updateConfigHandler(w http.ResponseWriter, r *http.Request) {
	var newConfig Config
	if err := json.NewDecoder(r.Body).Decode(&newConfig); err != nil {
		http.Error(w, "Invalid JSON", http.StatusBadRequest)
		return
	}

	configMutex.Lock()
	oldConfig := config
	config = newConfig
	configMutex.Unlock()

	data, err := yaml.Marshal(config)
	if err != nil {
		http.Error(w, "YAML marshal error", http.StatusInternalServerError)
		return
	}
	if err := os.WriteFile("config.yaml", data, 0644); err != nil {
		http.Error(w, "Failed to save config.yaml", http.StatusInternalServerError)
		return
	}

	InitChinaIPs()
	if config.ChinaIps != "" {
		loadIPRangesCached(config.ChinaIps)
	}

	oldAddr := getListenAddr(oldConfig)
	newAddr := getListenAddr(config)

	if newAddr != oldAddr || oldConfig.LocalMode != config.LocalMode || oldConfig.RemoteMode != config.RemoteMode {
		go func() {
			proxyRestartChan <- true
		}()
		w.Write([]byte("配置已更新，代理服务将自动重启生效"))
		return
	}

	w.Write([]byte("配置更新成功!"))
	log.Println("Configuration updated successfully")
}

func startConfigWebServer() {
	mux := http.NewServeMux()

	mux.HandleFunc("/api/config", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			getConfigHandler(w, r)
		case http.MethodPost:
			updateConfigHandler(w, r)
		default:
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		}
	})

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.Write(embeddedIndexHTML)
	})

	log.Println("Config web interface is running at: http://localhost:8081")
	if err := http.ListenAndServe(":8081", mux); err != nil {
		log.Fatalf("Failed to start config server: %v", err)
	}
}
