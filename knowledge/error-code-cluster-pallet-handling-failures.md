# 错误码簇：托盘处理失败类

## 适用范围
- 适用于一组都与托盘识别、进叉、抬叉、放货、退出托盘场景相关的错误码与异常现象。
- 用于把“托盘任务失败”从一般任务异常中单独聚类。

## 典型现象
- 错误码总伴随托盘相关动作失败出现。
- 某些错误码表面不同，但本质都指向托盘几何、状态位或动作链路问题。
- bag、现场照片和错误码需要一起看才容易下结论。

## 优先检查
1. 先确认错误码出现时任务是否正在执行托盘相关步骤。
2. 检查 `fork_tip`、`fork_limit`、`fork_stage`、托盘识别结果和现场几何条件。
3. 再判断是托盘专项动作失败、状态位不一致，还是底层链路先异常。

## 关键日志
- 托盘任务 bag / caution
- `/motor_control/low_level_status`
- `default.launch`
- `mobile_base.launch`
- 现场照片

## 常见检索词
- 托盘错误码
- 取货错误码
- 放货错误码
- 叉货错误
- 托盘识别失败报码

## 判定口径
- 如果错误码和托盘动作失败高度同步，更像托盘处理失败簇。
- 如果托盘动作前已有底层链路异常，更可能是托盘错误码只是后续表现。

## 常见根因
- 托盘几何不匹配。
- 叉尖 / 限位状态异常。
- 托盘识别链路不稳定。
- 参数边界或事件条件未满足。

## 处理建议
1. 错误码先归簇，再结合现场几何和状态位判断。
2. 优先区分“托盘专项根因”和“底层链路带出来的托盘报错”。
3. 复测时要保留同托盘、同库位、同动作阶段条件。

## 参考文档
- [error-codes.md](error-codes.md)
- [task_dispatch/pallet-handling-task-special-cases.md](task_dispatch/pallet-handling-task-special-cases.md)
- [task_dispatch/pallet-or-geometry-mismatch.md](task_dispatch/pallet-or-geometry-mismatch.md)
