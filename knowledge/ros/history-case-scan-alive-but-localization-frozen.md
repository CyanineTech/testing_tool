# 历史案例：雷达数据还在，但定位长时间冻结

## 适用范围

- `/scan` 仍有数据，但机器人位置长时间不更新，或定位值像“卡住了一样”。
- 适用于“不是纯雷达掉线，而是定位链路局部冻结”的历史复盘。

## 典型现象

- 雷达 topic 看起来正常，但地图上的位置不动或更新极慢。
- 机器人现场在移动，`/amcl_pose` 或定位结果却几乎不变化。
- 重定位、切图或节点短暂重启后会暂时恢复。

## 历史复盘优先

- 优先固定定位冻结开始的时间，而不是只看当前 `/scan` 和当前 pose。
- 先核对冻结前后 `default.launch`、`state_monitor_wrapper.launch`、TF 和定位节点日志。
- 不要因为雷达当前有数据，就排除当时定位链路局部卡死。

## 优先检查

1. 先确认冻结时机器人是否真实在移动。
2. 再确认 `/scan` 是否连续更新，而不是只看单次输出。
3. 检查 `/amcl_pose`、`/tf` 和定位节点日志是否在同一时段停止推进或异常跳变。
4. 判断是定位算法冻结、TF 关系卡住，还是地图 / 切图后链路未完全刷新。

## 关键日志

- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/state_monitor_wrapper.launch`
- `/scan`
- `/amcl_pose`
- `/tf`
- 对应时间段 bag

## 常见检索词

- 雷达有数据但定位不动
- scan 正常但 amcl 不更新
- 定位冻结
- 地图上位置卡住
- 移动了但 pose 不变

## 判定口径

- 如果 `/scan` 连续更新但定位值长时间不变，更像定位链路冻结而不是纯雷达掉线。
- 如果 `/scan` 也同时异常，则更像感知输入本身中断。

## 常见根因

- 定位节点内部状态卡住或未正常推进。
- TF 链局部冻结，导致定位结果无法正确更新。
- 切图或重定位后某一层关系未刷新。
- 时间同步抖动间接影响定位更新链路。

## 处理建议

1. 先把它与“雷达掉线”区分开，不要直接回到纯 USB / 雷达思路。
2. 先查定位节点、TF 和切图时序，再查感知输入。
3. 修复后要验证“移动中定位持续更新”，不能只验证静态时有 pose。

## 参考文档

- [location-loss.md](location-loss.md)
- [history-case-location-ok-but-map-or-tf-mismatch.md](history-case-location-ok-but-map-or-tf-mismatch.md)
- [tf-tree-incomplete-or-jumping.md](tf-tree-incomplete-or-jumping.md)

