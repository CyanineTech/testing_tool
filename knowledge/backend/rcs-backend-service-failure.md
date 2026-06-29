# RCS 后端服务异常

## 适用范围

- RCS 主机上的后端、调度、数据库或容器服务异常。
- 常见于服务没起来、端口不可用、任务和消息链路异常、Docker 容器失联等场景。

## 典型现象

- 后端看起来在线，但任务、地图或消息接口不工作。
- 容器、supervisor 或 systemd 管理的服务有停止、重启或异常退出。
- 任务派发、机器人心跳或地图加载出现异常，但问题不一定完全在机器人侧。
- 日志里能看到服务报错、端口拒绝或依赖服务不可用。

## 历史复盘优先

- 如果主机已经重启、服务后来恢复，优先回看重启前或故障发生时的历史日志。
- 先固定重启时间、故障时间或上一个 `boot`，再查 `supervisor`、`backend`、`docker`、`kernel`。
- 不要直接拿当前 `docker ps`、当前端口状态当成历史主机故障根因。

## 优先检查

1. 历史问题先看重启前或故障时间对应的 `supervisor`、`backend`、`docker`、`kernel` 日志。
2. 再看主机服务是否还活着：supervisor、Docker、数据库、调度中心。
3. 检查关键端口和服务日志，确认不是单个服务停了。
4. 再看机器人在线状态和任务链路，判断是不是后端链路把任务卡住了。
5. 如果是容器类服务，确认容器是否反复重启或健康检查失败。

## 关键日志

- `supervisorctl status`
- `docker ps`
- `docker logs ... --tail 20`
- `~/backend_log/` 或主机后端日志目录
- `dispatch_center` 相关日志
- `journalctl -u supervisor -b -1`
- `journalctl -u docker -b -1`
- `journalctl -k -b -1`


## 常见检索词

- 后端服务异常
- 3737 不通
- supervisor 异常
- 主机服务挂了
- 重启后恢复

## 常见根因

- 后端主服务未正常启动。
- 调度中心或数据库连接异常。
- 任务链路中的某个依赖服务停掉了。
- 容器健康检查失败或反复重启。
- 配置变更后没有重新加载，导致服务状态和配置不一致。

## 处理建议

1. 历史问题先固定故障时间，不要直接引用当前状态。
2. 先把服务状态分层看清楚，不要只盯一个容器。
3. 如果是基础服务停掉，先恢复基础链路，再看业务层。
4. 如果是任务或地图接口异常，继续查调度中心和数据库依赖。
5. 如果只是局部端口不可用，重点看对应日志和配置。
6. 修复后再检查任务是否能连续下发和执行。

## 参考文档

- [rcs-task-dispatch-failure.md](rcs-task-dispatch-failure.md)
- [rcs-task-system.md](rcs-task-system.md)
- [error-tracing-methods.md](error-tracing-methods.md)
