# 主从链路 + Redis / HTTP / ROS 联合断点判断

## 适用范围
- 问题不是单个服务挂掉，而是主机到从机的任务、状态或规划链路在某一跳断开。
- 适用于要把 `Redis -> HTTP -> backend_fastapi -> ROS` 这条链逐跳断点排查的场景。

## 历史复盘优先

- 这类页面默认服务历史故障复盘，优先固定故障时间、重启时间、任务时间和对应日志目录。
- 不要直接拿当前状态替代历史证据，尤其不要让恢复后的状态覆盖首发异常。
- 应优先按时间线还原故障过程，再结合当前状态做补充验证。

## 典型现象
- 主机端任务存在，但从机 ROS 没有动作。
- 从机后端收到了请求，但主机侧状态不回流。
- Redis 频道有消息，但 HTTP / ROS 没继续，或者反过来。
- 某条链路只有部分环节有日志，其余环节无输出。

## 优先检查
1. 先明确问题方向：是“主机下发不到从机”，还是“从机执行了但回不到主机”。
2. 按顺序检查：
   - 主机业务服务
   - Redis 频道
   - HTTP / gRPC 调用
   - 从机 backend_fastapi
   - 从机 ROS topic / service
3. 每一跳都确认两件事：有没有请求进来、有没有结果出去。
4. 再将断点映射到对应服务、网络、认证或参数层。

## 关键日志
- 主机后端日志
- `task_running_server`、`map_server`
- Redis `global` 与 `{slave_id}` 频道观测
- 从机后端日志
- 从机 ROS topic / service 状态

## 常见检索词
- 主从链路断点
- redis 到 http 没下去
- http 到 ros 断了
- 任务发到从机但 ros 没动作
- 状态回流断了

## 判定口径
- 如果 Redis 前就没消息，更像主机业务层问题。
- 如果 Redis 有消息但 HTTP 没出去，更像桥接或服务调用问题。
- 如果 HTTP 到了但 ROS 没动作，更像从机后端到 ROS 的断点。
- 如果 ROS 执行了但主机无状态更新，更像回流链路断点。

## 常见根因
- Redis 发布 / 订阅链路中断。
- HTTP / gRPC 调用超时或目标不可达。
- 从机后端收到请求但未继续下发到 ROS。
- ROS 执行结果未正确回流到主机。

## 处理建议
1. 把链路拆成固定几跳逐一确认，不要笼统说“主从通信有问题”。
2. 断点一旦找到，就优先修复该跳，不要同时处理整条链。
3. 修复后复测“下发链”和“回流链”两边，确认闭环完整。

## 参考文档
- [backend/python-ros-call-chain-monitoring.md](backend/python-ros-call-chain-monitoring.md)
- [backend/http-or-grpc-call-chain-timeout.md](backend/http-or-grpc-call-chain-timeout.md)
- [backend/slave-backend-unreachable-from-master.md](backend/slave-backend-unreachable-from-master.md)
