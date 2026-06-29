# ROS 运行态入口

本目录用于承接机器人侧 ROS 节点、topic、定位、导航运行态问题。

## 适用范围

- 定位丢失、amcl 漂移、topic 不发布、节点异常退出。
- 用户描述偏向“定位没了”“节点不在了”“地图对不上”“ROS 没起来”。

默认处理方式：

1. 如果是历史 ROS 问题，优先固定故障时间和对应 `not_permanent` 目录。
2. 不要直接用当前 `rosnode list` / 当前 topic 状态替代历史故障证据。
3. 历史问题优先看对应时间段的 `default.launch`、`mobile_base.launch`、`state_monitor_wrapper.launch`、bag 和 caution。

## 历史复盘优先

- ROS 运行态问题如果已经恢复，优先固定故障时间和对应 `not_permanent` 日志目录。
- 不要直接用当前 `rosnode list`、当前 topic 或当前 pose 替代历史故障证据。
- 应优先回看对应时间段的 `default.launch`、`mobile_base.launch`、`state_monitor_wrapper.launch` 和 bag。

## 常见检索词

- 定位丢失
- 定位漂移
- 位置跳变
- 地图对不上
- ros 没起来
- 节点掉了
- topic 不发布
- 雷达 topic 不更新
- amcl 漂移
- 导航没法跑

## 建议优先补充的子类页

1. 定位丢失 / 定位跳变
2. 雷达 topic 不更新
3. 节点启动失败 / 反复拉起
4. 地图加载或切图异常

## 当前已覆盖文档

- [location-loss.md](location-loss.md)
- [topic-not-publishing.md](topic-not-publishing.md)
- [node-startup-failure.md](node-startup-failure.md)
- [map-loading-or-switch-failure.md](map-loading-or-switch-failure.md)
- [tf-tree-incomplete-or-jumping.md](tf-tree-incomplete-or-jumping.md)
- [history-case-time-jump-causes-motion-anomaly.md](history-case-time-jump-causes-motion-anomaly.md)
- [history-case-location-ok-but-map-or-tf-mismatch.md](history-case-location-ok-but-map-or-tf-mismatch.md)
- [history-case-scan-alive-but-localization-frozen.md](history-case-scan-alive-but-localization-frozen.md)
- [history-case-relocalize-recovers-but-tf-chain-still-suspect.md](history-case-relocalize-recovers-but-tf-chain-still-suspect.md)

## 推荐命名方式

- `location-*.md`
- `topic-*.md`
- `node-*.md`
- `mapping-*.md`

## 关联总入口

- [../common-faults.md](../common-faults.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
- [../log-paths.md](../log-paths.md)
