# 任务系统与动作场景入口

本目录用于承接 RCS 任务派发、任务状态推进、叉货取放货等动作场景问题。

## 适用范围

- 任务不派发、任务卡中间态、动作执行失败、场景步骤无法推进。
- 用户描述偏向“任务没下去”“取货失败”“叉不到位”“状态不动了”。

默认处理方式：

1. 如果问题已经过去，优先回看任务发生时的状态流、后端日志、调度日志和对应错误时间。
2. 不要直接用当前任务队列或当前机器人在线状态替代历史任务故障证据。
3. 历史任务问题优先看任务创建、下发、回执、状态推进的时间线。

## 历史复盘优先

- 任务问题优先围绕任务创建、卡住、恢复和人工干预的时间线复盘。
- 不要只因为任务最终完成或当前机器人在线，就忽略最初卡住时的真实断点。
- 应优先回看主机任务流、从机动作、事件回执和现场条件变化。

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
- [history-case-manual-recovery-hides-task-root-cause.md](history-case-manual-recovery-hides-task-root-cause.md)
- [history-case-retry-succeeds-but-first-failure-matters.md](history-case-retry-succeeds-but-first-failure-matters.md)
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
