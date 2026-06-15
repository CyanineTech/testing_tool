# Redis / 中间件依赖异常

## 适用范围
- RCS 主机后端、调度中心、CBS 或任务链路依赖的 Redis、MongoDB、MySQL、中转服务异常。
- 适用于“服务本身在，但链路不通、消息不流、队列不走”的场景。

## 典型现象
- 后端端口在线，但任务状态不推进或消息不回流。
- 某个服务日志报连接 Redis、MongoDB、MySQL 失败。
- 调度、路径规划、状态同步链路出现间歇性卡死。
- Docker 容器健康状态异常或反复重启。

## 优先检查
1. 先确认 Redis、MongoDB、MySQL 等依赖容器是否存活：`docker ps`。
2. 检查对应端口和容器日志，确认是否存在连接拒绝、认证失败或资源不足。
3. 如果是任务链路问题，再结合 Redis channel 和调用链日志确认消息是否中断。
4. 再区分是依赖自身故障，还是上层服务配置、网络或认证问题。

## 关键日志
- `docker ps`
- `docker logs docker-redis_6_2-1 --tail 50`
- `docker logs docker-mongo_5_0-1 --tail 50`
- `docker logs docker-mysql_5_7-1 --tail 50`
- 主机后端、调度中心和 CBS 相关日志

## 常见检索词
- redis 连接失败
- 中间件异常
- mysql 连接失败
- mongo 连接失败
- 队列不走
- 消息不回流

## 判定口径
- 如果依赖容器本身异常，更像基础中间件问题。
- 如果依赖正常但上层报错，更像配置、网络、认证或调用逻辑问题。

## 常见根因
- Redis / MongoDB / MySQL 容器异常退出。
- 容器端口占用、磁盘满或资源不足。
- 服务配置指向错误实例或认证信息不对。
- 上层服务连通性异常，导致依赖不可达。

## 处理建议
1. 先确认依赖本身是否活着，再看业务服务日志。
2. 如果中间件异常，优先恢复基础依赖，再追业务链路。
3. 如果依赖正常但消息不流，继续查调用链和频道消费状态。
4. 修复后验证任务派发、路径规划和状态同步是否都恢复。

## 参考文档
- [README.md](README.md)
- [service-timeout.md](service-timeout.md)
- [python-ros-call-chain-monitoring.md](python-ros-call-chain-monitoring.md)
