# 历史案例：主机服务都在，但调用链已断

## 适用范围
- 主机上后端、调度、端口看起来都在线，但任务、路径或状态链路实际无法走通。
- 适用于“服务健康检查看似正常，但业务就是不工作”的复盘场景。

## 典型现象
- 端口在、进程在，但任务不推进或调用无结果。
- 某一跳 HTTP / gRPC / Redis 回流中断后，整体业务停住。
- 表面上不是“服务挂了”，而是“链路断了”。

## 优先检查
1. 不要停留在 `systemctl` / `docker ps` 层，继续按调用链逐跳核对。
2. 对照 `python-ros-call-chain-monitoring.md` 中链路，确认每一跳是否真的有入有出。
3. 检查调用发起端、调用接收端、Redis 回流和从机侧 ROS 更新。

## 关键日志
- 主机后端日志
- `task_running_server`、`map_server`、`backend_fastapi` 日志
- Redis 频道流量观测
- 从机 ROS topic 更新情况

## 常见检索词
- 服务都在但不工作
- 端口正常但任务不走
- 健康正常但链路断了
- 主机服务没挂但调用失败

## 判定口径
- 如果端口健康但业务链路无输出，更像调用链断点问题。
- 如果端口都不在，更像基础服务状态问题。

## 常见根因
- 中间一跳调用超时或未真正返回。
- Redis 回流断掉，导致后续状态不更新。
- 从机侧接收到了请求，但未继续下发到 ROS。

## 处理建议
1. 先逐跳找断点，不要被“服务在线”误导。
2. 对每一跳都要确认“请求到了”和“结果回来了”。
3. 修复后用同一条业务链完整复测。

## 参考文档
- [http-or-grpc-call-chain-timeout.md](http-or-grpc-call-chain-timeout.md)
- [python-ros-call-chain-monitoring.md](python-ros-call-chain-monitoring.md)
- [slave-backend-unreachable-from-master.md](slave-backend-unreachable-from-master.md)
