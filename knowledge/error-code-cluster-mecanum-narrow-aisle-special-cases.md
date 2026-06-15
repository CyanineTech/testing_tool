# 错误码簇 + 麦轮窄通道任务专项

## 适用范围
- 适用于麦轮机型在窄通道、贴边、会车、让路等任务中反复出现的一组错误码和导航异常。
- 用于把“错误码、机型、路线场景”三者联合起来判断。

## 典型现象
- 错误码总在窄通道、贴边或会车区域附近出现。
- 麦轮机型在该区域比其它机型更容易报码或重规划。
- 同样错误码在宽阔区域不容易复现。

## 优先检查
1. 先确认错误码是否与窄通道、让路或局部绕行任务强相关。
2. 检查路线图节点、障碍距离、避让点与局部规划输出。
3. 对照麦轮机型差异页，判断是否为机型运动学在窄通道被放大。
4. 再区分是定位、图设计、局部规划还是机型边界问题。

## 关键日志
- 路线图配置
- `/odom`
- `/cmd_vel`
- 路径规划相关 topic
- 问题时间点 bag / caution

## 常见检索词
- 麦轮窄路报码
- 麦轮会车报错
- 贴边报码
- 窄通道导航错误码
- mecanum 狭窄区域异常

## 判定口径
- 如果错误码只在窄通道区域复现，更像麦轮窄通道专项问题。
- 如果全场景都报码，更像通用定位、底盘或传感器问题。

## 常见根因
- 麦轮姿态 / 横移在窄通道区域鲁棒性不足。
- 路线图留边、间距、避让配置不适合麦轮。
- 局部规划在狭窄空间更容易触发异常。

## 处理建议
1. 先把问题缩小到具体路线区域和机型。
2. 联合看错误码、路线图和局部规划，而不是只看单个报错。
3. 修改后在同一通道做单机、会车和贴边三类复测。

## 参考文档
- [error-code-cluster-location-navigation-failures.md](error-code-cluster-location-navigation-failures.md)
- [task_dispatch/mecanum-narrow-aisle-task-special-cases.md](task_dispatch/mecanum-narrow-aisle-task-special-cases.md)
- [hardware_bus/mecanum-model-differences.md](hardware_bus/mecanum-model-differences.md)
