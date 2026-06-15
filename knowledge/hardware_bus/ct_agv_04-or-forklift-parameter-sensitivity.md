# CT_AGV_04 / Forklift 参数敏感问题

## 适用范围
- 适用于 `ct_agv_04`、`forklift` 这类叉车型在取放货、贴边、定位或动作切换中对参数更敏感的场景。
- 用于识别“不是硬件坏了，而是参数边界过紧或现场几何放大了参数问题”。

## 典型现象
- 相同任务在大多数时候正常，但在某些库位、某些托盘或某些姿态下频繁失败。
- 稍微调整准备点、插入距离、速度或姿态后成功率明显变化。
- 现场看起来像硬件问题，但更像参数边界不够鲁棒。

## 优先检查
1. 先确认问题是否集中在取货、放货、贴边、升降或狭窄空间动作上。
2. 对照现场几何、托盘规格和任务点位，看是否存在“只差一点”的边界问题。
3. 检查相关参数是否过于保守或过于激进。
4. 再区分是纯参数敏感，还是底层状态位、传感器和通信链路异常共同作用。

## 关键日志
- `default.launch`
- `mobile_base.launch`
- `/motor_control/low_level_status`
- 现场照片、bag、任务时间点

## 常见检索词
- 参数太敏感
- 调一点就好了
- 某些库位总失败
- 同任务有时行有时不行
- 准备点差一点
- 插入距离不合适

## 判定口径
- 如果微调参数后成功率显著变化，更像参数敏感问题。
- 如果调参无明显影响，更要回头查传感器、底层链路和现场几何。

## 常见根因
- 插入距离、准备点、速度或姿态参数处在边界值。
- 叉车型现场几何差异放大了参数敏感性。
- 参数问题与托盘规格、现场空间、底层状态共同叠加。

## 处理建议
1. 先确认是否为边界参数问题，而不是直接大范围调参。
2. 一次只改最小范围参数，并保留现场对照。
3. 调整后必须在失败场景复测，而不是只在简单场景验证。

## 参考文档
- [forklift-model-hardware-differences.md](forklift-model-hardware-differences.md)
- [../task_dispatch/fork-pickup-misalignment.md](../task_dispatch/fork-pickup-misalignment.md)
- [../task_dispatch/pallet-or-geometry-mismatch.md](../task_dispatch/pallet-or-geometry-mismatch.md)
