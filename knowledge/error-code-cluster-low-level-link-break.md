# 错误码簇：底层链路中断类

## 适用范围
- 适用于一组都指向 USB / CAN / 嵌入式 / 底层状态链路中断的错误码复盘。
- 用于把多个表面不同的错误码归并到“底层链路断”这一类判断入口。

## 历史复盘优先

- 这类页面默认服务历史故障复盘，优先固定故障时间、重启时间、任务时间和对应日志目录。
- 不要直接拿当前状态替代历史证据，尤其不要让恢复后的状态覆盖首发异常。
- 应优先按时间线还原故障过程，再结合当前状态做补充验证。

## 典型现象
- 同一时间段出现多个不同错误码，但都伴随底层设备掉线、状态位异常或通信中断。
- 表面上看是多个故障，实际上根因可能是同一条底层链路。

## 优先检查
1. 先确认同一时段是否有 USB、CAN、EB、低层状态位异常同时出现。
2. 对照错误码时间、`default.launch`、`mobile_base.launch` 和 `dmesg -T`。
3. 判断错误码是否属于“首发错误”还是“后续扩散表现”。

## 关键日志
- `error_monitor_server.launch`
- `default.launch`
- `mobile_base.launch`
- `dmesg -T`
- `lsusb -t`
- `ip -s -d link show can0`

## 常见检索词
- 多个底层错误码一起报
- can 和 usb 一起异常
- 低层链路断了
- 底层状态全乱了

## 判定口径
- 如果多个错误码都集中在底层链路异常前后，更像同一根因扩散。
- 如果只有单一错误码且无链路异常，不一定归到底层链路簇。

## 常见根因
- USB 总线不稳
- CAN / EB 通信中断
- 公共供电、接插件或 Hub 问题
- 时间点前已有底层链路首发异常

## 处理建议
1. 不要逐个错误码分开修，优先先找共同链路。
2. 先恢复公共底层链路，再观察派生错误码是否自然消失。
3. 结论里注明“主错误 / 派生错误”。

## 参考文档
- [error-codes.md](error-codes.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [hardware_bus/can-eb-communication-abnormal.md](hardware_bus/can-eb-communication-abnormal.md)
