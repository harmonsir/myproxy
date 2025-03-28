# myproxy

SwitchyOmega 已经太老了，用GPT写个proxy做Window下面的全局代理吧。

**会自动根据IP进行学术上网。**


### build

```
set CGO_ENABLED=0
go build -ldflags="-s -w -H=windowsgui"
```

### config

```yaml
enable_windows_proxy: false

local_mode: "http"     # 或 "http"
listen_on: "127.0.0.1"
listen_port: 1080

remote_mode: "socks5"    # 或 "http"
default_target:
  ip: "1.2.3.4"
  port: 12340

china_ips: "https://cdn.jsdelivr.net/gh/Loyalsoldier/geoip@release/text/cn.txt"
```