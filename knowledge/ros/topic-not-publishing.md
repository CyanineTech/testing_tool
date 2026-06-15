# ROS Topic 不发布 / 无数据

## 适用范围
- 机器人某个关键 topic 没数据、长时间不更新或偶发中断。
- 适用于 `/scan`、`/low_level_error`、`/amcl_pose`、`/move_base/status` 等关键 topic 异常。

## 典型现象
- `rostopic echo` 一直等不到消息。
- 节点看起来还在，但 topic 没有更新。
- 上层逻辑表现为定位不动、状态不刷新或动作不推进。
- 某个 topic 只在开机初期有数据，之后断更。

## 优先检查
1. 先确认 topic 对应节点是否还在运行：`rosnode list`。
2. 检查 `rostopic hz <topic>`、`rostopic info <topic>`，确认是否真的无人发布。
3. 如果 topic 属于传感器链路，再看 USB / CAN / 驱动侧是否异常。
4. 再结合 `default.launch`、`mobile_base.launch` 和对应时间段 bag 判断是节点异常还是输入源异常。

## 关键日志
- `rosnode list`
- `rostopic info <topic>`
- `rostopic hz <topic>`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`

## 常见检索词
- topic 不发布
- topic 没数据
- rostopic 没消息
- 状态不刷新
- topic 断更
- 节点在但没输出

## 判定口径
- 如果节点不在，更像节点启动失败或异常退出。
- 如果节点还在但 topic 没数据，更像输入源丢失、内部卡死或发布逻辑异常。

## 常见根因
- 对应 ROS 节点异常退出。
- 传感器输入源掉线，节点失去上游数据。
- topic 发布线程卡住或状态机未推进。
- TF、参数或初始化顺序问题导致节点不真正开始工作。

## 处理建议
1. 先区分是“节点没了”还是“节点还在但没发消息”。
2. 如果是传感器类 topic，优先排底层链路，不要先调上层参数。
3. 如果是业务状态 topic，再检查状态机、触发条件和调用链。
4. 修复后用 `rostopic hz` 连续观察一段时间，确认不是短暂恢复。

## 参考文档
- [README.md](README.md)
- [location-loss.md](location-loss.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
