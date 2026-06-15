# 硬件与总线层入口

本目录用于承接机器人硬件外设、USB、CAN、嵌入式板卡和物理链路稳定性问题。

## 适用范围

- 摄像头、雷达、PCAN、CH341、音响、USB 拓展坞等外设异常。
- CAN 通信中断、EB 板卡复位、总线数据停止发布。
- 用户描述偏向“设备掉了”“驱动断了”“总线不稳”“重连后恢复”。

## 常见检索词

- USB 掉线
- 摄像头离线
- 相机掉了
- pcan 异常
- ch341 异常
- can 通信异常
- eb 通信异常
- 设备反复重连
- 总线不稳
- 驱动断了

## 建议优先补充的子类页

1. USB 外设掉线 / 反复重连
2. CAN / EB 通信异常
3. 单个传感器供电异常
4. 拓展坞 / 线束 / 接插件接触不良

## 当前已覆盖文档

- [usb-device-troubleshooting.md](usb-device-troubleshooting.md)
- [can-eb-communication-abnormal.md](can-eb-communication-abnormal.md)
- [sensor-power-or-connector-instability.md](sensor-power-or-connector-instability.md)
- [usb-hub-or-dock-emi-instability.md](usb-hub-or-dock-emi-instability.md)
- [history-case-usb-can-cascade-failure.md](history-case-usb-can-cascade-failure.md)
- [forklift-model-hardware-differences.md](forklift-model-hardware-differences.md)
- [mecanum-model-differences.md](mecanum-model-differences.md)
- [ct_agv_04-or-forklift-parameter-sensitivity.md](ct_agv_04-or-forklift-parameter-sensitivity.md)

## 推荐命名方式

- `usb-*.md`
- `can-*.md`
- `sensor-*.md`
- `embedded-*.md`

## 关联总入口

- [../common-faults.md](../common-faults.md)
- [../error-codes.md](../error-codes.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
