# 叉车型 + 托盘任务组合专项

## 适用范围
- 适用于 `forklift`、`ct_agv_04` 等叉车型执行托盘取放货任务时的组合问题。
- 用于把“机型差异”“托盘几何”“状态位链路”三者放在一起判断。

## 典型现象
- 同样是托盘任务，叉车型比其它机型更容易在最后阶段失败。
- 取货、抬叉、放货或退出动作中，某个状态位总是不满足。
- 某类托盘、某类库位或某类准备点组合总失败。

## 优先检查
1. 先确认问题是否只发生在叉车型托盘任务，而不是普通导航任务。
2. 检查 `fork_tip`、`fork_limit`、`fork_stage` 与现场动作是否一致。
3. 对照托盘规格、准备点、库位空间和机型参数，看是否存在组合边界问题。
4. 再判断是底层状态位、参数敏感性还是现场几何导致。

## 关键日志
- `/motor_control/low_level_status`
- 托盘任务 bag / caution
- `default.launch`
- `mobile_base.launch`
- 现场照片和托盘规格

## 常见检索词
- 叉车型托盘任务失败
- forklift 托盘问题
- 抬叉后任务不推进
- 托盘任务到最后失败
- 叉尖状态不对

## 判定口径
- 如果只在叉车型 + 托盘场景复现，更像组合专项问题。
- 如果脱离托盘场景也异常，更要回头看底盘或通用硬件问题。

## 常见根因
- 叉车型状态位与现场动作存在边界偏差。
- 托盘几何和准备点叠加放大了参数敏感性。
- 机型参数、底层状态与现场几何组合不鲁棒。

## 处理建议
1. 先按“机型 + 托盘 + 点位”三维组合复盘，不要分散看。
2. 如果状态位不稳，优先处理底层链路；如果状态位稳定，再调参数或几何。
3. 修复后至少在同托盘、同库位、同机型上连续复测。

## 参考文档
- [../hardware_bus/forklift-model-hardware-differences.md](../hardware_bus/forklift-model-hardware-differences.md)
- [pallet-handling-task-special-cases.md](pallet-handling-task-special-cases.md)
- [pallet-or-geometry-mismatch.md](pallet-or-geometry-mismatch.md)
