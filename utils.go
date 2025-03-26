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

// SetAllProxies 启用 WinHTTP 和系统注册表代理
func SetAllProxies() {
	startWindowsProxy()
	enableWindowsSystemProxy()
}

// ClearAllProxies 关闭系统代理并重置 WinHTTP 代理
func ClearAllProxies() {
	disableWindowsSystemProxy()
	resetWindowsProxy()
}

// SetProxyExceptions 设置例外的域名走直连
func SetProxyExceptions() {
	setProxyOverride()
}

func startWindowsProxy() {
	proxyAddr := fmt.Sprintf("127.0.0.1:%d", config.ListenPort)
	cmd := exec.Command("netsh", "winhttp", "set", "proxy", proxyAddr)

	// 隐藏 cmd 窗口
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow: true,
	}

	if err := cmd.Run(); err != nil {
		log.Printf("设置 Windows WinHTTP 代理失败: %v", err)
	} else {
		log.Printf("成功设置 WinHTTP 代理为: %s", proxyAddr)
	}
}

func resetWindowsProxy() {
	cmd := exec.Command("netsh", "winhttp", "reset", "proxy")

	// 隐藏命令提示符窗口
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow: true,
	}

	if err := cmd.Run(); err != nil {
		log.Printf("重置 WinHTTP 代理失败: %v", err)
	} else {
		log.Println("WinHTTP 代理已重置为默认（无代理）")
	}
}

func enableWindowsSystemProxy() {
	proxyAddress := fmt.Sprintf("127.0.0.1:%d", config.ListenPort)

	key, _, err := registry.CreateKey(registry.CURRENT_USER, `Software\Microsoft\Windows\CurrentVersion\Internet Settings`, registry.SET_VALUE)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetDWordValue("ProxyEnable", 1); err != nil {
		log.Printf("设置 ProxyEnable 失败: %v", err)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = true })
		log.Printf("ProxyEnable 设置为 1")
	}

	if err := key.SetStringValue("ProxyServer", proxyAddress); err != nil {
		log.Printf("设置 ProxyServer 失败: %v", err)
	} else {
		log.Printf("ProxyServer 设置为 %s", proxyAddress)
	}
}

func disableWindowsSystemProxy() {
	key, err := registry.OpenKey(registry.CURRENT_USER, `Software\Microsoft\Windows\CurrentVersion\Internet Settings`, registry.SET_VALUE)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetDWordValue("ProxyEnable", 0); err != nil {
		log.Printf("禁用 ProxyEnable 失败: %v", err)
	} else {
		trayState.Update(func(s *TrayStatus) { s.SysProxy = false })
		log.Printf("ProxyEnable 设置为 0")
	}
}

func setProxyOverride() {
	bypass := "<local>;*.pylab.me;*.trip2w.com"

	key, err := registry.OpenKey(registry.CURRENT_USER, `Software\Microsoft\Windows\CurrentVersion\Internet Settings`, registry.SET_VALUE)
	if err != nil {
		log.Printf("打开注册表键失败: %v", err)
		return
	}
	defer key.Close()

	if err := key.SetStringValue("ProxyOverride", bypass); err != nil {
		log.Printf("设置 ProxyOverride 失败: %v", err)
	} else {
		log.Printf("ProxyOverride 设置为: %s", bypass)
	}
}
