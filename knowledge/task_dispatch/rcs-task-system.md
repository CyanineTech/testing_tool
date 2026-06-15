# RCS 任务系统参考

## 任务类型

| 类型标识 | 中文名 | 说明 |
|----------|--------|------|
| location | 基础任务 | 可添加库位或功能点到任务步骤的实体任务 |
| dispatch | 手动派遣 | 功能点呼叫任务，执行完后需人工释放机器人 |
| elevator | 电梯任务 | 工位呼叫任务（和诚客户） |
| standby | 功能点入库 | 通过功能点取货的入库任务（计划废弃） |
| location_call | 库位入库 | 呼叫机器人去某库位取货，可指定放货区域 |
| store_location | 直接入库 | 机器人身上有货时，直接去某库位放货 |
| standby_shipment | 订单式入库 | 批量取货的入库任务，需预先分配放货库位 |

## 机器人使用状态

| 状态 | 说明 |
|------|------|
| use | 使用中 |
| free | 空闲 |
| disconnect | 掉线 |
| fault | 故障 |
| low_power | 低电量 |
| charging | 充电中 |

## 事件类型

| ID | 名称 | 中文名 | 说明 |
|----|------|--------|------|
| 1 | none | 无 | - |
| 2 | stop | 停顿 | 延时事件 |
| 3 | scan_align | 雷达对齐 | - |
| 4 | accurate_align | 精准对齐(0.2) | - |
| 5 | pull_car | 拉料车 | - |
| 6 | drop_car | 放料车 | - |
| 7 | lift_get | 电梯口取货 | - |
| 8 | place_pallet | 库位放货 | 可选择放货位置 |
| 9 | auto_charging | 自动充电 | - |
| 10 | pallet_get | 装载托盘 | - |
| 11 | pallet_get_d | 正面装载托盘 | - |
| 12 | pallet_left | 左侧放货 | - |
| 13 | pallet_right | 右侧放货 | - |
| 14 | transfer_point | 传送点事件 | - |
| 15 | call_elevator | 呼叫电梯 | - |
| 16 | release_elevator | 释放电梯 | - |
| 17 | plane_transmission | 平面传送 | - |
| 18 | transfer_calibration | 传送校准 | - |

## RCS 配置参数 (start.yaml) - 以实际代码为准

| 参数 | 实际值(170) | 说明 |
|------|--------|------|
| port | 3737 | 从机后端API端口 |
| mode | single | 单机/集群模式 |
| env | DEBUG | 运行环境 |
| factory | general | 工厂标识 |
| developer | true | 开发者模式 |
| api_docs | false | API文档开关 |
| auth_manage | false(主)/true(从) | 鉴权开关 |
| auto_entry_mode | false | 自动进模式 |
| auto_event | true | 自动事件执行 |
| auto_release | true | 任务完成自动释放 |
| auto_return_rest | true | 自动回休息区 |
| auto_charging | true(主)/false(从) | 自动充电 |
| threshold_battery | 30 | 低电量阈值(%) |
| work_threshold_battery | 60 | 工作电量阈值(%) |
| rest_threshold_battery | 30 | 休息区充电阈值 |
| task_mode | sequence | 任务模式 |
| pick_up_rule | general | 取货规则 |
| stock_rule | general | 入库规则 |
| cooperation | 0 | 协作模式 |
| retry_mode_timeout | 3 | 重试进模式超时(秒) |
| retry_mode_times | 3 | 重试进模式次数 |
| retry_quit_mode_timeout | 1 | 重试退模式超时 |
| retry_quit_mode_times | 1 | 重试退模式次数 |
| master_ip | 127.0.0.1 | 主机IP(单机时本地) |
| master_token | false | 主机Token认证 |
| check_ap_delay | 5000 | AP检查延迟(ms) |
| data_backup_interval | 604800 | 数据备份间隔(秒=7天) |
| data_backup_folder_num | 109 | 备份目录保留数 |
| intelligent_dynamic_distribution_picking | false | 智能动态分配取货 |
| intelligent_dynamic_inventory_allocation | false | 智能动态库存分配 |
| registering_multiple_pickup_times | true | 注册多次取货 |
| generate_calibrate_data | true | 生成标定数据 |
| generate_key | true | 生成密钥 |
| hecheng | false | 合成模式(特定客户) |
| user_configured_enter_elevator_retry_duration | 30 | 电梯重试时间 |
| user_configured_recall_elevator_interval | 20 | 电梯重新呼叫间隔 |

### 错误自动处理配置
```yaml
ros_pickup_error_ids:    # 取货错误码→自动重试
  - 32000212
  - 30200014
  - 30200015
ros_stock_error_ids:     # 入库错误码→自动重试
  - 32000205
```

### 自动事件集 (auto_event_set)
stop, none, scan_align, accurate_align, pull_cat, drop_cat, lift_get, place_pallet, auto_charging, pallet_get, pallet_get_d, place_pallet_1, place_pallet_2, place_pallet_left, place_pallet_right, pre_target, yixuan_event, transfer_point, call_elevator, release_elevator

### 自动释放集 (auto_release_set)
task, standby, shipment, auto_charging, location, target_auto_release, store_location

## 库位参数默认值
```yaml
pallet_pos_size_params:
  length: 1.2      # 托盘长度(m)
  width: 1.0       # 托盘宽度(m)
  margin: [7.5, 7.5, 7.5, 7.5]  # 边距
  passage_width: 2.0  # 通道宽度(m)
  in_location_management_system: true
  pp_type: access
```

## 调用链与链路监控

如果问题不是“任务规则配错”，而是“任务发出后没有沿链路走完”，优先看 [Python / ROS 调用链与监控落点](python-ros-call-chain-monitoring.md)。

重点关注：

- `task_running_server -> map_server` 的 gRPC `127.0.0.1:9993`
- `map_server -> ROS 主机` 的 `/ecbs_srvs/ecbs_request`
- `ROS 主机 -> backend_fastapi` 的 `PATCH /robots/way/point/`
- Redis `global` 和 `{slave_id}` 频道
- 从机 ROS topic `/ecbs_msgs/ecbs_result_agent`、`/ecbs_msgs/map_nodes_agent`
