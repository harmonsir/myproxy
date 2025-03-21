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

// ------------------ 数据结构定义 ------------------

// IPv4Range 表示一个 IPv4 地址区间
type IPv4Range struct {
	start uint32
	end   uint32
}

// IPv6Range 表示一个 IPv6 地址区间（16字节数组）
type IPv6Range struct {
	start [16]byte
	end   [16]byte
}

// 全局存储已加载的网段
var ipv4Ranges []IPv4Range
var ipv6Ranges []IPv6Range

// ------------------ 辅助函数 ------------------

// ipToUint32 将 IPv4 地址转换为 uint32（大端序）
func ipToUint32(ip net.IP) uint32 {
	return binary.BigEndian.Uint32(ip.To4())
}

// compare16 比较两个 16 字节数组，返回 -1、0 或 1
func compare16(a, b [16]byte) int {
	for i := 0; i < 16; i++ {
		if a[i] < b[i] {
			return -1
		} else if a[i] > b[i] {
			return 1
		}
	}
	return 0
}

// ------------------ IP 范围加载 ------------------

// loadIPRangesFromFile 从指定本地文件加载 CIDR 网段，并解析存入全局变量
func loadIPRangesFromFile(filename string) error {
	file, err := os.Open(filename)
	if err != nil {
		return err
	}
	defer file.Close()

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
		if ip4 := ipnet.IP.To4(); ip4 != nil {
			start := ipToUint32(ip4)
			mask := binary.BigEndian.Uint32(ipnet.Mask)
			end := start | ^mask
			ipv4Ranges = append(ipv4Ranges, IPv4Range{start: start, end: end})
		} else {
			ip16 := ipnet.IP.To16()
			if ip16 == nil {
				continue
			}
			var startArr [16]byte
			copy(startArr[:], ip16)
			var maskArr [16]byte
			copy(maskArr[:], ipnet.Mask)
			var endArr [16]byte
			for i := 0; i < 16; i++ {
				endArr[i] = startArr[i] | ^maskArr[i]
			}
			ipv6Ranges = append(ipv6Ranges, IPv6Range{start: startArr, end: endArr})
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}

	// 排序：方便后续二分查找
	sort.Slice(ipv4Ranges, func(i, j int) bool {
		return ipv4Ranges[i].start < ipv4Ranges[j].start
	})
	sort.Slice(ipv6Ranges, func(i, j int) bool {
		return compare16(ipv6Ranges[i].start, ipv6Ranges[j].start) < 0
	})
	return nil
}

// loadIPRangesCached 根据 filename 加载网段数据：
// 如果 filename 为 http/https，则使用固定缓存文件名 "cache_ipranges.txt" 进行远端加载与缓存更新；
// 否则直接当作本地文件加载。
func loadIPRangesCached(filename string) error {
	var localFile string
	if strings.HasPrefix(filename, "http://") || strings.HasPrefix(filename, "https://") {
		cacheFile := "cache_ipranges.txt"
		localFile = cacheFile
		needUpdate := true

		if info, err := os.Stat(cacheFile); err == nil {
			if time.Since(info.ModTime()) < 7*24*time.Hour {
				log.Printf("Using cache file %s (modified within 7 days)", cacheFile)
				needUpdate = false
			} else {
				log.Printf("Cache file %s is older than 7 days, will attempt to update", cacheFile)
			}
		} else {
			log.Printf("Cache file %s does not exist, will attempt remote load", cacheFile)
		}

		if needUpdate {
			log.Printf("Fetching remote file: %s", filename)
			resp, err := http.Get(filename)
			if err != nil || resp.StatusCode != http.StatusOK {
				log.Printf("Remote load failed: %v, status: %v", err, resp.Status)
				if _, err := os.Stat(cacheFile); err == nil {
					log.Printf("Using existing cache file %s despite remote load failure", cacheFile)
					localFile = cacheFile
				} else {
					return fmt.Errorf("remote load failed and no cache available")
				}
			} else {
				defer resp.Body.Close()
				body, err := io.ReadAll(resp.Body)
				if err != nil {
					return fmt.Errorf("failed to read remote response: %v", err)
				}
				if err := os.WriteFile(cacheFile, body, 0644); err != nil {
					log.Printf("Failed to write cache file %s: %v", cacheFile, err)
					if _, err := os.Stat(cacheFile); err == nil {
						localFile = cacheFile
					} else {
						return fmt.Errorf("failed to write cache file and no cache available")
					}
				} else {
					log.Printf("Cache file %s updated successfully", cacheFile)
				}
			}
		}
	} else {
		localFile = filename
	}
	return loadIPRangesFromFile(localFile)
}

// ------------------ 查询函数 ------------------

// isIPInRanges 判断给定 IP 是否落在任一已加载网段中
func isIPInRanges(ip net.IP) bool {
	if ip4 := ip.To4(); ip4 != nil {
		ipUint := ipToUint32(ip4)
		i := sort.Search(len(ipv4Ranges), func(i int) bool {
			return ipv4Ranges[i].end >= ipUint
		})
		return i < len(ipv4Ranges) && ipv4Ranges[i].start <= ipUint && ipUint <= ipv4Ranges[i].end
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
	return i < len(ipv6Ranges) && compare16(ipv6Ranges[i].start, ipArr) <= 0 && compare16(ipv6Ranges[i].end, ipArr) >= 0
}

// ------------------ 主函数及示例 ------------------
