# ROS 节点启动失败 / 反复拉起

## 适用范围
- 某个关键 ROS 节点启动失败、反复重启、在 `rosnode list` 中缺失或频繁僵尸化。
- 适用于导航、定位、感知、底盘控制和业务动作节点异常。

## 历史复盘优先

- ROS 运行态问题如果已经恢复，优先固定故障时间和对应 `not_permanent` 日志目录。
- 不要直接用当前 `rosnode list`、当前 topic 或当前 pose 替代历史故障证据。
- 应优先回看对应时间段的 `default.launch`、`mobile_base.launch`、`state_monitor_wrapper.launch` 和 bag。

## 典型现象
- 机器人进模式后功能不完整，某些节点始终起不来。
- `rosnode list` 缺少关键节点，或节点短时间反复出现又消失。
- `rt_node_info` 中有 `notRunningNodeList` 或 `zombieNodeList`。
- 上层表现为能进模式但某一能力完全不可用。

## 优先检查
1. 先列出节点：`rosnode list`，确认缺的是哪个节点。
2. 如果节点有 supervisor 或模式管理参与，确认是否被反复拉起失败。
3. 检查 `default.launch`、`mobile_base.launch` 中该节点的启动报错。
4. 再判断是依赖缺失、参数异常、硬件输入源异常还是进程自身崩溃。

## 关键日志
- `rosnode list`
- `rostopic echo /gw_<robot_id>/rt_node_info`
- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/mobile_base.launch`
- `~/log/permanent/lanyin.log`

## 常见检索词
- 节点启动失败
- 节点起不来
- 节点反复重启
- zombie node
- notRunningNodeList
- rosnode 缺失

## 判定口径
- 如果节点从未出现，更像启动条件、参数或依赖缺失。
- 如果节点出现后很快消失，更像进程崩溃、输入源异常或状态守护拉起失败。

## 常见根因
- launch 参数错误或依赖资源缺失。
- 上游硬件输入异常，导致节点初始化失败。
- 模式切换时启动顺序不对。
- 进程运行中崩溃，进入反复拉起状态。

## 处理建议
1. 先锁定具体节点，不要只看宏观现象。
2. 再结合启动日志确认失败发生在初始化、运行中还是退出重拉阶段。
3. 如果依赖传感器或底层输入，优先把输入源恢复稳定。
4. 修复后再次进模式并复查 `rosnode list` 和 `rt_node_info`。

## 参考文档
- [README.md](README.md)
- [topic-not-publishing.md](topic-not-publishing.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
