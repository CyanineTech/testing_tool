---
mode: "prompt"
description: "AMR/RCS 故障排查流程引导"
---

# 故障排查

请按以下格式描述故障：

1. **故障设备**: (IP或主机名，如 leefung-t8, 192.168.1.250)
2. **故障现象**: (如：机器人红闪、无法进模式、任务不派发、摄像头离线等)
3. **发生时间**: (何时开始出现)
4. **影响范围**: (单台/多台，是否影响生产)

---

## 排查步骤

### 固定顺序
1. 先确认故障设备、现象、时间、影响范围
2. 先做连通性和网络诊断，判断是本机、从机还是主机不可达
3. 再跑 AMR / RCS 快速状态检查脚本
4. 再按故障类型分流到硬件、导航、网络、后端或错误码
5. 最后收集日志，取到 bag 或 caution 证据后再给结论
6. 默认直接自动执行到可得结论；只有缺少目标设备 / 主机名 / 关键现象时才追问一次

### Step 1: 快速状态检查
```bash
# AMR 检查
bash scripts/check_amr_status.sh <设备IP>

# RCS 检查 (如果问题可能在后端)
bash scripts/check_rcs_status.sh 192.168.1.170
```

### Step 2: 根据故障分类深入排查

**硬件类故障** (USB设备/电机/传感器):
- 参考: `knowledge/common-faults.md` → USB 设备故障 / 电机CAN故障
- 关键命令: `lsusb -t`, `ip -s -d link show can0`, `dmesg -T`

**导航类故障** (定位丢失/路径规划失败/避障异常):
- 参考: `knowledge/common-faults.md` → 定位/导航故障
- 关键命令: `rostopic echo /amcl_pose`, `rostopic echo /move_base/status`

**网络类故障** (掉线/延迟高/无法连接):
- 运行: `bash scripts/network_diag.sh <设备IP>`
- 参考: `knowledge/system-architecture.md` → 网络拓扑

**RCS后端故障** (任务不派发/机器人状态异常):
- 运行: `bash scripts/check_rcs_status.sh <RCS主机IP>`
- 参考: `knowledge/task_dispatch/rcs-task-system.md`

**错误码查询**:
- 参考: `knowledge/error-codes.md`

### Step 3: 日志深入分析
```bash
bash scripts/collect_logs.sh <设备IP> [时间关键词]
```

### Step 4: 给出结论

请按以下格式输出诊断结果：

```
## 诊断结果

**故障类别**: [硬件/软件/网络/配置]
**严重程度**: [信息/警告/错误/致命]
**影响范围**: [单台设备/多台设备/全局]

**根因分析**:
<具体原因描述>

**修复方案**:
1. [紧急处理步骤]
2. [根本修复步骤]

**是否需要停机**: [是/否]
**预计恢复时间**: [估计]
```

### 交互规则

- 收到可执行问题后，先回复一条“正在排查中”，不要把排查中和最终结果合并成一条。
- 默认先走原排障流程，不引入额外模型复核分支。
- 飞书只作为外部触发器，不改变原来的排障顺序和结论结构。
