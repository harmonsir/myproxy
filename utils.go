package main

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os/exec"
)

// transfer 在两个连接之间传输数据
func transfer(dst io.WriteCloser, src io.ReadCloser) {
	defer dst.Close()
	defer src.Close()
	io.Copy(dst, src)
}

// copyHeader 将响应头复制到目标 header 中
func copyHeader(dst, src http.Header) {
	for k, vv := range src {
		for _, v := range vv {
			dst.Add(k, v)
		}
	}
}

func startWindowsProxy() {
	proxyAddr := "127.0.0.1:" + fmt.Sprintf("%d", config.ListenPort)
	cmd := exec.Command("netsh", "winhttp", "set", "proxy", proxyAddr)
	if err := cmd.Run(); err != nil {
		log.Printf("设置 Windows 代理失败: %v", err)
	} else {
		log.Printf("成功设置 Windows 代理为: %s", proxyAddr)
	}
}

func enableWindowsSystemProxy() {
	proxyAddress := fmt.Sprintf("127.0.0.1:%d", config.ListenPort)

	// 启用代理：ProxyEnable 设为 1
	cmd := exec.Command("reg", "add", `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`, "/v", "ProxyEnable", "/t", "REG_DWORD", "/d", "1", "/f")
	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("Failed to enable ProxyEnable: %v, output: %s", err, output)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = true })
		log.Printf("ProxyEnable set to 1")
	}

	// 设置代理服务器地址：ProxyServer
	cmd = exec.Command("reg", "add", `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`, "/v", "ProxyServer", "/t", "REG_SZ", "/d", proxyAddress, "/f")
	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("Failed to set ProxyServer: %v, output: %s", err, output)
	} else {
		log.Printf("ProxyServer set to %s", proxyAddress)
	}
}

func disableWindowsSystemProxy() {
	// 启用代理：ProxyEnable 设为 1
	cmd := exec.Command("reg", "add", `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`, "/v", "ProxyEnable", "/t", "REG_DWORD", "/d", "0", "/f")
	if output, err := cmd.CombinedOutput(); err != nil {
		log.Printf("Failed to disable ProxyEnable: %v, output: %s", err, output)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = false })
		log.Printf("ProxyEnable set to 0")
	}
}

func setProxyOverride() {
	// 例外列表，包含局域网 (<local>) 以及指定域名
	bypass := "<local>;*.pylab.me;*.trip2w.com"
	cmd := exec.Command("reg", "add", `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`, "/v", "ProxyOverride", "/t", "REG_SZ", "/d", bypass, "/f")
	output, err := cmd.CombinedOutput()
	if err != nil {
		log.Printf("Failed to set ProxyOverride: %v, output: %s", err, output)
	} else {
		log.Printf("ProxyOverride set to: %s", bypass)
	}
}
