# 网络连通性异常 / 设备连不上

## 适用范围

- AMR 到 RCS 主机、路由器、局域网或 VPN 的连通性异常。
- 常见表现包括 ping 不通、SSH 失败、飞书触发后取不到远程证据、设备偶发掉线。

## 典型现象

- 机器人在线状态不稳定，偶发掉线。
- `ping` 失败、`ssh` 失败或只能进入认证阶段。
- Tailscale / WiFi / 路由器链路存在间歇抖动。
- 同一设备在不同时间段表现不一致，像是链路层波动而不是单点配置错误。

## 优先检查

1. 先确认目标 IP / 主机名是否正确，避免把地址写错当成网络故障。
2. 检查本机到目标的 `ping`、`ssh`、DNS 和路由表。
3. 查看 WiFi、Tailscale、1300D 路由器和现场网线状态。
4. 如果只是在 SSH 阶段失败，再区分是认证问题还是链路不可达。

## 关键日志

- `scripts/network_diag.sh` 输出
- `ip addr show`
- `ip route`
- `nmcli d show`
- `tailscale status`
- `tailscale netcheck`
- `chronyc sources`

## 常见根因

- 目标地址写错，或者连的不是当前问题设备。
- WiFi / 网线 / 1300D 路由器链路不稳定。
- Tailscale / VPN 状态异常。
- SSH 认证失败，但网络本身其实可达。
- 时间同步偏差过大，间接影响认证或服务联通。

## 处理建议

1. 先排除地址错误和局域网基础连通性问题。
2. 如果 `ping` 不通，优先查路由器、网线、WiFi 和 VPN。
3. 如果 `ping` 通但 `ssh` 不通，优先判断是认证失败还是权限问题。
4. 如果链路抖动反复出现，记录时间点并交叉查看 `chronyc` 和现场网络状态。
5. 修复后再重试一次飞书触发和远程取证，确认链路恢复。

## 参考文档

- [common-faults.md](common-faults.md)
- [system-architecture.md](system-architecture.md)
- [error-tracing-methods.md](error-tracing-methods.md)
