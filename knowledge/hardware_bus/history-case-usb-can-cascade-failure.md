# 历史案例：USB 异常连带 CAN / 嵌入式级联故障

## 适用范围
- 现场问题先表现为摄像头、USB 或拓展坞异常，随后进一步扩大成 CAN、嵌入式或底层状态不稳定。
- 适用于“看起来像单个设备坏了，最后发现是整条链路问题”的历史复盘类问题。

## 典型现象
- 先看到摄像头离线、USB reset、设备重连。
- 随后 `CAN bus停止发布数据`、`cannot read eb`、`reset embedded system` 等底层错误出现。
- 单独恢复摄像头或单独恢复 CAN 都只能短暂缓解。

## 优先检查
1. 先按时间线确认 USB 异常是否早于 CAN / EB 异常出现。
2. 检查 `dmesg -T`、`lsusb -t`、`default.launch`、`mobile_base.launch` 是否能串起完整事件链。
3. 判断是单个设备掉线，还是同一 Hub / 拓展坞 / 供电链路整体波动。
4. 再决定是按 USB 总线问题处理，还是按底层 CAN 问题处理。

## 关键日志
- `dmesg -T`
- `lsusb -t`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`
- `ip -s -d link show can0`

## 常见检索词
- 先相机掉线后 can 异常
- usb 后面又报 can
- 摄像头异常连带底层故障
- 一开始是 usb 后面全挂了
- 级联故障

## 判定口径
- 如果 USB 异常总早于 CAN / EB 异常，更像总线、供电或 Hub 级联问题。
- 如果底层异常先出现，再影响感知链路，更像 CAN / 驱动侧先失稳。

## 常见根因
- 拓展坞 / Hub EMI 干扰，引发多设备级联波动。
- 公共供电不稳，先影响 USB，再扩大到底层设备。
- 线束或接插件公共链路接触不良。

## 处理建议
1. 不要按“单设备故障”思路拆开修，优先按公共链路问题处理。
2. 先稳定供电、Hub、线束和总线，再观察上层设备是否恢复。
3. 修复后按时间线复盘，确认不再出现“先 USB、后 CAN”的级联模式。

## 参考文档
- [usb-device-troubleshooting.md](usb-device-troubleshooting.md)
- [usb-hub-or-dock-emi-instability.md](usb-hub-or-dock-emi-instability.md)
- [can-eb-communication-abnormal.md](can-eb-communication-abnormal.md)
