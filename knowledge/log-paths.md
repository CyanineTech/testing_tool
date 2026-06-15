# 日志路径与格式

## AMR 端日志

### 路径总览

| 路径 | 类型 | 说明 |
|------|------|------|
| `/home/robot/log/permanent/` | 持久 | 不自动删除 |
| `/home/robot/log/backend_log/error_manage_server.log` | 持久 | 后端错误管理日志 |
| `/home/robot/log/env.log` | 持久 | 环境变量/启动日志 |
| `/home/robot/log/not_permanent/<日期-时间>/` | 临时 | 每次进模式创建一个目录 |
| `/home/robot/autobag/` | 滚动 | 自动录包（7200分钟后自动删除） |
| `/var/run/log/new_backend.log` | 持久 | supervisor 后端启动日志 |
| `/var/run/log/celery.log` | 持久 | celery 任务日志 |

### 进模式日志目录结构

每次进入导航模式，会在 `/home/robot/log/not_permanent/` 下创建以时间命名的目录：
```
/home/robot/log/not_permanent/2025_04_02-16_48_20/
├── default.launch      # 主launch日志（定位、导航、感知节点）
├── mobile_base.launch  # 底盘launch日志（电机、CAN、单片机）
└── ...
```

补充经验：

- `default.launch` 往往就是传感器信号监控日志。像 `~/log/not_permanent/2026_06_11-11_02_51/default.launch` 这类文件，现场排查时通常可以直接看到“谁的信号没了”。
- 如果要先判断是雷达、摄像头、USB 设备还是其他感知链路掉线，优先从 `default.launch` 开始看。

### 日志时间查找技巧
```bash
# 找到某个时间段的日志目录
ls -lt /home/robot/log/not_permanent/ | head -10

# 在 default.launch 中搜索某个时间前后
grep "16:48" /home/robot/log/not_permanent/2025_04_02-16_48_20/default.launch

# 搜索错误信息
grep -i "error\|fail\|exception" <日志文件> | tail -30
```

### 内核日志
```bash
# 当前启动的内核日志
dmesg -T

# 上一次启动的内核日志
sudo journalctl -o short-precise -k -b -1 > /tmp/last_boot.log

# -1 是上一次开机，-2 是上上次
sudo journalctl -o short-precise -k -b -2 > /tmp/2nd_last_boot.log
```

### 自动录包
- 路径: `/home/robot/autobag/`
- 格式: `.bag` (ROS bag), `.zip`, `.jpg`
- 保留策略: 7200 分钟（5天）后通过 crontab 自动删除
- 录包服务: `rosbag_rotate`（1分钟滚动录包）
- 错误码录包: `rosbag_caution`（仅在报错时录包）

## RCS 端日志

### 路径总览

| 路径 | 类型 | 说明 |
|------|------|------|
| MongoDB (docker) | 持久 | 新版日志记录在 MongoDB |
| `/var/run/log/new_backend.log` | 持久 | 后端主进程启动日志 |
| `/var/run/log/celery.log` | 持久 | Celery 异步任务日志 |
| supervisor stdout/stderr | 临时 | supervisor 管理的各进程日志 |

补充经验：

- `~/log/permanent/<开机时间>/error_monitor_server.launch` 是错误码登记日志，例如 `~/log/permanent/2026_06_11-13_34_48/error_monitor_server.launch`。
- 这个日志里通常可以查到错误码的触发时间、解除时间以及对应 `info`。
- `~/log/permanent/<开机时间>/` 这种日期目录是按开机时间生成的；只有下次开机时才会再生成新的目录。

### MongoDB 日志查询

新版本的 FastAPI 后端将日志记录在 MongoDB 中，可通过后端 API 查询：
```bash
# 进入 MongoDB 容器
docker exec -it docker-mongo_5_0-1 mongosh

# 查询最近的日志
use robot_backend
db.logs.find().sort({timestamp: -1}).limit(10)
```

### Supervisor 日志
```bash
# 查看所有服务状态
supervisorctl status

# 查看特定服务日志
supervisorctl tail new_backend
supervisorctl tail -f new_backend  # 实时查看
```

## 监控系统

### Uptime Kuma
- 入口: `http://<主机>:3001/`
- 监控项: PING连通性、HTTP状态、JSON数据验证
- 保留: 5天历史数据

### cy_robot_state_mon
- WebSocket: `ws://127.0.0.1:9990/websocket/`
- HTTP API: `http://<主机>:8079/gw_<robot_id>`
- 功能: 实时机器人状态监控

### Beszel
- 功能: 每台机器的性能指标监控
- 指标: CPU、内存、磁盘、网络、Docker资源、温度

## 日志级别含义

### ROS 日志级别
| 级别 | 前缀 | 含义 |
|------|------|------|
| DEBUG | `[DEBUG]` | 调试信息 |
| INFO | `[INFO]` | 正常运行信息 |
| WARN | `[WARN]` | 警告，需关注 |
| ERROR | `[ERROR]` | 错误，功能受影响 |
| FATAL | `[FATAL]` | 致命错误，节点可能崩溃 |

### 后端日志级别
通过 `config/logging.yaml` 配置，记录到 MongoDB。

## SSH 登录欢迎信息 (MOTD)

AMR 设备 SSH 登录时会显示：
- USB Intel 设备（深度相机）
- USB Orbbec 设备（深度相机）
- USB PCAN 设备
- USB CH340 设备（单片机串口）
- USB RGB 摄像头设备
- 自动录包占用空间
- 机器人 ID (`gw_<robot_id>`)
- 机器人模式来源

脚本位置: `/etc/update-motd.d/99-cyanine-os`
