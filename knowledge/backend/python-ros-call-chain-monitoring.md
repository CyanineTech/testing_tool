# Python / ROS 调用链与监控落点

## 适用范围

- RCS 主机任务下发、CBS 路径规划回流、从机 backend_fastapi 再下发到从机 ROS 的链路排查。
- 适用于要设计链路级监控、定位任务下发延迟、Redis 消息积压、gRPC / HTTP 调用失败、ROS topic 不新鲜等问题。
- 本页只记录已确认的代码事实和推荐观测点，不替代运行态抓包或联调验证。

## 已确认调用链

### 任务下发链

1. `task_running_server` 通过本机 gRPC `127.0.0.1:9993` 调 `map_server` 的 `MakeGoalService`。
2. `map_server` 使用 ROS Service Client 调 `/ecbs_srvs/ecbs_request` 下发目标位姿。
3. ROS 主机接收后，通过 HTTP `PATCH http://{slave_ip}/robots/way/point/` 转发到从机 `backend_fastapi`。
4. 从机 `backend_fastapi` 再通过本机 ROS gRPC `WayPointService` 继续下发。

### 轨迹 / 地图节点回流链

1. ROS 主机 topic `/ecbs_msgs/ecbs_result`、`/ecbs_msgs/map_nodes` 被 `map_server` 订阅。
2. `map_server` 将标准化后的轨迹 / 地图节点发布到 Redis `channel=global`。
3. `cbs_master_server` 的 `GlobalUpdaterSubscriber` 订阅 `global`，写入 `global_plan` / `global_map_nodes`。
4. `cbs_master_server` 再按从机粒度发布到 Redis `channel={slave_id}`，字段包括 `slave_path_plan`、`map_nodes`。
5. 从机 `backend_fastapi` 订阅自身频道，调用 `RobotPathPlanService` / `RobotMapNodesService`。
6. 从机 ROS 最终发布 `/ecbs_msgs/ecbs_result_agent`、`/ecbs_msgs/map_nodes_agent`。

## 关键协议与标识

- `task_running_server -> map_server`: gRPC `127.0.0.1:9993`
- `map_server -> ROS 主机`: ROS Service `/ecbs_srvs/ecbs_request`
- `ROS 主机 -> backend_fastapi`: HTTP `PATCH /robots/way/point/`
- `map_server -> cbs_master_server`: Redis Pub/Sub `channel=global`，代码侧主机 Redis 端口为 `16379`
- `cbs_master_server -> backend_fastapi`: Redis Pub/Sub `channel={slave_id}`
- `backend_fastapi -> 本机 ROS`: gRPC `RobotPathPlanService`、`RobotMapNodesService`
- `backend_fastapi -> 从机 ROS topic`: `/ecbs_msgs/ecbs_result_agent`、`/ecbs_msgs/map_nodes_agent`

## 优先检查

1. 先确认任务是卡在“任务没发出”还是“发出了但没落到从机 ROS”。
2. 检查 `MakeGoalService`、`/ecbs_srvs/ecbs_request`、`/robots/way/point/` 是否存在连续失败或超时。
3. 检查 Redis `global` 和 `slave_id` 频道是否持续有消息，以及发布到消费的时间差。
4. 检查 `/ecbs_msgs/ecbs_result`、`/ecbs_msgs/map_nodes`、`/ecbs_msgs/ecbs_result_agent`、`/ecbs_msgs/map_nodes_agent` 的新鲜度。
5. 检查 `CBSPlanPathSender`、`CBSMapNodesSender` 在主机和从机两侧是否都处于活跃状态。

## 建议监控项

### 可用性

- `MakeGoalService` 成功率
- `RobotPathPlanService` 成功率
- `RobotMapNodesService` 成功率
- `PATCH /robots/way/point/` HTTP 2xx 比率

### 延迟

- `MakeGoalService` P95 / P99 延迟
- `PATCH /robots/way/point/` P95 / P99 延迟
- Redis `global` 发布时间与 `cbs_master_server` 接收时间差
- Redis `{slave_id}` 发布时间与从机 `backend_fastapi` 接收时间差

### 新鲜度

- `/ecbs_msgs/ecbs_result` 最近消息时间
- `/ecbs_msgs/map_nodes` 最近消息时间
- `/ecbs_msgs/ecbs_result_agent` 最近消息时间
- `/ecbs_msgs/map_nodes_agent` 最近消息时间

### 错误率 / 积压

- gRPC 5 分钟失败率
- HTTP serial 过期拒绝比率
- Redis 频道无新消息持续时间
- `CBSPlanPathSender` / `CBSMapNodesSender` 活跃数或停摆状态

## 建议告警阈值

- 任一关键 gRPC 5 分钟失败率大于 `3%` 告警。
- `global` 或 `{slave_id}` 频道在任务执行中 `10 秒` 无新消息告警。
- `PATCH /robots/way/point/` 的 `P99 > 500ms` 且持续 `3 分钟` 告警。
- agent topic 在机器人导航中 `5 秒` 无更新告警。

## 关键日志与观测点

- `task_running_server/TaskManage/task_scheduling.py`
- `task_running_server/RobotCore/grpc_client/client.py`
- `map_server/Ros/GRPC/server/server.py`
- `map_server/Ros/RosOperate/service.py`
- `map_server/Ros/RosOperate/topic.py`
- `master_ros_server/server/ecbs.py`
- `cbs_master_server/CBS/defines.py`
- `cbs_master_server/CBS/plan.py`
- `backend_fastapi/RobotCore/single/views.py`
- `backend_fastapi/RobotCore/single/defines.py`
- `backend_fastapi/Ros/GRPC/server/server.py`
- `backend_fastapi/Ros/RosOperate/topic.py`
- Redis `global` 与 `{slave_id}` 频道观测
- ROS service 列表、ROS topic 新鲜度、从机 API 访问日志

## 待运行态确认项

- `map_server` 调用的是 `/ecbs_srvs/ecbs_request`，但 `master_ros_server` 当前 Python 代码注册的是 `/ecbs_srvs/tmp_goal`；要确认是否存在别名、桥接或另一处服务端实现。
- `/ecbs_srvs/goals_request` 当前只确认到 Python 服务实现，尚未在本仓 Python 代码中找到显式调用者。
- `19888` 在当前文档语境中是组目标设计意图对应的任务服务入口，不应再直接当成异常项。

## 最小联调核对动作

1. 列出 ROS Service，确认 `/ecbs_srvs/ecbs_request`、`/ecbs_srvs/goals_request` 是否在线。
2. 抓 Redis `global` 与 `{slave_id}` 频道，确认消息持续流动。
3. 查看从机 `/robots/way/point/` 访问日志，确认请求已收到且返回 success。
4. 查看 `/ecbs_msgs/ecbs_result_agent` 与 `/ecbs_msgs/map_nodes_agent` 是否实时更新。

## 使用约束

- 本页只能作为“已确认代码事实 + 监控设计输入”，不能把未确认调用方写成既成事实。
- 如果要基于本页再产出监控方案，必须把待运行态确认项单独列出。

## 参考文档

- [rcs-task-system.md](rcs-task-system.md)
- [system-architecture.md](system-architecture.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [service-timeout.md](service-timeout.md)
