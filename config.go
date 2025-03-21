package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v2"
)

// Config 定义了配置文件结构
type Config struct {
	EnableWindowsProxy bool   `yaml:"enable_windows_proxy" json:"enable_windows_proxy"`
	LocalMode          string `yaml:"local_mode" json:"local_mode"`
	ListenOn           string `yaml:"listen_on" json:"listen_on"`
	ListenPort         int    `yaml:"listen_port" json:"listen_port"`

	RemoteMode    string `yaml:"remote_mode" json:"remote_mode"`
	DefaultTarget struct {
		IP   string `yaml:"ip" json:"ip"`
		Port int    `yaml:"port" json:"port"`
	} `yaml:"default_target" json:"default_target"`

	ChinaIps string `yaml:"china_ips" json:"china_ips"`
}

var config Config
var directIPMap map[string]bool

// loadConfig 从用户目录下加载 YAML 配置文件
func loadConfig() error {
	//home, err := os.UserHomeDir()
	//if err != nil {
	//	return err
	//}
	//configPath := filepath.Join(home, ".config", "myproxy", "config.yaml")
	configPath := filepath.Join(".", "config.yaml")
	data, err := os.ReadFile(configPath)
	if err != nil {
		return fmt.Errorf("failed to read config file %s: %v", configPath, err)
	}
	if err := yaml.Unmarshal(data, &config); err != nil {
		return fmt.Errorf("failed to parse config file: %v", err)
	}
	return nil
}

// initDirectIPMap 将配置文件中的 ipmap 加入一个 map，方便查找
//func initDirectIPMap() {
//	directIPMap = make(map[string]bool)
//	for _, ip := range config.IPMap {
//		directIPMap[ip] = true
//	}
//}

func initChinaIPs() {
	if config.ChinaIps != "" {
		if err := loadIPRangesCached(config.ChinaIps); err != nil {
			log.Fatalf("Failed to load IP ranges: %v", err)
		}
	}
}

// isDirectTarget 判断目标地址是否在直连白名单中
func isDirectTarget(host string) bool {
	hostOnly, _, err := net.SplitHostPort(host)
	if err != nil {
		hostOnly = host
	}
	if ip := net.ParseIP(hostOnly); ip != nil {
		return directIPMap[ip.String()]
	}
	// 如果是域名，则解析 DNS
	ips, err := net.LookupIP(hostOnly)
	if err != nil {
		log.Printf("DNS lookup failed for %s: %v", hostOnly, err)
		return false
	}
	for _, ip := range ips {
		if isIPInRanges(ip) {
			return true
		}
	}
	return false
}
