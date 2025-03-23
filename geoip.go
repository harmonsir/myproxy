package main

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"
)

type IPv4Range struct{ start, end uint32 }
type IPv6Range struct{ start, end [16]byte }

var ipv4Ranges []IPv4Range
var ipv6Ranges []IPv6Range

// ------------------ 辅助函数 ------------------

func ipToUint32(ip net.IP) uint32 {
	return binary.BigEndian.Uint32(ip.To4())
}

func compare16(a, b [16]byte) int {
	for i := 0; i < 16; i++ {
		switch {
		case a[i] < b[i]:
			return -1
		case a[i] > b[i]:
			return 1
		}
	}
	return 0
}

// ------------------ IP 加载逻辑 ------------------

func loadIPRangesFromFile(filename string) error {
	file, err := os.Open(filename)
	if err != nil {
		return err
	}
	defer file.Close()

	ipv4Ranges = nil
	ipv6Ranges = nil

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		_, ipnet, err := net.ParseCIDR(line)
		if err != nil {
			log.Printf("Skipping invalid CIDR %q: %v", line, err)
			continue
		}
		addIPNetToRanges(ipnet)
	}
	if err := scanner.Err(); err != nil {
		return err
	}

	sortIPRanges()
	appendLocalNetworkRanges()
	return nil
}

func addIPNetToRanges(ipnet *net.IPNet) {
	if ip4 := ipnet.IP.To4(); ip4 != nil {
		start := ipToUint32(ip4)
		mask := binary.BigEndian.Uint32(ipnet.Mask)
		end := start | ^mask
		ipv4Ranges = append(ipv4Ranges, IPv4Range{start, end})
	} else {
		ip16 := ipnet.IP.To16()
		if ip16 == nil {
			return
		}
		var startArr, endArr, maskArr [16]byte
		copy(startArr[:], ip16)
		copy(maskArr[:], ipnet.Mask)
		for i := 0; i < 16; i++ {
			endArr[i] = startArr[i] | ^maskArr[i]
		}
		ipv6Ranges = append(ipv6Ranges, IPv6Range{startArr, endArr})
	}
}

func sortIPRanges() {
	sort.Slice(ipv4Ranges, func(i, j int) bool {
		return ipv4Ranges[i].start < ipv4Ranges[j].start
	})
	sort.Slice(ipv6Ranges, func(i, j int) bool {
		return compare16(ipv6Ranges[i].start, ipv6Ranges[j].start) < 0
	})
}

func appendLocalNetworkRanges() {
	localCIDRs := []string{
		"10.0.0.0/8",
		"172.16.0.0/12",
		"192.168.0.0/16",
		"127.0.0.0/8",
		"::1/128",
		"fc00::/7",
		"fe80::/10",
	}

	for _, cidr := range localCIDRs {
		if _, ipnet, err := net.ParseCIDR(cidr); err == nil {
			addIPNetToRanges(ipnet)
		}
	}

	sortIPRanges()
}

// ------------------ 加载缓存或远程 ------------------

func loadIPRangesCached(filename string) error {
	var localFile string

	if strings.HasPrefix(filename, "http://") || strings.HasPrefix(filename, "https://") {
		cacheFile := "cache_ipranges.txt"
		localFile = cacheFile
		needUpdate := true

		if info, err := os.Stat(cacheFile); err == nil {
			if time.Since(info.ModTime()) < 7*24*time.Hour {
				log.Printf("✔ Using cache file %s (valid)", cacheFile)
				needUpdate = false
			} else {
				log.Printf("ℹ Cache file %s is outdated, attempting update", cacheFile)
			}
		}

		if needUpdate {
			log.Printf("🌐 Fetching remote file: %s", filename)
			resp, err := http.Get(filename)
			if err != nil || resp.StatusCode != http.StatusOK {
				log.Printf("⚠ Remote load failed: %v", err)
				if _, err := os.Stat(cacheFile); err == nil {
					log.Printf("✔ Falling back to cache file: %s", cacheFile)
				} else {
					return fmt.Errorf("❌ remote load failed and no cache available")
				}
			} else {
				defer resp.Body.Close()
				body, err := io.ReadAll(resp.Body)
				if err != nil {
					return fmt.Errorf("read remote failed: %v", err)
				}
				if err := os.WriteFile(cacheFile, body, 0644); err != nil {
					log.Printf("⚠ Failed to write cache, but continuing")
				} else {
					log.Printf("✔ Cache updated: %s", cacheFile)
				}
			}
		}
	} else {
		localFile = filename
	}

	return loadIPRangesFromFile(localFile)
}

// ------------------ 查询函数 ------------------

func isIPInRanges(ip net.IP) bool {
	if ip4 := ip.To4(); ip4 != nil {
		ipUint := ipToUint32(ip4)
		i := sort.Search(len(ipv4Ranges), func(i int) bool {
			return ipv4Ranges[i].end >= ipUint
		})
		return i < len(ipv4Ranges) && ipv4Ranges[i].start <= ipUint
	}

	ip16 := ip.To16()
	if ip16 == nil {
		return false
	}
	var ipArr [16]byte
	copy(ipArr[:], ip16)
	i := sort.Search(len(ipv6Ranges), func(i int) bool {
		return compare16(ipv6Ranges[i].end, ipArr) >= 0
	})
	return i < len(ipv6Ranges) &&
		compare16(ipv6Ranges[i].start, ipArr) <= 0 &&
		compare16(ipv6Ranges[i].end, ipArr) >= 0
}
