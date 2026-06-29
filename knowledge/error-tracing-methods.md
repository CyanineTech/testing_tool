# 机器常见错误追溯方法

## 适用范围

- 已知大概故障时间、错误码、任务时间，想继续追历史证据。
- 用户描述偏向“怎么追根因”“怎么回溯”“这个错误往哪里深挖”。

## 历史复盘优先

- 这页默认面向历史故障复盘，不是给当前状态快速巡检用。
- 应优先固定故障时间、错误码触发时间、任务动作时间，再围绕该时间窗口回看 bag、ROS 日志、内核日志和后端日志。
- 当前状态只能作为补充，不应覆盖历史证据结论。

## 常见检索词

- 怎么追根因
- 怎么回溯故障
- 历史故障怎么查
- 错误码怎么查日志
- bag 怎么对时间
- 故障时间前后看什么
- 重启后恢复怎么查

## 推荐排查顺序

1. 先确定故障时间点或时间窗口。
2. 先找错误码、任务动作、重启事件的时间锚点。
3. 再按层级回看 ROS / 后端 / 网络 / 内核日志。
4. 如果需要运动或场景细节，再回看 bag。
5. 结论输出时必须区分已证实证据、补充信息和待验证推测。

## AMR 历史三阶段建议

针对 AMR 事后复盘，推荐按下面三阶段逐步收口，而不是首轮看完就下结论：

1. 第一阶段：先固定故障时间、开机目录和基础历史日志
   - 优先确定精确故障时间或时间窗口
   - 回溯到对应 `not_permanent/<开机时间目录>`
   - 先收 `default.launch`、`mobile_base.launch`、`state_monitor_wrapper.launch`、`dmesg`、`caution_files`
2. 第二阶段：补低层与运行态证据
   - 看 `/low_level_error`
   - 看 `rosnode list`
   - 看 `can0`
   - 看 `lsusb -t`
   - 对照 launch 日志里底层、扫描、定位、任务相关异常
3. 第三阶段：补 `caution / bag` 与恢复动作线索
   - 看同时间段是否存在 `caution_*.bag.zip`
   - 必要时继续核对 bag 前后 `20s~60s` 状态变化
   - 若现场有切手动、重发任务、人工释放、人工恢复，应把它视为掩盖首因的恢复动作，而不是根因本身

## 底层日志体系

### 三种日志类型

| 类型 | 路径示例 | 说明 |
|------|----------|------|
| 连续基础日志 | `~/autobag/_2025-10-12-05-43-37_2806.bag` | 每文件1分钟，不间断录制 |
| 重要错误日志 | `~/autobag/caution_T10_20251014_140530.bag.zip` | 特定错误触发时自动录制前后20秒 |
| ROS 原始日志 | `~/log/not_permanent/<时间>/` | 每次进模式创建新目录 |

### 重要错误触发条件

以下错误码会触发自动录包（caution）：
- 30200019, 20100022, 34100017, 30200014, 30200027, 30200028, 30200029, 30200021, 32000216

### 错误快照页面

访问 `http://<主机名>/static/caution.html` 可快速查看：
- 错误码和时间
- 错误发生时前后摄像头的实时照片
- 一键复制 scp 命令下载对应 bag 文件

## 日志提取工具 (Download.py)

### 使用方法
```bash
ssh robot@<机器人>
python3 Download.py
# 输入时间，如：2026-01-09 11:01:53
# 输入额外日志关键词（可选，直接回车跳过）
```

### 支持的时间格式
- `2026_01_04-23_58_53`
- `2026-01-04-23-58-53`
- `20260104-235853`
- `2026-01-09 10:26:35`
- `2026/01/09 10:26:35`
- `2026.01.09 10:26:35`

### 输出内容
- 自动录包（输入时间前2分钟）
- caution 录包（前后1分钟）
- 内核日志 dmesg（前后1分钟）
- ROS 日志（默认: mobile_base.launch、pure_laser_amcl.launch、lift_cargo.launch、state_monitor_wrapper.launch，前后1分钟）
- 生成 scp 命令便于下载

补充经验：

- `~/log/not_permanent/<时间目录>/default.launch` 经常就是传感器信号监控日志。排查“谁的信号没了”时，通常优先看这里。
- `~/log/permanent/<开机时间>/error_monitor_server.launch` 是错误码登记日志，适合查错误码的触发时间、解除时间和对应 `info`。
- `~/log/permanent/<开机时间>/` 目录按开机时间生成；只有下次开机时才会再生成新的日期目录。

### 日志时间戳转换
```bash
python3 convert_timestamps.py mobile_base.launch > mb.log
```
将 ROS 原始日志的纯数字时间戳转为可读格式，并按时间排序。

## 基础日志 bag 中包含的 Topic

### /motor_control/low_level_status
| 字段 | 说明 |
|------|------|
| low_level_error | 底层错误码（对应错误列表 20100006~20100031） |
| fork_tip | 叉尖传感器触发状态 |
| fork_limit | 叉货到位（根部撞板）传感器 |
| fork_stage | 0=未知, 1=叉臂下降到位, 2=叉臂上升 |
| battery | 电池电量(%) |
| battery_current | 电池电流A（-放电, +充电） |
| battery_voltage | 电压（需÷100得到V） |
| driving_motor_error | 行走电机错误 |
| steering_motor_error | 转向电机错误 |
| info | [手自动(1自动,2手动), 柱子按钮] |

### 运动相关 Topic
| Topic | 说明 |
|-------|------|
| /odom | 里程计（位移、朝向、线速度、角速度） |
| /motor_control/driving_motor_rpm | 行走电机实际转速(rpm) |
| /motor_control/driving_motor_rpm_sent/twist/linear/z | 发给行走电机的转速命令(rad/s) |
| /motor_control/driving_motor_rpm_sent/twist/linear/x | 转向电机转角命令(rad) |
| /motor_control/driving_motor_rpm_sent/twist/linear/y | 转向电机实际转角(rad) |
| /gw_{robot_id}/move_manager/robot_pose | 机器人在地图中的位置 |
| /cmd_vel | 自主导航原始规划速度 |
| /cmd_vel_mux | 经过状态选择后的速度命令 |
| /mobile_base_controller/cmd_vel | 加减速平滑后的最终速度命令 |

### 充电调试 Topic
| Topic | 说明 |
|-------|------|
| /motor_control/battery_debug.y | 0=准备判断, 1=充电中, 2=充电停止, 3=停止(错误/充满/保护) |
| /motor_control/battery_debug.w | 10=充满后激活中, 20=充满后关闭中, 30=充电错误, 40=要求进入充电, 50=要求退出充电 |
| /motor_control/motor_control_debug.x | 0=不在充电, 50=在充电 |
| /motor_control/motor_control_debug.y | 50=充满, 70=未充满 |
| /motor_control/motor_control_debug.z | 0=电极关闭, 50=电极打开 |

## 各类错误排查流程

### 摄像头离线 / 嵌入式系统停止发送数据
→ 优先看 [USB 设备异常 / 摄像头离线](usb-device-troubleshooting.md)，重点对照 `lsusb -t` 层级、`dmesg -T`、`default.launch`、`mobile_base.launch` 和 `caution` 录包。

### 有功能模块被关闭/无响应

**未重启情况：**
```bash
ssh robot@<机器人>
rostopic echo /gw_<robot_id>/rt_node_info
# 关注 notRunningNodeList 和 zombieNodeList（忽略 rostopic 本身）
```

**已重启情况：**
```bash
cd ~/log/permanent
ll  # 找到错误发生前最近的目录
vi lanyin.log
# 搜索错误时间，关注 zombie node list
```

### 电机错误排查

1. 通过 sftp 或 scp 下载错误时间对应的 bag 文件
2. 用 Foxglove 打开，查看：
   - `/motor_control/low_level_status` 的 `driving_motor_error` 和 `steering_motor_error` 是否为 0
   - `/motor_control/driving_motor_rpm.data` 转速是否为 0
3. 结果告知开发

### 取货失败排查

**无法识别托盘 / 取货失败 / 叉臂被卡住：**
1. 查看 `http://<主机>/static/caution.html` 的错误快照照片
2. 判断是否因为：
   - 托盘规格不符
   - 托盘残缺（特征不完整）
   - 货物摆放太偏
3. 如无法判断，用 Foxglove 配置 `loading_unloading.json` 查看 bag

**托盘识别原理 (rviz/foxglove)：**
- `rear_scan` (黄色): 激光扫描数据，出现在细柱状物体上
- `obstacles` (绿色圆柱): 在 rear_scan 上生成的障碍物标记
- `debug_polygon` (蓝色框): 程序在此范围内寻找托盘脚
- 需要至少 2 个 obstacles 与蓝色框相交才能识别成功
- `debug_polygon` 大小由白色点云数据连通性决定（ConvexHull）

**识别失败常见原因：**
- 背光导致深度数据缺失
- 点云数据不连通，debug_polygon 过小
- 两个 obstacles 间距小于托盘最小间距
- `indv_params.yaml` 中 `cluster_tolerance` 参数可调

### 叉臂上升失败

用 Foxglove 查看 bag 中：
- `fork_stage`: 1=降到底, 2=升到顶, 0=中间状态
- `driving_motor_error` / `steering_motor_error` 是否为 0
- `battery_current` 电流是否异常
- `driving_motor_rpm`: 有值=车在动，+=前进，-=后退

正常流程：退后 → 插入托盘底部 → 抬叉 → 抬叉同时前进

### 防撞条触发

查看 `http://<主机>/static/caution.html` 照片判断是否人为导致。

### 放货报错（身上有货/无货）

**有货情况常见原因：**
1. 取货完碰撞条未感应到（接触面太小）
2. 托盘太宽超出碰撞条范围
3. 取货后行走中碰到物体触发碰撞条暂停→报错
4. 叉臂没升到顶就开始走→跳过放货步骤
5. 放完货后撞板未离开→障碍物等待超时

**无货情况常见原因：**
1. 切手动放货后切回自动，未跳过放货步骤 → 联系后端
2. 切手动时智能分配中，切回后任务未取消 → 联系后端
3. 托盘脚损坏脱落 → 现场处理
4. 充电位接任务后立马报错 → 联系后端

### 同库位多次取/放货失败

- 检查机器取货位置是否太偏/太近
- 调整地图中库位位置
- 调整事件坐标 X 值（X 越大，取货距离越远）

### 充电相关错误

**关键 Topic 观察：**
- `battery_current`: 充电时应为正值
- `battery_debug.y`: 充电状态机
- `motor_control_debug.z`: 电极开关状态

**典型故障：** 电极打开且未充满，但电流突然从正变负 → 充电桩问题

### 驱动停止发布数据

1. 确定报错时间和当时任务
2. SSH 进入，查看内核日志：
   ```bash
   sudo journalctl -o short-precise -k -b -1 > /tmp/last.log
   ```
3. 检查是否有物理因素（USB/摄像头/内存问题）
4. 进入 `log/not_permanent` 找对应时间目录
5. 转换时间戳搜索 `mobile_base.launch`

## 疑难排查案例：时间跳变导致机器人突然退后

### 现象
机器人在无任务时突然高速后退。

### 排查过程
1. 控制台录像、后端日志、ROS 任务层日志均未发现新任务 → 非上层触发
2. 查看连续基础日志 bag + mobile_base.launch 原始日志
3. 日志中发现 `jump back in time...clearing TF...` + 高转速 rpm=-3238
4. Foxglove 分析发现 2.5s 时间段内：
   - 轮子高速反转（driving_motor_rpm ≈ -4500）
   - odom/twist 为 0（程序认为没有速度）
   - 数据呈锯齿状波动
   - low_level_status 的 seq 计数器回跳

### 根因
Chrony 时间同步在导航运行中触发大幅度时间校正（2.5s），导致：
- `swerve_steering_controller` 中 dt 为负数
- 速度/加速度限制计算异常
- 无上层命令时向电机发出高速旋转命令

### 修复
- 更保守的 chrony 同步策略（makestep 0.05 3 + maxslewrate 1000）
- 代码层对负数 dt 添加保护机制

## Foxglove 配置文件

| 配置文件 | 用途 |
|----------|------|
| loading_unloading.json | 取货/放货/对准/识别类错误分析 |
| check_collide.json | 碰撞错误分析 |
| low_level_status_and_cmd_vel.json | 底层状态+速度命令 |
| check charging fault.json | 充电故障分析 |

## 关联总入口

- [README.md](README.md)
- [common-faults.md](common-faults.md)
- [log-paths.md](log-paths.md)
- [error-codes.md](error-codes.md)
| get_pallet.rviz | rviz 完整托盘识别数据 |
