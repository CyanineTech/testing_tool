# indv_params.yaml 参数调优指南

> 文件路径: `~/static/indv_params.yaml`  
> 每台机器人出厂前必须检查该文件所有值。如无需更改默认值，则不写入。

## 适用范围

- 需要调整机器人个体参数，尤其是传感器外参、取放货动作、点云过滤、导航参数和载具识别参数。
- 用户描述偏向“为什么这台车总偏”“这个托盘场景怎么调”“参数改哪里”“indv_params 怎么看”。

## 历史复盘优先

- 这页主要说明参数语义和调参入口，不应直接替代历史故障证据分析。
- 如果是“某次场景反复失败”“某台车长期偏同一方向”，应先回看历史任务、bag、日志和现场几何，再决定是否改参数。
- 不要把所有场景问题都直接归因到 `indv_params`；先排除 USB / CAN / 定位 / 路线 / 现场托盘差异等更直接原因。

## 常见检索词

- indv_params
- 参数调优
- 托盘参数
- 取货偏
- 放货偏
- tf 校准
- 充电对准参数
- cluster_tolerance
- inflation_radius
- 这台车总偏

## adjust_urdf（传感器安装误差补偿）

用于传感器安装位置与理论位置的差异补偿，**必有项**。

TF关系：`front_up_scanner` → `front_up_scanner_delta` 由 `front_scanner_xyz*` 和 `front_scanner_rpy*` 定义。

校准工具：`cy_tfadjust`（见下方"TF校准"章节）

### CT-04 传感器命名
| 参数前缀 | 对应传感器 |
|----------|-----------|
| Depthcamera_* | 后深度摄像头（撞板摄像头，托盘识别） |
| front_Depthcamera_* | 前深度摄像头 |
| fork_Depthcamera_* | 左叉尖深度摄像头 |
| fork_rDepthcamera_* | 右叉尖深度摄像头 |
| fork_up_Depthcamera_* | 左侧深度摄像头 |
| fork_up_rDepthcamera_* | 右侧深度摄像头 |
| front_scanner_* | 前下方中间雷达 |
| front_up_scanner_* | 顶部中间雷达 |

## charging（充电对准调参）

坐标系：x轴朝车头

| 参数 | 默认 | 说明 |
|------|------|------|
| target_corr_x | 0.0 | m，对准X轴微调（+前 -后） |
| target_corr_y | 0.0 | m，对准Y轴微调（+左 -右） |
| target_corr_yaw | 0.0 | rad，朝向微调（+逆时针 -顺时针） |
| ratio_tf_y_x_give_up | 0.15 | 摆动大→调小(0.04)；先外面调准再对接 |

## lift_cargo（取放货/托盘动作）

坐标系：x轴朝车尾，左右以车尾朝向为准

### 通用参数
| 参数 | 默认 | 说明 |
|------|------|------|
| action_with_gentle_brake | false | true=缓加减速（防倒货） |
| fork_stuck_points_count | 8.0 | 叉尖碰撞判断点云数阈值，误判可调大 |
| out_distance | - | m，取/放货后前进距离，离开库位 |
| slow_vel_coeff_picking | 0.3 | 取货撞货严重时调小(0.2) |
| speed_up_mode | true | false=降低插入/后退速度（窄托盘场景） |

### 取货偏修改（优先级从上到下）
| 参数 | 默认 | 说明 |
|------|------|------|
| target_corr_y | 0.0 | m，插入时Y轴微调（+左 -右） |
| target_corr_yaw | 0.0 | rad，插入时朝向微调 |
| ratio_tf_y_x_give_up | 0.15 | 取货准备点挪动太久→调大(0.25)；还偏→调小(0.1) |
| speed_up_coeff_loading | 3.0 | 最大插入速度倍数，插偏可降(2.0) |
| kp | 2.3 | PID强度，左右摇晃大→调小(2.0) |

### 放货偏修改（优先级从上到下）
| 参数 | 默认 | 说明 |
|------|------|------|
| go_straight_dist | - | m，叉臂上升时旋转中心到撞板距离；往前放→调小，往后放→调大 |
| target_corr_y_alt | 0.0 | m，放货Y轴微调（+左 -右） |
| target_corr_yaw_alt | 0.0 | rad，放货朝向微调 |
| speed_up_coeff_unloading | 3.0 | 最大放货速度倍数 |
| kp_alt | 1.6 | 放货PID强度，摇晃大→调小(1.2) |

### 托盘宽度相关
| 参数 | 默认 | 说明 |
|------|------|------|
| cargo_min_width | 0.6 | m，托盘脚最小间距（低于此不取） |
| cargo_max_width | 1.4 | m，货物最大宽度（设为实际+0.1m） |
| extreme_case_cargo_max_width_overwrite | - | m，超大货物强制宽度（如2.1m） |

### 叉尖相关高级参数
| 参数 | 默认 | 说明 |
|------|------|------|
| cam_measure_trigger_dist | -0.28 | m，触发功能的距离阈值 |
| stuck_detect_method | 3 | 0=关闭, 1=摄像头速度, 2=轮速, 3=默认 |
| use_cam_feedback | false | 摄像头测距补偿插入行程 |
| ignore_fork_tip_sensor | true | false=启用叉尖红外传感器 |
| check_collide_loading_pallet_end | false | true=叉尖凸出时检测障碍物 |

## pointcloud_filter（点云过滤/避障）

当避障摄像头误触发（看到莫名其妙的点），调大 `min_neighbors_in_radius`（默认5，可改8~9）：
```yaml
pointcloud_filter_fork_up_body:
  min_neighbors_in_radius: 8
pointcloud_filter_fork_up_head:
  min_neighbors_in_radius: 8
pointcloud_filter_front:
  min_neighbors_in_radius: 8
pointcloud_filter_rfork_up_body:
  min_neighbors_in_radius: 8
pointcloud_filter_rfork_up_head:
  min_neighbors_in_radius: 8
```

对于超宽货物，还需修改 `pointcloud_filter_fork` / `pointcloud_filter_rfork` 的 `data_filter_box` 第一个值为：旋转中心到货物尾部距离 + 0.05m

## move_base（自主导航）

```yaml
move_base:
  TebLocalPlannerROS:
    max_vel_x: 1.0         # m/s，最高前进速度（控制台可改）
    max_vel_x_backwards: 0.5  # m/s，最高后退速度（特殊需求改0.8）
```

超宽货物膨胀半径：`inflation_radius = extreme_case_cargo_max_width_overwrite/2 + 0.3`

## state_monitor（导航状态）

| 参数 | 说明 |
|------|------|
| footprint_state_2 | 载货碰撞模型多边形（超宽货物需改xx=-旋转中心到货尾距离） |
| xy_goal_tolerance_alt | 0.3m，CBS中途点到达位移精度 |
| yaw_goal_tolerance_alt | 0.6，CBS中途点到达朝向精度 |
| always_allow_init_with_backwards_motion | true=允许TEB倒车起步 |
| enable_fp2_latch_from_state0_forklimit | true=撞板触发后保持footprint_2 |
| enable_free_goal_vel | true=CBS中途点不需完全停稳 |
| manage_teb_knot_detection | true=乱路径不执行 |
| enable_docking_viapoint_change | true=docking阶段动态调整viapoint权重 |

## region_growing_multiple_plane_segmentation（载具识别）

| 参数 | 默认 | 说明 |
|------|------|------|
| max_area | 1.2 | m²，载具俯视最大面积（超大托盘改2.0） |
| cluster_tolerance | 0.07 | m，2D映射点云连通性判定距离 |

## obstacle_extractor（提取托盘脚）

| 参数 | 默认 | 说明 |
|------|------|------|
| min_group_points | 4 | 每个obstacle需要的rear_scan最小点数（误识别多→调大） |

## TF 校准工具 (cy_tfadjust)

### 启动
```bash
# indv文件模式（推荐）：编辑indv_params.yaml保存即生效
cy_tfadjust

# 键盘模式（带rviz可视化）
ssh -XC robot@<机器人>
cy_tfadjust -frontX 1.0 -backX 1.0 -lrX 1.0 -lrY 1.0
```

### 操作说明
- indv文件模式：编辑 `~/static/indv_params.yaml` 保存时自动发布TF
- 键盘模式：在车四周生成虚拟坐标，键盘移动传感器图像
- 程序启动时从 indv_params 读取全部坐标并重新发布
- 增加观察用TF：`base_footprint_y_view`、`base_footprint_x_view`

## 诊断命令

```bash
# 查看导航规划器类型
rosparam get /move_base/base_global_planner
# global_planner/GlobalPlanner = 退后模式
# nav_core_adapter::GlobalPlannerAdapter = 普通模式

# 查看是否允许倒车初始化
rosparam get /move_base/TebLocalPlannerROS/allow_init_with_backwards_motion

# 查看碰撞模型类型
rosparam get /move_base/TebLocalPlannerROS/footprint_model/type
# polygon = 精准碰撞, two_circles = 普通模式

# 查看状态监控反馈
rostopic echo /state_monitor/state_monitor_feedback

# 模拟电量（仿真/测试）
rostopic pub /motor_control/low_level_status motor_control/low_level_status_forklift "header: ..."
# 用tab补全，修改battery值
```

## 推荐排查顺序

1. 先确认问题更像参数问题，而不是硬件、定位、任务链路或现场几何异常。
2. 如果是历史问题，先固定失败时间并回看 bag、日志、现场照片。
3. 再按模块判断是 TF、取放货、避障、导航还是载具识别参数。
4. 每次只改一小组参数，并保留改前改后对照。

## 关联总入口

- [common-faults.md](common-faults.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [task_dispatch/pallet-or-geometry-mismatch.md](task_dispatch/pallet-or-geometry-mismatch.md)
- [ros/history-case-location-ok-but-map-or-tf-mismatch.md](ros/history-case-location-ok-but-map-or-tf-mismatch.md)
