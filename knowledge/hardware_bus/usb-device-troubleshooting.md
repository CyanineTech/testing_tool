# USB 设备异常 / 摄像头离线

## 适用范围

- AMR 运行中出现摄像头离线、USB 设备反复重连、PCAN 或 CH341 异常。
- 适用于 D415 / D435、DCW2、RGB 充电摄像头、PCAN、单片机串口转 USB、音响和外部拓展坞相关问题。
- 重点用于区分“单个摄像头掉线”与“USB 总线 / 拓展坞 / CAN 链路整体不稳定”。

## 典型现象

- 相机节点离线、图像中断或进模式后某一路摄像头不工作。
- `lsusb -t` 中设备层级变化、设备消失或驱动异常。
- 日志中出现 `uvcvideo`、USB reset、disconnect、reconnect 等内核信息。
- 摄像头离线后又伴随 `CAN bus 停止发布数据`、嵌入式停止发送数据或 PCAN 频繁重连。
- 外部拓展坞挂载多个奥比设备时，某一路设备恢复不上来。

## 设备识别规则

1. 优先看 `lsusb -t` 的层级结构，不要只看 Bus / Port 编号；不同机器人编号可能不同，但层级结构通常一致。
2. 奥比 DCW2 常见特征是同一 port 下存在 3 个 `480M` 子设备。
3. Intel D415 / D435 常见特征是同一 port 下有 5 个以上 `5000M` 子设备。
4. CH341 常表现为 `Driver=ch341`、`12M`。
5. PCAN 常表现为 `Driver=peak_usb`、`12M`。
6. 奥比设备内部自带逻辑拓展坞，深度和 RGB 会作为其下级设备出现；2.0 设备也可能都挂在同一个 root hub 下。

## 优先检查

1. 先执行 `lsusb -t`，按层级结构、Class、Driver 和速率识别掉的是哪类设备。
2. 进入对应时间的 `~/log/not_permanent/<时间目录>/`，在 `default.launch` 中查摄像头相关日志。
3. 用 `dmesg -T | grep -i "usb\|disconnect\|reset\|uvcvideo"` 看本次开机内核 USB 异常；历史开机用 `sudo journalctl -o short-precise -k -b -1`。
4. 如果摄像头异常同时伴随底层问题，再查 `mobile_base.launch` 中单片机、PCAN、串口或 CAN 相关报错。
5. 若现场出现 USB-CAN 一直重连、无 buffer，再补看 `ip -s -d link show can0`。

## 关键日志

- `lsusb -t`
- `dmesg -T`
- `sudo journalctl -o short-precise -k -b -1`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`
- `ip -s -d link show can0`
- `~/autobag/caution_*.bag.zip` 及对应前后摄像头图片

## 常见根因

- `uvcvideo` 或 USB 总线异常导致摄像头掉线后无法自动恢复。
- 外部拓展坞 EMI 干扰，导致整条 USB 链路不稳定。
- 同一拓展坞挂载超过 2 个奥比设备，恢复时可能有一路起不来。
- 摄像头离线后继续连带影响 PCAN、CH341 或嵌入式通信，表现为 USB / CAN 复合故障。
- 音响或其他 USB 外设异常占用 / 卡死，拖垮整条总线。

## 处理建议

1. 先判断故障是否只影响单个摄像头，还是同一条 USB / 拓展坞下的多个设备一起波动。
2. 如果日志里同时出现摄像头掉线和 CAN / 嵌入式异常，优先按总线级问题处理，不要只盯相机节点。
3. 可按症状选择恢复动作：
   - `rosservice call /usb_recovery/fix_can`
   - `rosservice call /usb_recovery/fix_eb`
   - `rosservice call /usb_recovery/fix_can_eb`
   - `rosservice call /usb_recovery/fix_cams`
4. 如果 `fix_cams` 后紧跟着出现驱动 / CAN 停止发布数据，优先 `rosservice call /motor_control/force_driver_power_rst`；再不行才考虑按急停断驱动电、释放急停并等待约 10 秒。
5. 如果摄像头、CAN、嵌入式三者同时异常，优先按整链路恢复，不要分别零散处理。
6. 上述恢复动作属于写操作，线上排障前要先确认影响范围。

## 历史疑难线索

- USB 音箱异常可能导致整体重启 / 卡死。
- `uvcvideo` 异常可能导致设备掉线后无法自动回来。
- 拓展坞 EMI 问题会表现为多类 USB 设备一起波动。
- 若拓展坞上接入超过 2 个奥比设备，可能有一路恢复失败。
- USB-CAN 一直重连且没有 buffer 时，通常需要结合 `can0` 统计进一步定位。

## 参考文档

- [common-faults.md](common-faults.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [can-eb-communication-abnormal.md](can-eb-communication-abnormal.md)
- [log-paths.md](log-paths.md)
