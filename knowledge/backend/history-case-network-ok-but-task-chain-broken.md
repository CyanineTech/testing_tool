# 历史案例：网络正常但任务链路已断

## 适用范围
- 主从机之间基本可 ping、可 SSH，但任务派发、回执或规划链路仍然失败。
- 适用于“表面网络没问题，但业务链路就是断”的历史问题。

## 典型现象
- `ping`、`ssh` 都正常，但任务不下发或状态不回流。
- 飞书或前端看到的不是掉线，而是任务链路中断。
- 现场误以为网络没问题，最后发现是业务消息链路断点。

## 优先检查
1. 先确认基础网络可达，不再停留在网络层排查。
2. 再检查主机到从机后端、Redis 频道、HTTP / gRPC 链路是否有真实业务流量。
3. 判断断在任务派发、从机接收、ROS 下发还是状态回流。

## 关键日志
- 主机后端日志
- 从机后端日志
- `task_running_server`、`map_server`
- Redis / HTTP / gRPC 调用记录

## 常见检索词
- 网络正常但任务不走
- ping 通但是不派发
- ssh 正常但任务链断了
- 链路断点

## 判定口径
- 如果基础网络一直正常，但业务链路没流量，更像任务链路断点问题。
- 如果连基础连接都不稳，还是应先回到网络层。

## 常见根因
- 业务调用链某一跳无请求或无回执。
- 中间件消息流断掉。
- 主从配置、任务状态或路由指向错误对象。

## 处理建议
1. 先确认基础连通性，再逐跳查任务链路。
2. 重点找“有请求没回执”或“根本没发出去”的断点。
3. 修复后用同类任务复测完整链路。

## 参考文档
- [history-case-master-service-healthy-but-call-chain-broken.md](history-case-master-service-healthy-but-call-chain-broken.md)
- [http-or-grpc-call-chain-timeout.md](http-or-grpc-call-chain-timeout.md)
- [slave-backend-unreachable-from-master.md](slave-backend-unreachable-from-master.md)
