# 定位丢失

## 适用范围

- AMR 在导航或定位过程中出现定位飘移、丢失、重定位失败或地图坐标不稳定。
- 常见于激光雷达数据异常、TF 树不完整、AMCL 状态不正常或现场环境变化后。

## 典型现象

- 机器人明明在现场，但地图上的位置漂移很大。
- 到点后无法稳定停在目标位置。
- 重定位后很快又漂移，或者定位状态短时间内变差。
- 轨迹看起来能走，但 pose 一直不稳定。

## 历史复盘优先

- 如果定位问题发生在过去，优先固定故障时间和对应 `not_permanent` 目录，而不是直接看当前 `/scan` 和 `/amcl_pose`。
- 当前定位已经恢复时，历史 bag、`default.launch`、`mobile_base.launch` 和 `state_monitor_wrapper.launch` 更有价值。
- 如果用户描述里带“刚刚”“刚才”“今天”“某个时刻”，优先按对应时间窗口复盘定位链路。

## 优先检查

1. 历史问题先固定故障时间窗口和对应日志目录。
2. 先看 `/scan` 是否有稳定数据，确认激光雷达没有掉线。
3. 检查 `/amcl_pose` 和 TF 树是否完整。
4. 核对地图是否匹配当前现场，环境是否有大改动。
5. 再结合对应时间段的 bag 和导航日志判断是传感器问题还是地图 / 参数问题。

## 关键日志

- `rostopic echo /scan -n1`
- `rostopic echo /amcl_pose -n1`
- `rosrun tf tf_monitor`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`
- `~/log/not_permanent/<时间目录>/state_monitor_wrapper.launch`
- `~/autobag/` 中的对应 bag


## 常见检索词

- 定位丢失
- 位置漂移
- map 对不上
- 刚刚定位异常
- 重定位

## 常见根因

- 激光雷达数据不稳定或间歇掉线。
- TF 树缺失、坐标系配置异常。
- 地图与现场不匹配，或者现场发生了明显变化。
- AMCL、定位参数或扫描数据质量不足。
- 底层 CAN / USB 异常间接影响传感器链路。

## 处理建议

1. 历史问题优先还原故障时间窗口里的传感器和 TF 状态。
2. 如果雷达掉线，先排底层链路而不是直接调定位参数。
3. 如果传感器正常，再看地图、坐标系和 AMCL 参数。
4. 如果是现场变化导致，先评估是否需要更新地图或重建区域。
5. 修复后再连续跑几次定位和导航，确认不会反复漂移。

## 参考文档

- [common-faults.md](common-faults.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [navigation-route-rules.md](navigation-route-rules.md)
