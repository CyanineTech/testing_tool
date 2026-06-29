# 常见故障总入口

这页不是单独的完整 SOP，而是飞书排障和知识检索的总入口。

## 适用范围

- 适用于需要先判断故障属于哪一层、历史问题该从哪里开始查的总入口场景。
- 用户描述偏向“先帮我分层”“这类问题先看哪里”“历史故障怎么开始复盘”。

默认前提：

1. 大多数问题都是故障发生后再回头复盘。
2. 应先固定故障时间、重启时间、任务时间和对应日志目录。
3. 当前系统状态只能作为补充，不能直接替代历史证据。

## 历史复盘优先

遇到下面这些表述，默认先走历史故障排查，而不是直接看当前状态：

- 刚刚掉线
- 刚才任务没下去
- 今天下午 3 点左右异常
- 6 月 15 日 15 点前后卡住
- 重启后恢复
- 之前报错现在好了，但想查根因

优先动作：

1. 先确定故障大概时间窗口。
2. 再找对应 `boot`、日志目录、任务时间线。
3. 再按业务层去查历史证据。
4. 最后才用当前状态做补充校验。

## 常见检索词

- 掉线
- 任务不派发
- 任务卡住
- 服务不通
- 接口超时
- 定位丢失
- 地图切换失败
- WiFi 漫游
- ssh 不通
- USB 掉设备
- CAN 异常
- 重启后恢复

## 先判断属于哪一层

### 1. 硬件 / 总线 / 外设层

常见表现：

- 摄像头离线
- USB 设备反复重连
- PCAN / CH341 波动
- 传感器信号突然没了
- 单片机 / 驱动板通信异常

优先入口：

- [hardware_bus/README.md](hardware_bus/README.md)
- [hardware_bus/usb-device-troubleshooting.md](hardware_bus/usb-device-troubleshooting.md)
- [hardware_bus/can-eb-communication-abnormal.md](hardware_bus/can-eb-communication-abnormal.md)
- [hardware_bus/sensor-power-or-connector-instability.md](hardware_bus/sensor-power-or-connector-instability.md)

### 2. ROS 运行态层

常见表现：

- 定位丢失
- topic 不发布
- 节点没起来
- TF 跳变
- 地图加载失败

优先入口：

- [ros/README.md](ros/README.md)
- [ros/location-loss.md](ros/location-loss.md)
- [ros/topic-not-publishing.md](ros/topic-not-publishing.md)
- [ros/node-startup-failure.md](ros/node-startup-failure.md)
- [ros/map-loading-or-switch-failure.md](ros/map-loading-or-switch-failure.md)

### 3. 网络与连通性层

常见表现：

- AMR 掉线
- ping 不通
- ssh 不通
- WiFi 漫游
- 路由器链路不稳

优先入口：

- [network/README.md](network/README.md)
- [network/network-connectivity-failure.md](network/network-connectivity-failure.md)
- [network/wifi-roaming-instability.md](network/wifi-roaming-instability.md)
- [network/ssh-authentication-failure.md](network/ssh-authentication-failure.md)

### 4. 后端与调用链层

常见表现：

- RCS 后端不通
- 端口不监听
- 接口超时
- 服务拉起失败
- 主从调用链断了

优先入口：

- [backend/README.md](backend/README.md)
- [backend/rcs-backend-service-failure.md](backend/rcs-backend-service-failure.md)
- [backend/service-timeout.md](backend/service-timeout.md)
- [backend/http-or-grpc-call-chain-timeout.md](backend/http-or-grpc-call-chain-timeout.md)
- [backend/history-case-rcs-host-reboot-recovers-but-backend-chain-broken.md](backend/history-case-rcs-host-reboot-recovers-but-backend-chain-broken.md)

### 5. 任务系统与动作场景层

常见表现：

- 任务不派发
- 任务卡中间态
- 叉不到位
- 放货失败
- 事件条件不满足

优先入口：

- [task_dispatch/README.md](task_dispatch/README.md)
- [task_dispatch/rcs-task-dispatch-failure.md](task_dispatch/rcs-task-dispatch-failure.md)
- [task_dispatch/task-state-not-advancing.md](task_dispatch/task-state-not-advancing.md)
- [task_dispatch/fork-pickup-misalignment.md](task_dispatch/fork-pickup-misalignment.md)
- [task_dispatch/pallet-or-geometry-mismatch.md](task_dispatch/pallet-or-geometry-mismatch.md)

### 6. CBS / 路线规划层

常见表现：

- 会车冲突
- 路线绕圈
- 节点设计不合理
- 避让策略异常

优先入口：

- [cbs/README.md](cbs/README.md)
- [cbs/navigation-route-rules.md](cbs/navigation-route-rules.md)
- [cbs/multi-robot-deadlock-or-yield-conflict.md](cbs/multi-robot-deadlock-or-yield-conflict.md)
- [cbs/node-spacing-or-route-loop-design-problem.md](cbs/node-spacing-or-route-loop-design-problem.md)

## 高频历史证据入口

### 主机 / 机器人日志目录

- [log-paths.md](log-paths.md)
- [error-tracing-methods.md](error-tracing-methods.md)

补充经验：

1. `~/log/not_permanent/<开机时间目录>/default.launch`
   可用于看传感器信号监控日志，通常能查到是谁的信号没了。
2. `~/log/permanent/<开机时间目录>/error_monitor_server.launch`
   可用于看错误码登记、触发时间、解除时间和附带 `info`。
3. 这类日期目录通常按开机时间生成，下次开机后才会再生成新的目录。

### 错误码 / 场景联合入口

- [error-codes.md](error-codes.md)
- [error-code-scene-bag-joint-analysis.md](error-code-scene-bag-joint-analysis.md)
- [error-code-cluster-low-level-link-break.md](error-code-cluster-low-level-link-break.md)
- [error-code-cluster-task-chain-timeout.md](error-code-cluster-task-chain-timeout.md)

## 推荐排查顺序

1. 先问清故障时间，是“当前故障”还是“历史故障复盘”。
2. 先进入对应业务层目录 `README.md`。
3. 优先找最贴近症状的具体页，不要只停留在总入口。
4. 如果已有明确错误码、任务名、机型、现场特征，再继续跳到专题页。
5. 输出结论时必须区分：
   - 已确认的历史证据
   - 当前状态补充信息
   - 仍待验证的推测

## 关联总入口

- [README.md](README.md)
- [system-architecture.md](system-architecture.md)
- [log-paths.md](log-paths.md)
- [error-tracing-methods.md](error-tracing-methods.md)
