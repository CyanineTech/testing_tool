# 常见故障排查指南

## USB 设备故障

如果问题表现为摄像头离线、USB 设备反复重连、拓展坞 EMI 干扰、PCAN / CH341 一起波动，优先看 [USB 设备异常 / 摄像头离线](usb-device-troubleshooting.md)。

### USB 设备识别

supervisorctl status

# 检查后端日志
tail -100 /var/run/log/new_backend.log

# 检查 Docker 服务
docker ps
docker logs docker-redis_6_2-1 --tail 20
docker logs docker-mongo_5_0-1 --tail 20
```

### 常见后端问题

| 问题 | 检查方法 | 解决 |
|------|----------|------|
| 机器人掉线 | 检查 WebSocket 连接状态 | 检查网络/重启后端 |
| 任务不派发 | 检查调度中心日志 | 检查机器人状态/任务队列 |
| 地图加载失败 | 检查地图服务端口 4040 | 确认地图文件存在 |
| 充电失败 | 错误码 20100035 | 检查充电桩通信 |

### RCS 任务不派发

如果任务已创建但没有下发到机器人，优先看 [RCS 任务不派发 / 调度异常](rcs-task-dispatch-failure.md)。

重点关注：

- 主机后端、调度中心、数据库和队列是否都正常。
- 机器人是否在线、模式是否正确、前置条件是否满足。
- 某一类任务是否总失败，还是全局派发异常。
   cd <时间目录>/
   # 在 default.launch 日志中找时间前后的错误
   grep -i "camera\|realsense\|orbbec" default.launch
   ```

2. **查看内核 USB 日志**
   ```bash
   dmesg -T | grep -i "usb\|disconnect\|reset"
   ```

3. **检查是否同时有其他 USB 问题**
   ```bash
   # 检查 mobile_base.launch 中单片机/PCAN 状态
   grep -i "can\|serial\|ch341" <时间目录>/mobile_base.launch
   ```

### USB 软恢复

故障场景和对应修复命令：

- 摄像头离线：`rosservice call /usb_recovery/fix_cams`
- 驱动 / CAN bus 停止发布数据：`rosservice call /usb_recovery/fix_can`
- 嵌入式系统停止发送数据：`rosservice call /usb_recovery/fix_eb`
- 驱动 / CAN bus 停止发布数据 + 嵌入式系统停止发送数据：`rosservice call /usb_recovery/fix_can_eb`

如果 `fix_cams` 后又紧跟驱动 / CAN 异常，再考虑 `rosservice call /motor_control/force_driver_power_rst`；这些都是写操作，线上执行前要先确认影响范围。

## RCS 后端故障

### 服务状态检查
```bash
# 检查 supervisor 管理的服务
supervisorctl status

# 检查后端日志
tail -100 /var/run/log/new_backend.log

# 检查 Docker 服务
docker ps
docker logs docker-redis_6_2-1 --tail 20
docker logs docker-mongo_5_0-1 --tail 20
```

### 常见后端问题

| 问题 | 检查方法 | 解决 |
|------|----------|------|
| 机器人掉线 | 检查 WebSocket 连接状态 | 检查网络/重启后端 |
| 任务不派发 | 检查调度中心日志 | 检查机器人状态/任务队列 |
| 地图加载失败 | 检查地图服务端口 4040 | 确认地图文件存在 |
| 充电失败 | 错误码 20100035 | 检查充电桩通信 |

### RCS 任务不派发

如果任务已创建但没有下发到机器人，优先看 [RCS 任务不派发 / 调度异常](rcs-task-dispatch-failure.md)。

重点关注：

- 主机后端、调度中心、数据库和队列是否都正常。
- 机器人是否在线、模式是否正确、前置条件是否满足。
- 某一类任务是否总失败，还是全局派发异常。
| 错误日志 | 原因 | 解决方法 |
|----------|------|----------|
| `motor_control, curtis stops sending can data` | 电池CAN线未连接 | 检查电池CAN接线 |
| 电机驱动无法获取状态 (14/15) | CAN通信中断 | 检查CAN线缆/终端电阻 |
| 电机短路 (24/25) | 电机线短路 | 检查电机线缆 |
| 电机堵转 (28/29) | 机械卡死或负载过大 | 检查轮子是否被卡住 |
| 电机过载 (26/27) | 负载超过额定值 | 检查货物重量/路面情况 |

## 定位/导航故障

### 定位丢失
```bash
# 检查激光雷达数据
rostopic echo /scan -n1 | grep -c "ranges"

# 检查定位状态
rostopic echo /amcl_pose -n1

# 检查 TF 树完整性
rosrun tf tf_monitor
```

### 导航卡住/规划失败
```bash
# 检查代价地图
rostopic echo /move_base/status -n1

# 检查全局规划
rostopic echo /move_base/NavfnROS/plan -n1

# 查看 move_base 日志
rosnode info /move_base
```

### 取货时无法叉货到位

如果问题表现为取货、插叉或托盘对位时最后一段总是进不到位，优先看 [取货时无法叉货到位](fork-pickup-misalignment.md)。

重点关注：

- `/motor_control/low_level_status` 里的 `fork_tip`、`fork_limit`、`fork_stage`。
- 现场托盘规格、货物摆放偏位、托盘损坏情况。
- 取货准备点和插入参数是否与现场几何一致。
- 对应时间段的 bag、`default.launch` 和 `mobile_base.launch` 日志。

## 网络故障

### WiFi 断连
```bash
# 检查网络接口
ip addr show

# 检查 WiFi 连接
nmcli d wifi list
nmcli d show

# Ping RCS 主机
ping -c 3 <rcs_ip>
```

### Tailscale VPN
```bash
# 检查 Tailscale 状态
tailscale status

# 检查 DERP 连接
tailscale netcheck
```

### 1300D 路由器
```bash
# 检查 1300D 连通性
ping 192.168.127.254

# 检查端口转发（灯光控制器）
nc -zvu 192.168.127.254 1025
```

### 网络连通性异常

如果表现为 ping 不通、SSH 不通、WiFi / Tailscale 抖动或飞书远程取证失败，优先看 [网络连通性异常 / 设备连不上](network-connectivity-failure.md)。

重点关注：

- 目标 IP / 主机名是否正确。
- `ip addr show`、`ip route`、`nmcli d show`、`tailscale status` 的状态。
- 1300D 路由器、局域网网线和时间同步是否正常。

## 时间同步故障

### 诊断
```bash
# 检查 chrony 同步状态
chronyc sources
# 输出中 ^* 开头的行表示当前同步正常

# 检查时间偏差
chronyc tracking
```

### 修复
```bash
# 强制同步
sudo chronyc makestep

# 重启 chrony
sudo systemctl restart chrony
```

## RCS 后端故障

### 服务状态检查
```bash
# 检查 supervisor 管理的服务
### RCS 任务不派发

如果任务已创建但没有下发到机器人，优先看 [RCS 任务不派发 / 调度异常](rcs-task-dispatch-failure.md)。

重点关注：

- 主机后端、调度中心、数据库和队列是否都正常。
- 机器人是否在线、模式是否正确、前置条件是否满足。
- 某一类任务是否总失败，还是全局派发异常。
supervisorctl status

# 检查后端日志
tail -100 /var/run/log/new_backend.log

# 检查 Docker 服务
docker ps
docker logs docker-redis_6_2-1 --tail 20
docker logs docker-mongo_5_0-1 --tail 20
```

### 常见后端问题

| 问题 | 检查方法 | 解决 |
|------|----------|------|
| 机器人掉线 | 检查 WebSocket 连接状态 | 检查网络/重启后端 |
| 任务不派发 | 检查调度中心日志 | 检查机器人状态/任务队列 |
| 地图加载失败 | 检查地图服务端口 4040 | 确认地图文件存在 |
| 充电失败 | 错误码 20100035 | 检查充电桩通信 |

### RCS 任务不派发

如果任务已创建但没有下发到机器人，优先看 [RCS 任务不派发 / 调度异常](rcs-task-dispatch-failure.md)。

重点关注：

- 主机后端、调度中心、数据库和队列是否都正常。
- 机器人是否在线、模式是否正确、前置条件是否满足。
- 某一类任务是否总失败，还是全局派发异常。

## 智慧眼(库位识别)故障

### 服务检查
```bash
# 检查智慧眼服务容器
docker ps | grep cy_yolo
docker restart cy_yolo_test_crop_pallet_2

# 检查库位配置
cat ~/cy_storage_location_mon/stors.json

# 查看实时图像
ls ~/cy_storage_location_mon/imgs/
```

### 摄像头 RTSP 连接
```bash
# 测试 RTSP 流
ffprobe -rtsp_transport tcp "rtsp://admin:agv123456@<cam_ip>:554/stream2"
```

## 进入/退出模式故障

### 进模式失败
```bash
# 检查 node_supervisor 状态
rosservice call /cy_node_sv/launch_robot

# 检查日志
grep -i "error\|fail" ~/log/not_permanent/<最新目录>/default.launch | tail -20
```

### 退模式卡住
```bash
# 强制退出
rosservice call /cy_node_sv/stop_running_scenario

# 如果无响应，检查 rosmaster
rosnode list
```

## 开机故障判断（灯光）

| 灯光状态 | 含义 | 正常流程 |
|----------|------|----------|
| 绿呼吸 | 灯控上电默认 | 极短暂出现 |
| 黄长亮 | 系统已启动，等待进模式 | 正常待机 |
| 黄呼吸 | 正在进模式 | 持续数秒后变化 |
| 天蓝长亮 | 已在导航模式 | 正常工作 |
| 绿长亮 | 在执行任务中 | 正常工作 |
| 红闪 | 红色错误 | 需排查 |
| 紫长亮 | interrupt 状态 | 需排查 |
