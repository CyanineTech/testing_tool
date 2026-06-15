# 后端与调用链入口

本目录用于承接 RCS 主机后端、服务超时、接口异常和主从机调用链问题。

## 适用范围

- FastAPI 服务异常、端口不通、gRPC / HTTP / Redis / topic 链路异常。
- 用户描述偏向“接口超时”“服务挂了”“后端不通”“调用失败”。

## 常见检索词

- 接口超时
- 服务超时
- 服务不通
- 后端不通
- 调用失败
- 端口不通

## 建议优先补充的子类页

1. 服务超时 / 端口不通
2. 后端服务拉起失败
3. 主从机调用链断点
4. Redis / 数据库 / 中间件依赖异常

## 当前已覆盖文档

- [service-timeout.md](service-timeout.md)
- [rcs-backend-service-failure.md](rcs-backend-service-failure.md)
- [python-ros-call-chain-monitoring.md](python-ros-call-chain-monitoring.md)
- [redis-or-middleware-dependency-failure.md](redis-or-middleware-dependency-failure.md)
- [http-or-grpc-call-chain-timeout.md](http-or-grpc-call-chain-timeout.md)
- [slave-backend-unreachable-from-master.md](slave-backend-unreachable-from-master.md)
- [history-case-master-service-healthy-but-call-chain-broken.md](history-case-master-service-healthy-but-call-chain-broken.md)
- [history-case-network-ok-but-task-chain-broken.md](history-case-network-ok-but-task-chain-broken.md)

## 推荐命名方式

- `service-*.md`
- `backend-*.md`
- `call-chain-*.md`
- `redis-*.md`

## 关联总入口

- [../system-architecture.md](../system-architecture.md)
- [../error-tracing-methods.md](../error-tracing-methods.md)
- [../log-paths.md](../log-paths.md)
