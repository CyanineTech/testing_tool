# 历史案例：运行一段时间后温升触发链路不稳定

## 适用范围

- 开机初期正常，运行一段时间后设备、总线或传感器链路开始不稳定。
- 适用于“不是一上电就坏，而是热起来后才出问题”的历史硬件复盘。

## 典型现象

- 刚启动检查都正常，运行十几分钟或更久后开始掉线。
- 同一路线、同任务跑久了更容易出现 USB、CAN、串口或传感器异常。
- 重启后短时间恢复，过一阵又复现。

## 历史复盘优先

- 先固定“开始运行正常”到“第一次异常出现”的时间跨度，不要只看当前状态。
- 优先对照运行时长、环境温度、机柜温升、设备温度与异常出现时刻。
- 不要因为重启后短暂恢复，就把问题误判成随机偶发。

## 优先检查

1. 先确认异常是否总在运行一段时间后出现，而不是立即出现。
2. 检查散热、通风、设备外壳温度、Hub / 转接器温升和供电稳定性。
3. 对照 `dmesg -T`、`lsusb -t`、`ip -s -d link show can0` 看异常是否在温升后集中出现。
4. 如果多个设备一起变差，优先查公共供电、机柜温升和总线设备发热。

## 关键日志

- `dmesg -T`
- `lsusb -t`
- `ip -s -d link show can0`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`

## 常见检索词

- 跑一会才出问题
- 热起来后掉线
- 运行久了就不稳
- 重启后又好一阵
- 温度高后异常
- 过一会 can 就报错

## 判定口径

- 如果总是在运行一段时间后才开始异常，更像温升或热稳定性问题。
- 如果一上电就异常，则更像持续供电、配置或物理连接问题。

## 常见根因

- Hub、转接器、相机或串口设备热稳定性差。
- 机柜或安装空间散热不足。
- 温升导致供电电压边界变差，引发链路抖动。
- 长时间运行后线束或接口局部受热接触不稳定。

## 处理建议

1. 先记录“正常持续多久、何时开始异常”，不要只记录报错本身。
2. 优先排散热、供电和发热源，再看驱动和软件参数。
3. 修复后要做“持续运行”复测，而不是只做开机短测。

## 参考文档

- [history-case-vibration-causes-intermittent-drop.md](history-case-vibration-causes-intermittent-drop.md)
- [sensor-power-or-connector-instability.md](sensor-power-or-connector-instability.md)
- [usb-hub-or-dock-emi-instability.md](usb-hub-or-dock-emi-instability.md)

