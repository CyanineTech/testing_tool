# CPU 占用过高

## 适用范围
- 机器人控制器 CPU 持续偏高。
- RCS 主机或后端服务 CPU 偏高。
- 用户常见描述包括“CPU 占用过高”“卡顿”“很慢”“负载高”“进程吃满”。

## 典型现象
- 机器人响应变慢，但仍然在线。
- 导航、任务执行或日志刷新明显延迟。
- 后端服务偶发超时、页面卡顿或任务下发慢。

## 优先检查
1. 先确认目标到底是 AMR 控制器还是 RCS 主机。
2. 再看对应进程和系统负载是否持续升高。
3. 若伴随任务卡住或接口超时，再结合日志和时间点定位。

## 关键日志
- AMR：`/home/robot/log/permanent/`、`/home/robot/log/not_permanent/`、`/home/robot/log/start.log`
- RCS：后端日志、调度中心日志、任务执行日志
- 必要时补充对应时间点的 bag 或系统采样结果

## 常见根因
- 某个 ROS 节点或后端进程循环重试。
- 设备侧资源被摄像头、定位、任务队列或日志刷写占满。
- 外部依赖异常导致进程堆积、重连或重试放大。

## 处理建议
1. 先确认是单进程异常还是整体资源不足。
2. 再结合日志和时间窗口确认是哪个模块触发了高占用。
3. 如果已经影响任务执行，再按对应场景文档继续深挖。

## 参考文档
- [system-architecture.md](system-architecture.md)
- [common-faults.md](common-faults.md)
- [error-tracing-methods.md](error-tracing-methods.md)