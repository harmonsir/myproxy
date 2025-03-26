package main

import (
	_ "embed"
	"log"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/getlantern/systray"
)

var iconData = []byte{
	0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x10, 0x10, 0x00, 0x00, 0x00, 0x00,
	0x20, 0x00, 0x71, 0x01, 0x00, 0x00, 0x16, 0x00, 0x00, 0x00, 0x89, 0x50,
	0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48,
	0x44, 0x52, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x10, 0x08, 0x06,
	0x00, 0x00, 0x00, 0x1f, 0xf3, 0xff, 0x61, 0x00, 0x00, 0x01, 0x38, 0x49,
	0x44, 0x41, 0x54, 0x78, 0x9c, 0x95, 0xd3, 0xcf, 0x2b, 0xe5, 0x61, 0x14,
	0x06, 0xf0, 0x8f, 0x7b, 0x67, 0xc1, 0xcd, 0xf8, 0x51, 0x4a, 0x29, 0x99,
	0x66, 0x21, 0x61, 0xc3, 0x46, 0xb1, 0xa0, 0x94, 0x95, 0x64, 0xc3, 0x52,
	0xb6, 0xa6, 0xa9, 0x69, 0x56, 0xb3, 0x9b, 0x28, 0xf9, 0x1f, 0xdc, 0x52,
	0xae, 0x6c, 0x6d, 0x64, 0xc5, 0xac, 0xd8, 0xcd, 0x3f, 0x30, 0xb1, 0x9b,
	0x26, 0x59, 0x4c, 0x8a, 0x28, 0x21, 0x3f, 0x3a, 0xf5, 0xaa, 0xb7, 0x9b,
	0xf2, 0xf5, 0xd4, 0xb7, 0xb7, 0x73, 0x3a, 0xe7, 0x39, 0xe7, 0x39, 0xe7,
	0x7c, 0x29, 0x8e, 0x0e, 0x6c, 0xe3, 0x1a, 0xa7, 0x58, 0x45, 0xf9, 0x43,
	0xc1, 0xe4, 0x06, 0xec, 0xe0, 0x33, 0x7e, 0xa0, 0x0d, 0x3f, 0x71, 0x5b,
	0xb4, 0x7a, 0x0f, 0x9e, 0x30, 0x95, 0xf9, 0xd6, 0xf0, 0xb7, 0x54, 0x90,
	0x60, 0x24, 0xbd, 0xff, 0x33, 0xdf, 0x19, 0x5a, 0xf2, 0xa0, 0x26, 0x7c,
	0xcc, 0xec, 0x20, 0x9f, 0xc1, 0x61, 0xaa, 0x1e, 0xed, 0xfe, 0xc6, 0x18,
	0x26, 0xf1, 0x0f, 0x9b, 0x11, 0x58, 0xc1, 0x16, 0xee, 0xf1, 0x88, 0x5f,
	0xf8, 0x8a, 0x3f, 0xc9, 0xde, 0xc3, 0x04, 0x7a, 0x71, 0x9c, 0xc8, 0xe2,
	0xdb, 0x45, 0x6b, 0x10, 0x54, 0x71, 0x8e, 0x05, 0xcc, 0xe1, 0x24, 0x05,
	0x6c, 0xa0, 0xbf, 0x4e, 0x4a, 0x74, 0x35, 0x88, 0xee, 0xdc, 0x79, 0x89,
	0xef, 0x99, 0x3d, 0x9a, 0x08, 0x62, 0x70, 0x6f, 0xa2, 0x94, 0xde, 0x90,
	0xf1, 0x82, 0xb2, 0x77, 0xa2, 0x8a, 0x2b, 0x2c, 0x62, 0x36, 0x69, 0x8f,
	0x0e, 0xd6, 0xd1, 0xf7, 0x4a, 0xc1, 0x01, 0x7c, 0xca, 0x9d, 0x15, 0xd4,
	0x70, 0x97, 0x86, 0xb6, 0x8f, 0x6f, 0x69, 0x16, 0x0f, 0x69, 0x58, 0xe3,
	0x49, 0x7b, 0x3e, 0xc4, 0x03, 0xb4, 0xe7, 0x44, 0x8d, 0x68, 0xae, 0xab,
	0x16, 0x1d, 0x1d, 0x65, 0x6b, 0x8c, 0x95, 0x0e, 0x61, 0x3a, 0x9d, 0x73,
	0xad, 0xa8, 0xcc, 0xf9, 0x44, 0x32, 0x9c, 0xf9, 0xbe, 0xe0, 0xa2, 0xe8,
	0x25, 0xc6, 0x01, 0x05, 0xba, 0x32, 0x5f, 0x27, 0x6e, 0x8a, 0x76, 0x10,
	0x08, 0xcd, 0xd1, 0xf6, 0x12, 0x56, 0x52, 0xf2, 0xf2, 0x7b, 0x08, 0x62,
	0x60, 0xa1, 0x39, 0x36, 0x16, 0xff, 0x41, 0x24, 0x97, 0x9f, 0x01, 0x91,
	0x6e, 0x44, 0x4b, 0xd6, 0xd3, 0x82, 0x48, 0x00, 0x00, 0x00, 0x00, 0x49,
	0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
}

type TrayStatus struct {
	Tooltip  string
	Title    string
	Status   bool
	SysProxy bool
}

type TrayState struct {
	tooltip  string
	title    string
	status   bool
	sysProxy bool
	ch       chan TrayStatus
}

func NewTrayState() *TrayState {
	return &TrayState{ch: make(chan TrayStatus, 1)}
}

func (ts *TrayState) Update(updateFn func(s *TrayStatus)) {
	current := TrayStatus{
		Tooltip:  ts.tooltip,
		Title:    ts.title,
		Status:   ts.status,
		SysProxy: ts.sysProxy,
	}
	updateFn(&current)

	ts.tooltip = current.Tooltip
	ts.title = current.Title
	ts.status = current.Status
	ts.sysProxy = current.SysProxy

	ts.ch <- current
}

func (ts *TrayState) Channel() <-chan TrayStatus {
	return ts.ch
}

func (ts *TrayState) SysProxyEnabled() bool {
	return ts.sysProxy
}

var (
	statusItem  *systray.MenuItem
	toggleProxy *systray.MenuItem
	trayState   = NewTrayState()
)

func startTray() {
	systray.Run(onReady, onExit)
}

func onReady() {
	systray.SetIcon(iconData)
	systray.SetTitle("本地代理服务")
	systray.SetTooltip("正在启动代理...")

	statusItem = systray.AddMenuItem("状态: 启动中...", "当前运行状态")
	statusItem.Disable()

	toggleProxy = systray.AddMenuItem("系统代理状态", "点击切换系统代理")

	openConf := systray.AddMenuItem("打开配置页面", "http://localhost:8081")
	quit := systray.AddMenuItem("退出程序", "关闭程序")

	// 状态监听并更新 UI
	go func() {
		for status := range trayState.Channel() {
			systray.SetTooltip(status.Tooltip)
			if statusItem != nil {
				statusItem.SetTitle(status.Title)
			}
			if toggleProxy != nil {
				if status.SysProxy {
					toggleProxy.SetTitle("关闭系统代理")
				} else {
					toggleProxy.SetTitle("启用系统代理")
				}
			}
		}
	}()

	// 菜单交互监听
	go func() {
		for {
			select {
			case <-toggleProxy.ClickedCh:
				if trayState.SysProxyEnabled() {
					onStopProxy()
					trayState.Update(func(s *TrayStatus) {
						s.SysProxy = false
					})
				} else {
					onStartProxy()
					trayState.Update(func(s *TrayStatus) {
						s.SysProxy = true
					})
				}
			case <-openConf.ClickedCh:
				openBrowser("http://localhost:8081")
			case <-quit.ClickedCh:
				systray.Quit()
			}
		}
	}()
}

func onExit() {
	onStopProxy()
	os.Exit(0)
}

func openBrowser(url string) {
	var cmd string
	var args []string
	switch runtime.GOOS {
	case "windows":
		cmd = "rundll32"
		args = []string{"url.dll,FileProtocolHandler", url}
	case "darwin":
		cmd = "open"
		args = []string{url}
	default:
		cmd = "xdg-open"
		args = []string{url}
	}
	if err := exec.Command(cmd, args...).Start(); err != nil {
		log.Printf("打开浏览器失败: %v", err)
	}
}

func requestTrayStatusUpdate() {
	mode := strings.ToLower(config.LocalMode)
	trayState.Update(func(s *TrayStatus) {
		switch mode {
		case "http":
			s.Tooltip = "运行中（HTTP 模式）"
			s.Title = "状态: 运行中（HTTP）"
			s.Status = true
		case "socks5":
			s.Tooltip = "运行中（SOCKS5 模式）"
			s.Title = "状态: 运行中（SOCKS5）"
			s.Status = true
		default:
			s.Tooltip = "运行失败"
			s.Title = "状态: 模式错误"
			s.Status = false
		}
	})
}

func onStartProxy() {
	SetAllProxies()
	SetProxyExceptions()
}

func onStopProxy() {
	ClearAllProxies()
}
