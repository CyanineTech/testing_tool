# 叉车型硬件差异与排障注意点

## 适用范围
- 适用于 `forklift` 机型及与叉货、升降、托盘作业强相关的硬件差异排查。
- 用于区分“通用 AMR 问题”和“叉车型特有链路 / 传感器 / 动作问题”。

## 典型现象
- 同样的任务或参数，在叉车型上更容易出现叉不到位、升降异常、托盘识别失败。
- 叉尖传感器、叉限位、低层状态位直接影响任务推进。
- 现场问题更依赖托盘、叉臂、升降姿态和货物几何条件。

## 优先检查
1. 先确认是否涉及叉货、放货、升降或托盘检测链路。
2. 检查 `/motor_control/low_level_status` 中 `fork_tip`、`fork_limit`、`fork_stage` 等状态。
3. 再结合托盘规格、现场几何和底层通信稳定性判断。

## 关键日志
- `/motor_control/low_level_status`
- `default.launch`
- `mobile_base.launch`
- 相关取放货 bag / caution

## 常见检索词
- 叉车型
- 叉尖传感器
- fork_tip
- fork_limit
- fork_stage
- 托盘识别失败

## 判定口径
- 如果问题只在叉货动作附近复现，更像叉车型专有链路或几何问题。
- 如果与叉货无关，更优先按通用 AMR 问题排。

## 常见根因
- 叉臂状态位不符合预期。
- 托盘与现场几何条件不匹配。
- 底层通信异常连带影响叉货链路。

## 处理建议
1. 先确认是否属于叉车型特有动作链路。
2. 如果属于，优先查底层状态位和托盘 / 现场几何，不要直接套通用导航问题模板。
3. 修复后至少复测同类叉货 / 放货场景。

## 参考文档
- [can-eb-communication-abnormal.md](can-eb-communication-abnormal.md)
- [../task_dispatch/fork-pickup-misalignment.md](../task_dispatch/fork-pickup-misalignment.md)
- [../task_dispatch/pallet-or-geometry-mismatch.md](../task_dispatch/pallet-or-geometry-mismatch.md)
