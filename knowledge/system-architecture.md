# 系统架构

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    RCS 主机 (192.168.1.170)                   │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐     │
│  │ Master    │ │Dispatch  │ │  CBS    │ │  Charging  │     │
│  │ Backend   │ │ Center   │ │ Master  │ │  Server    │     │
│  │ :18888    │ │ :9998    │ │ :9995   │ │  :4096     │     │
│  └───────────┘ └──────────┘ └─────────┘ └────────────┘     │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐     │
│  │ Map       │ │ Transfer │ │TaskRun  │ │ Location   │     │
│  │ Server    │ │ Server   │ │ Server  │ │ Manage     │     │
│  │ :4040     │ │ :6888    │ │ :1993   │ │ :1024      │     │
│  └───────────┘ └──────────┘ └─────────┘ └────────────┘     │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐     │
│  │ Auth      │ │ User     │ │Log/Bkup │ │ SmartEyes  │     │
│  │ Center    │ │ Backend  │ │ Server  │ │ Server     │     │
│  │ :3434     │ │ :3072    │ │ :4041   │ │ :1028      │     │
│  └───────────┘ └──────────┘ └─────────┘ └────────────┘     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   Docker: MySQL:13306 / Redis:16379 / Mongo:17017    │   │
│  │   OpenResty: 80(HTTP) / 9990(WebSocket) / 8880 /9992 │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   ROS Master :11311 + master_ros_server + roslaunch  │   │
│  └──────────────────────────────────────────────────────┘   │
└───────┬─────────────────────────────────────────────────────┘
        │ WiFi / Tailscale VPN
        ▼
┌─────────────────────────────────────────────────────────────┐
│                  AMR 机器人 (Ubuntu 20.04)                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │    ROS Noetic (via cyanine-os.service → cyanine-os.sh)│   │
│  │  ┌────────────┐ ┌─────────────┐ ┌────────────────┐  │   │
│  │  │configurati-│ │motor_control│ │ obstacle_      │  │   │
│  │  │on_node(mgr)│ │(CAN/电机)   │ │ detector       │  │   │
│  │  └────────────┘ └─────────────┘ └────────────────┘  │   │
│  │  ┌────────────┐ ┌─────────────┐ ┌────────────────┐  │   │
│  │  │state_con-  │ │  amcl/neo_  │ │move_base/TEB/  │  │   │
│  │  │ structor   │ │localization │ │ DWB            │  │   │
│  │  └────────────┘ └─────────────┘ └────────────────┘  │   │
│  │  ┌────────────┐ ┌─────────────┐ ┌────────────────┐  │   │
│  │  │websocket_  │ │move_manager │ │ pull_drop/     │  │   │
│  │  │bridge      │ │(任务执行)   │ │ pallet_event   │  │   │
│  │  └────────────┘ └─────────────┘ └────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────────┐      │
│  │Slave     │ │ error_manage │ │  Docker容器         │      │
│  │Backend   │ │ _server      │ │(MySQL/Redis/Mongo/  │      │
│  │ :3737    │ │(supervisor)  │ │ OpenResty/YOLO)     │      │
│  └──────────┘ └──────────────┘ └────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

## 网络拓扑

### AMR 内部网络
- **主机 (ROS Master)**: 192.168.127.1 (ROS_MASTER_URI=http://192.168.127.1:11311)
- **1300D 路由器**: 192.168.127.254（提供 WiFi、串口转发 UDP:1025、摄像头管理）
- **前雷达**: 10.10.10.101:2368
- **后雷达**: 10.10.11.101:2368
- **Livox MID360**: 192.168.1.134 (NEO内网)

### 现场网络
- **RCS 主机**: 通常在客户内网（如 10.3.8.47）
- **AMR 连接 RCS**: 通过 1300D 的 WAN 口或 WiFi 接入客户网络
- **远程访问**: Tailscale VPN + 自建 DERP 服务器（阿里云）

### 远程连接方式
```bash
# 直接SSH（需在同一网络）
ssh robot@<amr-hostname>

# 通过Tailscale
ssh robot@<tailscale-hostname>

# SSH端口转发（访问AMR内部网络）
ssh -L 80:192.168.127.1:80 robot@<amr-hostname>

# SSH跳板
ssh robot@<target-ip> -J robot@<jump-host>

# GOST端口代理
gost -L tcp://:31422/172.19.15.41:22
```

## AMR 机型列表
| 机型 | 说明 | 配置路径 |
|------|------|----------|
| ct_agv_01 | CT01 | base/ct_agv_01/ |
| ct_agv_02 | CT02/CT05 背负式 | base/ct_agv_02/ |
| ct_agv_04 | CT04 叉车 | base/ct_agv_04/ |
| ct_agv_05 | CT05 | base/ct_agv_05/ |
| ct_tri | 三轮车 | base/ct_tri/ |
| forklift | 叉车(当前250使用) | base/forklift/ |
| mecanum | 麦克纳姆轮 | base/mecanum/ |
| mecanum_small | 小型麦轮 | base/mecanum_small/ |
| dingze | 鼎泽定制 | base/dingze/ |
| mihai_agv | 米海定制 | base/mihai_agv/ |
| xgd_agv | 小个大定制 | base/xgd_agv/ |
| sb_agv_sim | 仿真 | base/sb_agv_sim/ |

## ROS 环境配置

### 启动流程
1. systemd user service `cyanine-os.service` 调用 `/opt/cyanine-tech/bin/cyanine-os.sh`
2. 脚本读取 `~/static/config/robot_source.yaml` 加载 ROS 环境
3. 脚本读取 `~/static/config/robot_option.yaml` 导出 CT_* 环境变量
4. 调用 `configuration_node/scripts/start_up_cyanine_os.py` 启动节点管理

### ROS Source 链 (生产模式 source_mode: opt)
```
/opt/ros/noetic/setup.bash
→ /opt/cyanine-tech/cartographer/setup.bash
→ /opt/cyanine-tech/cyanine-os/setup.bash
```

### 关键环境变量 (robot_option.yaml)
| 变量 | 说明 | 典型值 |
|------|------|--------|
| CT_SIM | 是否仿真 | false |
| CT_DEV | 开发模式 | false |
| CT_PRODUCTION | 生产模式 | false |
| CT_BASE_VERSION | 底盘版本 | 2 |
| CT_PERCEPTION_SENSOR | 感知雷达 | pavo20 |
| CT_DRIVER_VENDOR | 驱动品牌 | helishi |
| CT_LOCALIZATION | 定位算法 | amcl |
| CT_PLANNER | 规划器 | TEB |
| CT_IS_MASTER | 是否主机 | true |
| CT_WIRE | 有线连接 | true |
| CT_ROSCANOPEN | CANopen协议 | false |
| CT_SCENARIO | 场景编号 | 2 |
| CT_ECBS_MASTER | ECBS主控 | false |
| CT_ECBS_MODE | ECBS模式 | false |
| CT_RGB_DETECT | RGB检测 | false |
| CT_FORK_CAM_DETECT | 叉尖摄像头 | false |
| CT_2_FORK_CAM | 双叉尖摄像头 | false |
| CT_2_FORK_UP_CAM | 双侧面摄像头 | false |

### 主要 ROS 包（160+个已安装）

核心导航:
`amcl`, `neo_localization`, `move_base`, `move_manager`, `teb_local_planner`, `dwa_local_planner`, `global_planner`, `dlux_global_planner`, `waypoint_global_planner`, `nav_core_adapter`

运动控制:
`motor_control`, `swerve_steering_controller`, `tricycle_controller`, `diff_drive_controller_with_imu`, `mobile_base`

状态/安全:
`state_constructor` (→state_monitor_msg), `error_monitor`, `health_guard_core`, `obstacle_detector`, `ct_3d_obstacle_mem`

感知传感器:
`realsense2_camera`, `orbbec_camera`, `pavo2s_ros`, `livox_ros_driver2`, `ira_laser_tools`, `pointcloud_filter_nodelet`

取放货/事件:
`pull_drop`, `pallet_event`, `charge_event`, `align_event`, `custom_event`, `action_monitor`, `event_core`

建图:
`cartographer_tools`, `multimap_server`, `map_tools`

通信:
`websocket_bridge`, `convert_message_to_web`, `cy_cbs`, `peer_motion_bridge`

工具:
`usb_recovery_tool`, `cy_tfadjust` (→cy_router), `camera_pose_calibration`, `system_diagnostics`

## ROS 节点职责

### node_supervisor (核心管理)
- 管理模式切换（闲置/建图/导航）
- 启动/停止 ROS launch 文件
- 提供 ROS Service 接口给后端调用

### motor_control (运动控制)
- CAN 通信（PCAN USB）控制电机驱动器
- 里程计计算
- 差速/全向/三轮运动学
- 源码: `motor_control/src/motor_control.cpp`

### state_constructor (状态采集)
- 与单片机（STM32，通过 CH341 USB转串口）通信
- 采集 IMU、急停、碰撞条、货物检测、叉臂状态
- 发布 `/low_level_error` 错误码

### obstacle_detector (避障)
- 深度相机障碍物检测
- 激光雷达障碍物检测
- 托盘深度检测（叉尖开关量）

### amcl / neo_localization (定位)
- 激光雷达 AMCL 定位
- 地图匹配定位

### move_base (导航)
- 全局路径规划
- 局部路径规划（DWB/TEB）
- 代价地图管理

## Docker 容器

### AMR 端 & RCS 端 (共用同一 docker-compose)
配置文件: `/docker_data/docker/docker-compose.yaml`

| 容器名 | 镜像 | 端口映射 | 功能 |
|--------|------|----------|------|
| docker-mysql_5_7-1 | mysql:5.7 | 13306→3306 | MySQL数据库 |
| docker-redis_6_2-1 | redis:6.2 | 16379→6379 | Redis缓存/消息 |
| docker-mongo_5_0-1 | mongo:5.0 | 17017→27017 | MongoDB |
| docker-openresty_1_21_4_1-6-1 | openresty/openresty:1.21.4.1-6-bullseye-fat | 80,8880,9990,9992 | 反向代理/WebSocket |

MySQL 凭据: root密码 `wudier**//`, 数据库 `lanyin`, 用户 `lanyin`/`lanyinrobot`

Docker 数据目录: `/docker_data/docker/`

### AMR 端额外容器（视配置）
| 容器名 | 镜像 | 功能 |
|--------|------|------|
| cy_yolo_human_detect | stigliew/cy_pose | YOLO 人体检测 |
| cy_yolo_crop_pallet2 | stigliew/cy_pose | YOLO 取货托盘识别 |

## 服务管理

### AMR 端
```bash
# ROS 导航服务（systemd user service, cyanine-os.sh启动）
systemctl --user status cyanine-os.service
systemctl --user stop cyanine-os.service
systemctl --user start cyanine-os.service
journalctl --user -u cyanine-os.service -f

# 后端服务通过 supervisor 管理 (配置: ~/static/*.ini)
supervisorctl status
supervisorctl restart error_manage_server

# Docker 服务 (systemd)
sudo systemctl status docker-compose.service
sudo systemctl restart docker-compose.service
```

Supervisor 从机进程组 (intra-company):
- `error_manage_server` → ~/error_manage_server/error_manage.py

### RCS 主机端
```bash
# supervisor 管理后端服务 (配置: ~/static/master.ini, ~/static/smart_eyes.ini)
supervisorctl status
supervisorctl restart <program>
supervisorctl restart all

# Docker 服务
sudo systemctl restart docker-compose.service
```

Supervisor 主机进程组 (master):
| 进程名 | 目录 | 入口 | 端口 |
|--------|------|------|------|
| master_backend | backend_fastapi_master | master_manage.py | 18888 |
| authentication_server | authentication_center | authentication_manage.py | 3434 |
| dispatch_server | dispatch_center | dispatch_manage.py (sleep 10) | 9998 |
| map_server | map_server | map_manage.py | 4040 |
| transfer_server | transfer_server | transfer_manage.py | 6888 |
| task_running_server | task_running_server | task_running_manage.py (sleep 11) | 1993 |
| master_ros_rpc | map_server/Ros | MasterRosMain.py | - |
| location_management_server | location_management_server | location_manage.py | 1024 |
| charging_server | charging_server | charging_manage.py | 4096 |
| user_backend | user_backend | user_manage.py | 3072 |
| log_server | data_manage_server | log_manage.py | 4041 |
| backup_server | data_manage_server | backup_manage.py | - |
| master_ros_server | master_ros_server | main.py | - |
| cbs_master_server | cbs_master_server | cbs_master.py | - |

Supervisor 进程组 (smart_eyes):
| 进程名 | 目录 | 入口 |
|--------|------|------|
| smart_eyes_server | smart_eyes_server | wisdom_manage.py |
| smart_task_server | location_management_server | smart_manage.py |
