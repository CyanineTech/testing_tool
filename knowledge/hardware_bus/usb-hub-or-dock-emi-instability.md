# USB 拓展坞 / Hub EMI 干扰不稳定

## 适用范围
- 多个 USB 外设共挂一个 Hub、拓展坞或转接板时，出现整组设备间歇掉线、重连或性能异常。
- 适用于摄像头、PCAN、CH341、音响等设备一起波动，且单独拆开时故障减轻的场景。

## 典型现象
- 多个 USB 设备在同一时间段一起掉线或重连。
- 某些设备看似随机异常，但总发生在同一组 Hub 或拓展坞下。
- 机器人运行、转向、震动或现场强干扰环境下更容易复现。
- `dmesg -T` 中反复出现 reset、disconnect、reconnect。

## 优先检查
1. 先确认异常设备是否都挂在同一个 Hub / 拓展坞层级下。
2. 检查 `lsusb -t`，确认多设备是否共享同一条上行链路。
3. 查看 `dmesg -T`，确认是否存在整组设备同时波动。
4. 再判断是否与供电不足、EMI 干扰、Hub 质量或线束布线有关。

## 关键日志
- `lsusb -t`
- `dmesg -T`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`

## 常见检索词
- 拓展坞不稳
- usb hub 异常
- 多个设备一起掉
- emi 干扰
- 同一条 usb 链路掉线
- 摄像头和 pcan 一起异常

## 判定口径
- 如果同一 Hub 下多个设备一起波动，更像拓展坞 / Hub / EMI 问题。
- 如果只有单个设备异常，更像设备本体、驱动或接插件问题。

## 常见根因
- Hub / 拓展坞自身质量不稳定。
- USB 上行供电不足。
- 线束布线靠近强干扰源，EMI 较大。
- 多设备共享带宽和供电，边界条件下更容易异常。

## 处理建议
1. 优先按“公共链路问题”处理，不要分别修单个设备。
2. 尝试拆分设备挂载、减少共挂数量或更换 Hub / 拓展坞。
3. 优化供电和布线，避开强干扰区域。
4. 修复后用同一设备组合复测，确认不是单次侥幸恢复。

## 参考文档
- [README.md](README.md)
- [usb-device-troubleshooting.md](usb-device-troubleshooting.md)
- [sensor-power-or-connector-instability.md](sensor-power-or-connector-instability.md)
