# TF 树不完整 / 时间跳变

## 适用范围
- ROS 中 TF 树缺失、坐标系不连通、时间跳变导致定位或导航行为异常。
- 适用于“TF 不完整”“jump back in time”“位置突然跳变”“导航控制异常”等问题。

## 典型现象
- `tf_monitor` 显示某些坐标系没有持续更新。
- 机器人位置、姿态或路径在地图中突然跳变。
- 日志中出现 `jump back in time`、`clearing TF` 等提示。
- 节点还在，但定位、导航或控制输出明显异常。

## 优先检查
1. 先确认 TF 树是否完整：`rosrun tf tf_monitor`。
2. 检查是否存在时间同步跳变、时间回退或消息时间戳异常。
3. 对照 `/amcl_pose`、`/odom`、`/tf` 的更新时间，判断是源数据异常还是 TF 广播异常。
4. 再看 `default.launch` 和时间同步相关日志，确认是否是 chrony 或系统时间问题。

## 关键日志
- `rosrun tf tf_monitor`
- `/tf`
- `/amcl_pose`
- `/odom`
- `~/log/not_permanent/<时间目录>/default.launch`
- `chronyc tracking`

## 常见检索词
- tf 不完整
- jump back in time
- tf 跳变
- 坐标系不连通
- clearing tf
- 时间跳变

## 判定口径
- 如果 TF 缺边或某一坐标系无更新，更像节点、广播或启动顺序问题。
- 如果 TF 整体跳变并伴随时间异常，更像系统时间跳变问题。

## 常见根因
- 关键 TF 广播节点未启动或异常退出。
- 时间同步发生大幅校正。
- 某一层定位或里程计源数据异常。
- 启动顺序导致部分节点在依赖未就绪时进入异常状态。

## 处理建议
1. 先确认是“树缺失”还是“时间跳变”。
2. 如果是时间跳变，优先检查 chrony 和系统时间策略。
3. 如果是 TF 缺失，锁定具体缺边节点并恢复其广播链路。
4. 修复后连续观察 TF 一段时间，确认不是瞬时恢复。

## 参考文档
- [README.md](README.md)
- [location-loss.md](location-loss.md)
- [map-loading-or-switch-failure.md](map-loading-or-switch-failure.md)
