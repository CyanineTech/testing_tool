# 错误码簇：任务链路超时类

## 适用范围
- 适用于一组都表现为任务、服务、回执或状态推进超时的错误码与异常现象。
- 用于快速判断问题更像主从调用链、任务状态机还是后端服务慢。

## 典型现象
- 错误码出现时，任务状态长时间不动，接口和回执明显变慢。
- 用户描述通常是“任务卡住”“服务不通”“一直等结果”。

## 优先检查
1. 先确认任务是否已派发、是否有现场动作、是否有状态回流。
2. 对照调用链日志和错误码时间点，确认超时发生在哪一跳。
3. 判断是主机业务层、主从链路还是从机执行回流阶段超时。

## 关键日志
- 主机后端日志
- `task_running_server`
- 从机后端日志
- Redis / HTTP / gRPC 调用记录
- 任务状态时间线

## 常见检索词
- 任务超时
- 接口超时
- 一直等结果
- 状态回不来
- 调用链超时

## 判定口径
- 如果任务没派发，先看业务层和前置条件。
- 如果任务已发但没回执，更像任务链路超时簇问题。

## 常见根因
- HTTP / gRPC 某一跳慢或断。
- Redis / 中间件消息流堵塞。
- 从机执行完成但状态未回流。
- 上层任务状态机等待超时。

## 处理建议
1. 错误码只作为入口，真正判断要靠任务链时间线。
2. 逐跳确认“请求是否发出”“结果是否回来”。
3. 修复后复测同类任务全链路。

## 参考文档
- [error-codes.md](error-codes.md)
- [master-slave-redis-http-ros-joint-breakpoint-analysis.md](master-slave-redis-http-ros-joint-breakpoint-analysis.md)
- [backend/http-or-grpc-call-chain-timeout.md](backend/http-or-grpc-call-chain-timeout.md)
