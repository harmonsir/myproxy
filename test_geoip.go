package main

import (
	"fmt"
	"log"
	"net"
)

func test_geoip() {
	// 示例：远端加载 IP 网段文件，使用固定缓存文件名 "cache_ipranges.txt"
	remoteFilename := "https://example.com/ipranges.txt"
	if err := loadIPRangesCached(remoteFilename); err != nil {
		log.Fatalf("Failed to load IP ranges: %v", err)
	}

	// 测试几个 IP 是否在加载的网段内
	testIPs := []string{
		"1.0.1.5",     // 例如在 1.0.1.0/24 内
		"1.0.3.1",     // 可能不在网段内
		"2001:db8::1", // IPv6 示例
	}

	for _, s := range testIPs {
		ip := net.ParseIP(s)
		if ip == nil {
			fmt.Printf("Invalid IP: %s\n", s)
			continue
		}
		if isIPInRanges(ip) {
			fmt.Printf("%s is in range\n", s)
		} else {
			fmt.Printf("%s is NOT in range\n", s)
		}
	}
}
