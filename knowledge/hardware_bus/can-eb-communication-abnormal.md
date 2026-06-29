# CAN / 嵌入式通信异常

## 适用范围

- AMR 运行中出现 `CAN bus停止发布数据`、`cannot read eb`、`cannot write eb`、`resume eb_interrupt`、`reset embedded system` 等底层异常。
- 常见于 PCAN、嵌入式控制板、电池 CAN 线、驱动板之间的链路抖动或断连。

## 历史复盘优先

- 如果用户描述是“刚刚异常”“重启后恢复”“某个时间点 CAN 掉了”，优先按历史故障复盘处理。
- 先固定故障时间，再回看对应时间段的 `mobile_base.launch`、`default.launch`、`dmesg` 和 bag。
- 不要只因为当前 `can0` 正常、当前 `lsusb -t` 正常，就排除历史 CAN / EB 链路异常。

## 常见检索词

- can 通信异常
- can bus 停止发布数据
- eb 通信异常
- reset embedded system
- cannot read eb
- cannot write eb
- pcan 异常
- ch341 异常
- 底层总线异常
- 重启后恢复

## 典型现象

- 机器人开机后看起来能进模式，但底层状态一直不稳定。
- 运动、电机、叉货动作或局部功能间歇失效。
- 伴随 USB 设备枚举异常、CAN 总线掉线、嵌入式重启或状态丢失。
- 日志里反复出现底层错误码，但上层 ROS 节点本身未必直接报死。

## 优先检查

1. 先看 `/low_level_error`、`/motor_control/low_level_status` 和最近的 `dmesg`。
2. 检查 `ip -s -d link show can0`，确认 CAN 接口是否频繁报错或重置。
3. 检查 `lsusb -t`，确认 PCAN、CH341、相机等 USB 设备是否稳定挂载。
4. 再看 `default.launch` 和 `mobile_base.launch` 中是否存在底层链路中断的时间点。

## 关键日志

- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`
- `~/log/permanent/lanyin.log`
- `dmesg -T` 输出
- `ip -s -d link show can0`
- `lsusb -t`

## 常见根因

- 电池 CAN 线接触不良或未连接。
- CAN 终端电阻、线缆或 PCAN 设备不稳定。
- 嵌入式控制板掉电、重启或通信超时。
- USB 总线受干扰，导致 CAN 或串口设备间歇离线。
- 底层恢复动作后没有真正恢复到稳定状态。

## 处理建议

1. 先判断是“单个设备异常”还是“CAN / 嵌入式链路整体异常”。
2. 如果 `can0` 报错明显，先排查线缆、终端电阻和 PCAN 设备。
3. 如果同时伴随 USB 设备波动，优先看 USB 总线和供电稳定性。
4. 如果日志指向嵌入式重启或掉电，先处理供电和硬件连接，再考虑软件恢复。
5. 恢复后再观察同一时段是否重复出现，避免把短暂恢复误判为根治。

## 参考文档

- [common-faults.md](common-faults.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [error-codes.md](error-codes.md)
