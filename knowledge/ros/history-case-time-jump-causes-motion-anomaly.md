# 历史案例：时间跳变导致定位或运动异常

## 适用范围
- 机器人在没有明显新任务的情况下，位置、TF 或运动控制出现异常跳变。
- 适用于要把“时间同步问题”从普通定位问题中单独识别出来的复盘场景。

## 历史复盘优先

- ROS 运行态问题如果已经恢复，优先固定故障时间和对应 `not_permanent` 日志目录。
- 不要直接用当前 `rosnode list`、当前 topic 或当前 pose 替代历史故障证据。
- 应优先回看对应时间段的 `default.launch`、`mobile_base.launch`、`state_monitor_wrapper.launch` 和 bag。

## 典型现象
- 机器人在无明确任务切换时突然出现异常运动或位置跳变。
- 日志中出现 `jump back in time`、`clearing TF` 等提示。
- `/odom`、`/tf`、控制输出在短时间内出现不合理变化。

## 优先检查
1. 先确认问题发生时是否伴随系统时间大幅调整。
2. 检查 `chronyc tracking`、`default.launch`、控制相关日志，确认时间跳变是否与运动异常同一时刻出现。
3. 再判断是纯定位漂移，还是时间同步导致控制链路异常。

## 关键日志
- `chronyc tracking`
- `chronyc sources`
- `~/log/not_permanent/<时间目录>/default.launch`
- `/tf`
- `/odom`

## 常见检索词
- jump back in time
- clearing tf
- 时间跳变
- 没任务突然乱动
- 时间同步后异常

## 判定口径
- 如果时间跳变和运动异常严格同一时段，更像系统时间校正问题。
- 如果没有时间异常记录，更像定位、TF 或控制链路自身问题。

## 常见根因
- chrony 在运行中进行了大幅时间校正。
- 某些控制或 TF 组件对负时间差处理不稳。
- 时间同步策略过激，影响运行态链路。

## 处理建议
1. 先把它当成时间同步问题复盘，不要一开始就归因到导航参数。
2. 优先检查 chrony 策略和时间校正幅度。
3. 修复后在运行态下连续观察 TF、odom 和控制输出。

## 参考文档
- [tf-tree-incomplete-or-jumping.md](tf-tree-incomplete-or-jumping.md)
- [location-loss.md](location-loss.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
