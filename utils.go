package main

import (
	"fmt"
	"golang.org/x/sys/windows/registry"
	"io"
	"log"
	"net/http"
	"os/exec"
	"syscall"
)

// transferData 在两个连接之间传输数据
func transferData(dst io.WriteCloser, src io.ReadCloser, done chan struct{}) {
	defer dst.Close()
	defer src.Close()
	io.Copy(dst, src)
	done <- struct{}{}
}

// copyHeaders 将响应头复制到目标 header 中
func copyHeaders(dst, src http.Header) {
	for key, values := range src {
		for _, v := range values {
			dst.Add(key, v)
		}
	}
}

// EnableWinHTTPProxy 单独启用 WinHTTP 代理
func EnableWinHTTPProxy() {
	configureWinHTTPProxy()
}

// DisableWinHTTPProxy 单独重置 WinHTTP 代理
func DisableWinHTTPProxy() {
	resetWinHTTPProxy()
}

// EnableSystemProxy 单独启用系统级代理
func EnableSystemProxy() {
	configureSystemProxy()
}

// DisableSystemProxy 单独禁用系统级代理
func DisableSystemProxy() {
	disableSystemProxy()
}

// EnableAllProxies 同时启用 WinHTTP 和系统级代理
func EnableAllProxies() {
	EnableWinHTTPProxy()
	EnableSystemProxy()
}

// DisableAllProxies 同时关闭系统级代理并重置 WinHTTP 代理
func DisableAllProxies() {
	DisableSystemProxy()
	DisableWinHTTPProxy()
}

// EnableBypassList 设置例外的域名走直连
func EnableBypassList() {
	configureProxyBypass()
}

func configureWinHTTPProxy() {
	proxyAddr := fmt.Sprintf("127.0.0.1:%d", config.ListenPort)
	cmd := exec.Command("netsh", "winhttp", "set", "proxy", proxyAddr)

	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}

	if err := cmd.Run(); err != nil {
		log.Printf("设置 WinHTTP 代理失败: %v", err)
	} else {
		log.Printf("WinHTTP 代理已设置为: %s", proxyAddr)
	}
}

func resetWinHTTPProxy() {
	cmd := exec.Command("netsh", "winhttp", "reset", "proxy")
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}

	if err := cmd.Run(); err != nil {
		log.Printf("重置 WinHTTP 代理失败: %v", err)
	} else {
		log.Println("WinHTTP 代理已重置为默认 (无代理)")
	}
}

func configureSystemProxy() {
	proxyAddr := fmt.Sprintf("127.0.0.1:%d", config.ListenPort)

	key, _, err := registry.CreateKey(
		registry.CURRENT_USER,
		`Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings`,
		registry.SET_VALUE,
	)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetDWordValue("ProxyEnable", 1); err != nil {
		log.Printf("启用系统代理失败: %v", err)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = true })
		log.Println("系统代理已启用")
	}

	if err := key.SetStringValue("ProxyServer", proxyAddr); err != nil {
		log.Printf("设置系统代理服务器失败: %v", err)
	} else {
		log.Printf("系统代理服务器已设置为: %s", proxyAddr)
	}
}

func disableSystemProxy() {
	key, err := registry.OpenKey(
		registry.CURRENT_USER,
		`Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings`,
		registry.SET_VALUE,
	)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetDWordValue("ProxyEnable", 0); err != nil {
		log.Printf("禁用系统代理失败: %v", err)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = false })
		log.Println("系统代理已禁用")
	}
}

func configureProxyBypass() {
	bypassList := "<local>;*.pylab.me;*.trip2w.com"

	key, err := registry.OpenKey(
		registry.CURRENT_USER,
		`Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings`,
		registry.SET_VALUE,
	)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetStringValue("ProxyOverride", bypassList); err != nil {
		log.Printf("设置访问例外失败: %v", err)
	} else {
		log.Printf("访问例外已设置为: %s", bypassList)
	}
}
