# 历史案例：运行振动导致设备间歇掉线

## 适用范围

- 设备静止时基本正常，但一运行、转弯、过坎或震动后就开始掉线。
- 适用于“不是持续坏，而是运动中间歇复现”的历史硬件链路问题。

## 典型现象

- 上电静止检查正常，跑起来才开始报错。
- 过减速带、转弯、抬叉、落叉后更容易触发设备掉线。
- 同一设备有时是 USB 掉线，有时是 CAN / 串口异常，表现不完全一致。

## 历史复盘优先

- 优先固定掉线发生时的动作和位置，而不是只看静止状态下的当前检查结果。
- 先查故障前后 `dmesg`、`default.launch`、`mobile_base.launch`，并结合现场动作时刻复盘。
- 不要因为静态复测正常，就否定运行振动导致的物理链路问题。

## 优先检查

1. 先确认异常是否只在运行、转向、过坎、抬叉等动态过程复现。
2. 检查线束固定、接插件锁紧、传感器支架、拓展坞和供电接头是否会随振动松动。
3. 对照 `dmesg -T`、`lsusb -t`、`ip -s -d link show can0` 判断掉的是单设备还是整条链路。
4. 如果能做安全复现，优先在相同动作下验证是否稳定触发。

## 关键日志

- `dmesg -T`
- `lsusb -t`
- `ip -s -d link show can0`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`

## 常见检索词

- 跑起来才掉线
- 一震动就掉
- 转弯后掉设备
- 过坎后异常
- 静止正常运行异常
- 动起来就报 can

## 判定口径

- 如果静态检查正常、动态动作时才复现，更像振动诱发的物理链路问题。
- 如果静止和动态都不稳定，更像持续供电或总线本身异常。

## 常见根因

- 线束固定不足，振动时拉扯接插件。
- 接插件锁止不牢，动态过程中瞬断。
- 传感器支架或 Hub 安装不稳。
- 公共供电接口在运动中接触抖动。

## 处理建议

1. 先把动态复现条件记清楚，不要只做静态排查。
2. 优先处理固定、锁紧、供电和支架问题，再看驱动和参数。
3. 修复后做“同动作、同路线、同震动场景”的复测。

## 参考文档

- [sensor-power-or-connector-instability.md](sensor-power-or-connector-instability.md)
- [usb-device-troubleshooting.md](usb-device-troubleshooting.md)
- [can-eb-communication-abnormal.md](can-eb-communication-abnormal.md)

