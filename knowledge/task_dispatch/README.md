# 任务系统与动作场景入口

本目录用于承接 RCS 任务派发、任务状态推进、叉货取放货等动作场景问题。

## 适用范围

- 任务不派发、任务卡中间态、动作执行失败、场景步骤无法推进。
- 用户描述偏向“任务没下去”“取货失败”“叉不到位”“状态不动了”。

## 常见检索词

- 任务不派发
- 任务卡住
- 状态不动了
- 任务没下去
- 取货失败
- 放货失败
- 叉不到位
- 托盘不到位
- 场景步骤没推进
- 事件没触发

## 建议优先补充的子类页

1. 任务不派发 / 卡队列
2. 取货 / 放货 / 叉货场景异常
3. 任务状态机未推进
4. 事件触发条件不满足

## 当前已覆盖文档

- [rcs-task-system.md](rcs-task-system.md)
- [rcs-task-dispatch-failure.md](rcs-task-dispatch-failure.md)
- [fork-pickup-misalignment.md](fork-pickup-misalignment.md)
- [task-state-not-advancing.md](task-state-not-advancing.md)
- [event-condition-not-satisfied.md](event-condition-not-satisfied.md)
- [pallet-or-geometry-mismatch.md](pallet-or-geometry-mismatch.md)
- [history-case-task-sent-but-no-state-feedback.md](history-case-task-sent-but-no-state-feedback.md)
- [charging-task-special-cases.md](charging-task-special-cases.md)
- [pallet-handling-task-special-cases.md](pallet-handling-task-special-cases.md)
- [history-case-pallet-scene-geometry-causes-repeat-failure.md](history-case-pallet-scene-geometry-causes-repeat-failure.md)

## 推荐命名方式

- `task-*.md`
- `dispatch-*.md`
- `fork-*.md`
- `scenario-*.md`

## 关联总入口

- [../error-tracing-methods.md](../error-tracing-methods.md)
- [../log-paths.md](../log-paths.md)
- [../common-faults.md](../common-faults.md)
