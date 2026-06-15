# WiFi 漫游后频繁掉线

## 适用范围
- AMR 在现场移动过程中，网络时好时坏，常见于跨 AP 区域移动、弱信号区切换或 1300D 接入不稳定场景。
- 适用于“静止时基本正常，一移动就掉线”或“同一路线反复掉线”的问题。

## 典型现象
- 机器人在固定路线移动到某一段时反复掉线。
- 飞书、前端或主机端看到机器人在线状态频繁抖动。
- SSH、ping 在静止时较稳定，移动后开始超时或丢包。
- Tailscale、WebSocket 或后端连接表现为间歇中断。

## 优先检查
1. 先确认掉线是否总发生在同一片区域，区分漫游问题和整机网络异常。
2. 检查 `nmcli d show`、`iwconfig` 或现场 WiFi 信号强度，确认 RSSI 是否明显波动。
3. 检查 1300D 路由器、现场 AP 和网线连接是否存在松动或供电不稳。
4. 再结合 `tailscale status`、`ping`、`ssh` 结果确认是 WiFi 漫游抖动还是更上层链路中断。

## 关键日志
- `scripts/network_diag.sh` 输出
- `nmcli d show`
- `ip addr show`
- `ip route`
- `tailscale status`
- `~/log/not_permanent/<时间目录>/default.launch` 中网络相关异常

## 常见检索词
- WiFi 漫游
- 移动就掉线
- 跑到某个位置掉线
- 网络一会好一会坏
- 信号不稳
- AP 切换后掉线

## 判定口径
- 如果静止正常、移动后异常，更像 WiFi 漫游或信号覆盖问题。
- 如果静止和移动都频繁异常，更像路由器、网线、VPN 或主机侧链路问题。

## 常见根因
- 现场 AP 覆盖不足，漫游区信号过弱。
- 1300D 路由器到上游 WiFi 的接入不稳定。
- 机器人移动过程中天线、网线或供电抖动。
- 漫游切换过慢，导致上层连接频繁断开。

## 处理建议
1. 先确认是否为固定区域掉线，并记录时间点和位置。
2. 如果明显是漫游区问题，优先优化 AP 覆盖、信号强度和切换策略。
3. 如果同时伴随 1300D 异常，先排查路由器供电、网线和 WAN / WiFi 接入方式。
4. 修复后重复跑同一路线验证，确认移动过程中连接持续稳定。

## 参考文档
- [README.md](README.md)
- [network-connectivity-failure.md](network-connectivity-failure.md)
- [../system-architecture.md](../system-architecture.md)
