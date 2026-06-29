# 历史案例：重定位后恢复，但 TF 链仍然可疑

## 适用范围

- 现场通过重定位后问题暂时恢复，但怀疑根因并不只是“需要重新定位”。
- 适用于“重定位能救回来，但链路里还有更深问题”的历史 ROS 复盘。

## 典型现象

- 机器人原本导航异常、姿态不对或位置不动，重定位后暂时恢复。
- 同类问题在一段时间后重复出现，不是一次性误操作。
- 表面看像“定位丢了”，但复盘时发现 TF、切图或时间链路也可疑。

## 历史复盘优先

- 先查重定位前的异常时间段，再看重定位后的恢复表现。
- 不要只因为“重定位后好了”就直接把根因归结为普通定位漂移。
- 先核对 `default.launch`、`/tf`、切图流程和定位链路的前后差异。

## 优先检查

1. 先确认重定位前的异常表现到底是 pose 漂移、冻结还是 map / TF 错位。
2. 检查重定位前后 `/tf`、`/amcl_pose`、地图关系和相关日志是否出现明显变化。
3. 判断重定位只是恢复手段，还是掩盖了更底层的 TF / 切图 / 时间问题。
4. 如果问题可复现，优先比较“异常前后”和“重定位后”的链路差异。

## 关键日志

- `~/log/not_permanent/<时间目录>/default.launch`
- `~/log/not_permanent/<时间目录>/state_monitor_wrapper.launch`
- `/tf`
- `/amcl_pose`
- 地图服务 / 切图相关日志

## 常见检索词

- 重定位后恢复
- relocalize 后好了
- 重新定位能好一会
- tf 还是不对
- map 对不上但重定位后暂时正常

## 判定口径

- 如果重定位后只短暂恢复，更像底层 TF / map / 时间链路仍有问题。
- 如果每次都靠重定位恢复，说明“重定位”更可能是绕过症状而不是根治。

## 常见根因

- TF 链局部异常，重定位只是在重新对齐表象。
- 切图 / 地图关系刷新不完整。
- 时间同步抖动导致定位链路偶发异常。
- 定位节点状态长期不稳定，重定位只是临时清状态。

## 处理建议

1. 先查重定位前的异常链路，不要只记录“重定位后恢复”。
2. 把重定位当作恢复动作，不要直接当作根因结论。
3. 修复后要验证“无需重定位也能稳定运行”。

## 参考文档

- [history-case-location-ok-but-map-or-tf-mismatch.md](history-case-location-ok-but-map-or-tf-mismatch.md)
- [history-case-scan-alive-but-localization-frozen.md](history-case-scan-alive-but-localization-frozen.md)
- [tf-tree-incomplete-or-jumping.md](tf-tree-incomplete-or-jumping.md)

