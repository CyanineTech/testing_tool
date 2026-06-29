# 网络与连通性入口

本目录用于承接主从机掉线、WiFi 不稳、SSH 不通、路由器与网络边界问题。

## 适用范围

- AMR 掉线、无法 ping、无法 SSH、偶发网络抖动。
- 用户描述偏向“连不上”“掉线”“延迟高”“主机找不到从机”。

默认处理方式：

1. 如果故障已经过去，优先固定掉线时间、重启时间、对应日志时间段。
2. 不要直接把“现在能 ping / 现在能 SSH”当成历史掉线根因排除依据。
3. 历史问题优先看主从机日志、上一个 `boot`、WiFi / 路由器 / VPN 的历史痕迹。

## 历史复盘优先

- 网络问题大多发生在某个时间窗口或某段路线中，优先固定掉线时间、恢复时间和对应位置。
- 不要因为当前能 ping 或能 SSH，就直接排除当时的历史网络异常。
- 应优先回看对应时间段的 WiFi、VPN、SSH、系统日志和现场网络变化。

## 常见检索词

- 掉线
- 连不上
- 无法 ping
- ssh 不通
- 主机找不到从机
- wifi 漫游
- 网络抖动
- 延迟高
- dns 异常
- 路由器问题

## 建议优先补充的子类页

1. 主从机掉线
2. WiFi 漫游或弱信号
3. 1300D 路由器接线 / 配置异常
4. DNS / 主机名解析异常

## 当前已覆盖文档

- [network-connectivity-failure.md](network-connectivity-failure.md)
- [wifi-roaming-instability.md](wifi-roaming-instability.md)
- [ssh-authentication-failure.md](ssh-authentication-failure.md)
- [site-wireless-interference-or-metal-shielding.md](site-wireless-interference-or-metal-shielding.md)
- [customer-site-network-acceptance-checklist.md](customer-site-network-acceptance-checklist.md)

## 推荐命名方式

- `network-*.md`
- `wifi-*.md`
- `router-*.md`
- `ssh-*.md`

## 关联总入口

- [../system-architecture.md](../system-architecture.md)
- [../common-faults.md](../common-faults.md)
- [../log-paths.md](../log-paths.md)
