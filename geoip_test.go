package main

import (
	"net"
	"testing"
)

func TestIsIPInRanges_LocalNetworks(t *testing.T) {
	// 准备：只注入局域网网段
	ipv4Ranges = nil
	ipv6Ranges = nil
	appendLocalNetworkRanges()

	cases := []struct {
		ip     string
		expect bool
	}{
		{"192.168.1.1", true},
		{"10.0.0.5", true},
		{"172.16.100.200", true},
		{"127.0.0.1", true},
		{"::1", true},
		{"fc00::1", true},
		{"fe80::abcd", true},
		{"8.8.8.8", false},              // 应该不在局域网网段内
		{"2001:4860:4860::8888", false}, // Google IPv6
	}

	for _, c := range cases {
		ip := net.ParseIP(c.ip)
		if ip == nil {
			t.Errorf("Invalid IP: %s", c.ip)
			continue
		}
		result := isIPInRanges(ip)
		if result != c.expect {
			t.Errorf("isIPInRanges(%s) = %v; want %v", c.ip, result, c.expect)
		}
	}
}
