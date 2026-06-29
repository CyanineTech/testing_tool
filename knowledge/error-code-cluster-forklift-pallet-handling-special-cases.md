# 错误码簇 + 叉车型托盘任务专项

## 适用范围
- 适用于叉车型在托盘取放货任务中出现的一组相关错误码和动作失败现象。
- 用于把“错误码、机型、托盘任务”放在一起做专项归因。

## 历史复盘优先

- 这类页面默认服务历史故障复盘，优先固定故障时间、重启时间、任务时间和对应日志目录。
- 不要直接拿当前状态替代历史证据，尤其不要让恢复后的状态覆盖首发异常。
- 应优先按时间线还原故障过程，再结合当前状态做补充验证。

## 典型现象
- 错误码几乎只在叉车型托盘任务里出现。
- 同一类错误码伴随 `fork_tip`、`fork_limit`、`fork_stage` 异常。
- 同样错误码在普通导航任务里很少出现。

## 优先检查
1. 先确认错误码是否出现在托盘任务阶段，而不是普通导航阶段。
2. 检查低层状态位与现场动作是否一致。
3. 对照托盘规格、准备点、点位和叉车型参数，判断是否为组合边界问题。
4. 再区分是错误码首发、底层链路首发，还是几何条件首发。

## 关键日志
- `/motor_control/low_level_status`
- 托盘任务 bag / caution
- `default.launch`
- `mobile_base.launch`
- 错误码登记日志

## 常见检索词
- 叉车托盘错误码
- forklift 取货报错
- 托盘任务报码
- 叉尖状态错误
- 抬叉报码

## 判定口径
- 如果错误码与托盘动作和状态位高度同步，更像叉车型托盘专项问题。
- 如果错误码先于托盘动作异常出现，更要回头查底层链路。

## 常见根因
- 叉车型状态位与现场动作不一致。
- 托盘几何、参数边界和机型差异共同放大问题。
- 底层链路波动在托盘任务阶段被放大成明显错误码。

## 处理建议
1. 不要只看错误码文本，要联合机型和任务类型判断。
2. 先确认“动作阶段 - 状态位 - 错误码”三者是否同一时间线。
3. 修复后要在同机型、同托盘任务上复测。

## 参考文档
- [error-code-cluster-pallet-handling-failures.md](error-code-cluster-pallet-handling-failures.md)
- [task_dispatch/forklift-pallet-task-combined-special-cases.md](task_dispatch/forklift-pallet-task-combined-special-cases.md)
- [hardware_bus/forklift-model-hardware-differences.md](hardware_bus/forklift-model-hardware-differences.md)
