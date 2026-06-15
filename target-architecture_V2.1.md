# 飞书触发的本机 AI 排障系统 - 架构与开发实现规范 (V2.1 完整领域版)

> **致阅读此文档的 AI 编码助手**：
> 本文档是当前项目的核心架构与业务逻辑蓝图。请严格遵循本文档中定义的模块职责、接口规范和安全约束。
> **核心开发背景**：当前环境无法使用原生 API Key 进行 Function Calling。核心推理引擎必须依赖本地安装的 CLI 工具（如 Claude Code/Copilot CLI）。交互层必须使用 PTY（伪终端）处理 stdin/stdout，并通过正则拦截实现“受控沙盒工具调用”。

## 1. 核心架构流转

系统部署在 Ubuntu 20.04 (ROS 1 Noetic) 节点，登录用户默认锁定为 `robot`。推荐架构由六层构成：

1. **飞书网关**：长连接监听 `@机器人` 消息。
2. **状态与路由**：提取 route、target、time_key、follow-up 状态，完成粗粒度分类。
3. **知识检索层**：从 `knowledge/` 中选择与当前 route 最相关的 Top-K SOP / 文档摘要，作为首轮上下文注入；此层负责“先缩小问题空间”，而不是把整个知识库无差别交给模型。
4. **CLI 驱动层 (PTY Wrapper)**：拉起本地大模型 CLI，过滤终端颜色字符，注入首轮上下文、会话历史和受控协议。
5. **受控补证层**：如果首轮证据不足，CLI 只能通过受控协议申请两类动作：
    - `read_knowledge`：继续读取指定 knowledge 文档或补充 SOP 摘要。
    - `execute`：执行白名单只读命令，经 `whitelist.json` 校验后发送至系统执行。
6. **输出与复盘**：当证据足够时输出最终 `report`，回传飞书，并生成排障经验草稿。

当前实现中，这一层的证据语义应明确区分为两类：

1. `knowledge_candidates`：应用侧在首轮检索出的 Top-K 候选文档清单，用于告诉模型当前问题空间已被缩小到哪些 SOP。
2. `knowledge_read[...]`：模型通过受控 `read_knowledge` 实际读取过的文档摘要，用于告诉后续 follow-up 和最终报告“哪些文档真的被读过”，而不是只被候选过。

推荐闭环如下：

1. 飞书消息进入系统。
2. 应用完成粗路由与目标提取。
3. 应用从知识库检索 Top-K 候选 SOP，并把摘要注入模型。
4. 模型优先基于已有 SOP 与现有 evidence 做判断。
5. 若证据不足，模型只能申请 `read_knowledge` 或 `execute`。
6. 系统回填新增知识或命令结果，直到模型输出 `report` 收束。

## 2. 全景目录结构与知识库映射规范

请按以下结构生成项目脚手架。特别注意 `knowledge/` 目录下各业务线的垂直拆分：

```text
feishu_agent/
├── main.py                     # 启动入口 
├── config.yaml                 # 默认配置 (网卡 enp88s0, 账号 robot, 等)
├── core/
│   ├── feishu_listener.py      
│   ├── router.py               
│   ├── post_mortem.py          
│   └── cli_wrapper.py          # 🚨 核心模块：pexpect 包装器，处理终端流
├── agent/
│   └── orchestrator.py         
├── sandbox/
│   ├── ssh_executor.py         
│   └── whitelist.json          
└── knowledge/                  # 📚 全领域知识库与 SOP 设定
    ├── README.md               # 顶层说明：主从架构、日志全局路径、bag提取标准
    ├── ros/                    # ➡️ 导航与底层算法
    │   ├── lidar_offline.md    # 雷达掉线排查 (dmesg / rosnode ping)
    │   └── local_error.md      # 定位异常排查 (tf 树检查 / /scan 频率)
    ├── hardware_bus/           # ➡️ 底层硬件通信
    │   ├── usb_timeout.md      # USB 接口超时排查 (lsusb / dmesg 过滤)
    │   └── can_bus_error.md    # CAN 异常排查 (ifconfig can0 / candump)
    ├── network/                # ➡️ 网络通讯与组网
    │   └── tailscale_drop.md   # Tailscale 断连排查 (systemctl status / enp88s0 抓包)
    ├── backend/                # ➡️ 车端/边缘端后端服务
    │   ├── api_timeout.md      # 接口超时排查 (HTTP 状态码 / 进程 CPU 占用)
    │   └── db_error.md         # 数据库异常排查 (连接池占满 / 磁盘 read-only 检查)
    ├── frontend/               # ➡️ 车端 HMI/UI 渲染
    │   └── ui_sync_error.md    # 前后端状态不同步 (WebSocket 断开 / 浏览器缓存)
    ├── task_dispatch/          # ➡️ 单机任务控制
    │   ├── not_received.md     # 任务不派发排查 (RCS 通信状态 / 状态机阻塞)
    │   └── fork_error.md       # 叉货不到位/失败排查 (电机电流日志 / 托盘位姿识别)
    ├── cbs/                    # ➡️ 集群与调度中心 (CBS)
    │   └── cluster_sync.md     # 车辆离线/坐标漂移排查 (MQTT 消息堆积 / 授时 NTP 同步)
    └── _ai_drafts/             # AI 自动生成的 SOP 沉淀草稿区

```

## 3. CLI 包装与交互协议 (`core/cli_wrapper.py`)

必须在发给模型的 System Prompt 中设定严格的受控协议。模型不能自由浏览本地文件系统，也不能自行调用 CLI 内建 shell / tool UI。首轮知识由应用侧先注入；若不足，模型只能通过受控动作补证。

### 3.1 协议原则

1. 首轮必须优先基于应用已注入的 SOP 摘要和当前 evidence 推理。
2. 如果知识不足，模型必须先申请 `read_knowledge`，而不是直接臆造未读取过的 SOP 内容。
3. 如果需要系统级证据，模型必须申请 `execute`，且一次只允许一条命令。
4. 获得足够证据后，模型必须输出 `report` 收束。
5. 除 `read_knowledge`、`execute`、`report` 外，任何普通文本命令建议、交互确认界面、TUI tool 调用都视为协议违规。

### 3.2 Prompt 约束注入示例

> "你是一个 AMR 排障专家。目标系统 Ubuntu 20.04。首轮知识库摘要已由系统注入，你必须先基于这些 SOP 和已有 evidence 判断。
> 如果知识证据不足，**必须且只能**输出以下代码块申请补充知识：
> ```read_knowledge
> knowledge/hardware_bus/can_bus_error.md
> ```
>
> 如果需要系统级证据，**必须且只能**输出以下代码块（系统会自动拦截执行并返回结果）：
> ```execute
> ip -details link show can0
> ```
>
> 获得结论后，必须输出：
> ```report
> {"root_cause": "...", "solution": "..."}
> ```"

### 3.3 `read_knowledge` 约束

1. 只能读取 `knowledge/` 目录下白名单范围内的 Markdown 文档。
2. 一次只允许请求一个文档路径。
3. 读取结果由系统裁剪和摘要后回填，不能把原始文件系统读权限直接交给模型。
4. 如果文档不存在、越权或不在允许目录内，系统必须拒绝并回填拒绝原因。
5. 每次成功的知识读取都应在 provider trace 中留下独立事件，例如 `pty_read_knowledge`，并记录 `path`、成功/失败状态以及摘要预览，便于后续排查“模型到底读了哪份知识”。

### 3.4 `execute` 约束

1. 一次只允许一条白名单命令。
2. 禁止重定向、写入、删除、重启、修改配置等破坏性动作。
3. 返回结果必须由系统裁剪后回填，避免长日志直接淹没上下文。

### 3.5 `report` 约束

`report` 必须是最终收束输出，至少包含：

1. `summary`
2. `root_cause`
3. `severity`
4. `next_steps`
5. `evidence`
6. `confidence`

## 4. 重点业务线 SOP 编写模板示例

在让 AI 读取知识库时，各子领域的 Markdown 必须结构严谨，指导 AI 调用确切的本地命令。

### 示例 A：`hardware_bus/can_bus_error.md`

```markdown
# CAN 总线异常排查 SOP

## 1. 现象描述
底盘运动控制失效，或底层传感器数据丢失。

## 2. 约束与白名单工具取证
1. 检查 CAN 接口状态：`ip -details link show can0` (确认 state 为 ERROR-ACTIVE 或 BUS-OFF)
2. 提取底层系统错误：`dmesg | grep -i can | tail -n 20`
3. 检查相关 ROS 节点：`rosnode info /can_driver`

## 3. 根因判别矩阵
| 现象/日志 | 可能根因 | 建议处置方案 |
| :--- | :--- | :--- |
| `state BUS-OFF` | 物理线路短路/断路 | 检查总线终端电阻，重启对应的物理节点 |
| `dmesg` 报 `buffer overflow` | 波特率不匹配或负载过高 | 确认波特率配置，检查干扰节点 |

```

### 示例 B：`backend/db_error.md`

```markdown
# 数据库/存储异常排查 SOP

## 1. 现象描述
后端日志狂刷写入失败，或者查询接口全部 500 超时。

## 2. 约束与白名单工具取证
1. 检查磁盘 I/O 状态：`dmesg | grep -i "I/O error"`
2. 检查系统挂载状态：`mount | grep -w "/"` (确认是否变更为 `ro` 只读模式)
3. 检查数据库进程：`systemctl status mysql` (或对应 DB 服务)

## 3. 根因判别矩阵
| 现象/日志 | 可能根因 | 建议处置方案 |
| :--- | :--- | :--- |
| mount 显示 `ro` | 硬盘故障引发文件系统自保 (Read-Only) | 触发告警。需人工介入运行 `fsck` 或更换硬盘 |
| `Too many connections` | 后端连接池泄露 | 重启后端服务释放连接，提交 bug 追踪溯源 |

```

### 示例 C：`task_dispatch/fork_error.md`

```markdown
# 叉货不到位 / 视觉对齐失败排查 SOP

## 1. 现象描述
车辆已到达提货区（pick-up area），但 Roll Cage / Pallet（托盘）对齐失败，或货叉举升异常中断。

## 2. 约束与白名单工具取证
1. 检查相机节点帧率：`rostopic hz /camera/depth/image_raw`
2. 检查 Label Studio 模型推理后端日志（若是视觉识别问题）：`journalctl -u ml-backend.service -n 50`
3. 获取底盘电机反馈：`rostopic echo -n 1 /fork_motor_status`

## 3. 根因判别矩阵
| 现象/日志 | 可能根因 | 建议处置方案 |
| :--- | :--- | :--- |
| 相机 hz 为 0 | 深度相机掉线 | 检查 USB 供电，重启相机 node |
| 模型置信度低于阈值 | 现场光线或托盘反光异常 | 切换至人工遥控接管，现场拍照反馈算法团队 |

```

## 5. 安全沙盒白名单 (`sandbox/whitelist.json`) 示例要求

系统拦截 `<execute>` 中的命令后，必须按正则表达式校验。

* **允许的模式**：`^ip a.*$`, `^ping -c [1-5] .*$`, `^systemctl status [a-zA-Z0-9_-]+$`, `^dmesg.*$`, `^journalctl.*$`, `^rostopic hz.*$`
* **拒绝的操作**：禁止写入 (`>`), 禁止修改 (`usermod`, `chmod`), 禁止删除 (`rm`), 禁止重启机器 (`reboot`, `shutdown`)。

## 6. 从当前实现迁移到混合式最小 PTY 试验的下一步

### 6.1 当前状态判断

截至当前代码版本，系统已经具备以下能力：

1. `providers/copilot_cli.py` 已实现单次 `-p` 与 PTY 多轮协议分流。
2. `core/cli_wrapper.py` 已实现 `read_knowledge` / `execute` / `report` 代码块识别、回填结果、等待最终 report。
3. `sandbox/ssh_executor.py` 与 `sandbox/whitelist.json` 已实现本地/SSH 只读白名单校验。
4. `core/orchestrator.py` 已支持 Top-K 文档候选注入，并把 `knowledge_candidates` 与 `knowledge_read[...]` 分开记录到会话证据。
5. `core/orchestrator.py` 已支持 follow-up 时把上一轮回复、部分证据以及“已读文档优先、候选文档回退”的文档上下文重新注入 provider。
6. `providers/copilot_cli.py` 已把 `pty_stalled_no_blocks`、`pty_partial_report_timeout` 等 PTY 中间失败态升格为显式 provider 结果，线上不再只能看到笼统的 `copilotcli 超时后已终止`。
7. `core/cli_wrapper.py` 现在已支持 knowledge observation 提交、流式 report-like JSON 兜底提取、字段清洗与归一化；最小 `read_knowledge -> report` 对照探针已能返回结构化 ProviderResult。

当前未完成的重点已收缩为两件事：

1. 真实飞书入口下，`amr` 路由是否能稳定复现本地已验证通过的最小 `read_knowledge -> report` 闭环。
2. 在证据不足时，模型是否能继续通过受控 `execute` 拉取系统级证据，而不是只停留在“知识摘要不足”的保守报告。

### 6.1.1 2026-06-11 最新 PTY 对照实验结论

当天的最小真实探针和对照实验已经得到以下可复现结论：

1. 原先较长的 interactive protocol prompt 在真实 PTY 链路中容易进入 `pty_stalled_no_blocks`，表现为反复出现 `Working esc cancel`，且没有 `read_knowledge`、`execute`、`report` 任一协议块。
2. 极短 wrapper prompt 已能让 Copilot CLI 吐出可解析 JSON；说明 PTY 不是完全不可用，问题更接近“提示词过长、重复规则过多、导致大段协议回显和收束不稳定”。
3. 将 `build_interactive_protocol_prompt()` 压缩后，短 provider probe 已能在 `pty_session_finish` 中拿到 `report_payload`，虽然 `stop_reason` 仍可能是 `deadline_timeout`，但 provider 已可直接返回 PTY 生成的结论，而不是立刻 fallback 到 single-shot。
4. 在进一步缩小到“第一步必须且只能输出一个 `read_knowledge` 代码块，正文固定为 `knowledge/common-faults.md`”的最小动作探针后，真实 PTY 已能稳定产出 `pty_read_knowledge` 事件；说明 action-first 的首动作打通问题已经解决。
5. 在 knowledge observation 改为可提交的 PTY 消息、知识摘要压缩、以及流式 report-like JSON 兜底提取后，最小 `read_knowledge -> report` 探针已能返回结构化结果，不再停留在 `stalled_no_blocks` 或 `pty_partial_report_timeout`。
6. 最新最小探针的最终结论仍然是“证据不足”，例如：仅凭 `knowledge/common-faults.md` 的摘要会收束到“仅有常见故障知识摘要，尚不足以定位具体 AMR/RCS 故障。未提供具体现象、日志或设备状态，无法判断根因。” 这说明当前剩余边界已经不再是 PTY 协议闭环，而是证据密度与真实 case 输入质量。
7. 飞书真实入口的第一轮偏航不是单纯 stalled，而是 command-heavy 的 provider context / doc excerpt 触发了 Copilot CLI 自带的命令确认框，表现为 `Checking AMR status`、`Do you want to run this command?`、随后 `pty_protocol_abort`；这一步已经通过收紧 provider context、清洗 doc excerpt、去掉 `首查命令` 注入得到缓解。
8. 飞书真实入口的第二轮偏航表明：仅压缩 context/evidence 还不够，Copilot 仍可能自行走内建 `Search/Read/Check/shell` 工具流；因此 interactive prompt 需要显式禁止这些内建工具，并要求一律先输出 `read_knowledge` / `execute` / `report` 代码块。
9. 在第三轮收紧后，偏航点已从“内建工具流”收缩为“默认交互首页与工作态噪声”，即 trace 中主要剩下 `@ files / # issues / Check for mistakes / Working esc cancel` 与 report-like JSON 片段交织；当前最新修复是把 PTY 启动方式从“先进入首页再通过 stdin 粘贴 prompt”切到官方 `copilot -i <prompt>` 自动执行。

这意味着当前阶段对 PTY 的判断应更新为：`report-only` 和最小 `read_knowledge -> report` 真链路都已通过本地验证；真实入口下的主问题已从“模型是否会乱跑内建工具”收缩为“切到 `copilot -i` 后，飞书真实消息入口能否稳定复现这条本地已验证的最小链路”。

### 6.2 下一步原则

下一步不要做以下动作：

1. 不要全量把 `amr`、`network`、`rcs` 都切到 PTY。
2. 不要继续用纯 `-p` 路径验证“是否会自己执行后续检查”，因为该路径只负责单次总结，不负责动作闭环。
3. 不要先把知识检索完全交给模型自由探索文件系统。
4. 不要先扩白名单再验证协议稳定性，先用最小 `read_knowledge` / `execute` 集合跑通闭环，再按真实 case 补能力。
5. 不要重新把 interactive prompt 扩回大段重复规则、示例和格式说明；最新实测表明 prompt 膨胀会显著增加 PTY 回显和 stalled 风险。

下一步应该做的是：只针对 `amr` 路由开启受控 PTY 小流量试验，验证“首轮 Top-K SOP 注入 + 必要时 `read_knowledge` / `execute` 补证”的多轮闭环在飞书真实消息入口下是否稳定。

在继续扩大 PTY 使用面之前，优先完成两件事：

1. 保持 `feishu_agent.service` 继续通过 `EnvironmentFile=/etc/default/feishu_agent` 加载 `COPILOTCLI_ENABLE_PTY_PROTOCOL=1` 与 `COPILOTCLI_PTY_ROUTES=amr`；当前虽然 `systemctl show feishu_agent.service --property=Environment` 仍返回 `Environment=`，但主进程环境已确认实际加载了这些变量。
2. 保持 interactive prompt 继续禁止内建 `Search/Read/Check/shell`，并使用 `copilot -i <prompt>` 作为 PTY 启动方式，避免再次回到默认交互首页后再粘贴 prompt 的旧路径。
3. 在飞书侧用单个 `amr` case 做小流量验证，重点观察真实消息入口下是否仍会出现 `pty_protocol_abort`、`Search/Read/Check`、`@ files / # issues` 首页噪声，或是否已经稳定收束到 `read_knowledge -> report`，以及是否需要再追加 `execute` 补证。

### 6.3 最小 PTY 试验开关

首轮试验环境建议仅开启以下开关：

```bash
FEISHU_ENABLE_PROVIDER_REVIEW=1
COPILOTCLI_ENABLE_PTY_PROTOCOL=1
COPILOTCLI_PTY_ROUTES=amr
COPILOTCLI_TIMEOUT=600
```

要求：

1. 只把 `amr` 放入 `COPILOTCLI_PTY_ROUTES`。
2. `network` 与 `rcs` 继续保持单次 `-p`，避免扩大不稳定面。
3. 生产默认值仍应保持未配置 `COPILOTCLI_PTY_ROUTES` 时不进入 PTY。
4. 若服务级环境变量未生效，飞书侧测到的仍会是当前稳定单次路径或 fallback 路径，而不是本地已验证通过的最小 PTY action-first 链路。

### 6.3.1 2026-06-11 当前验收边界

截至 2026-06-11 当前轮次，建议把验收边界明确写成：

1. 本地最小 PTY 真链路 `read_knowledge(common-faults) -> report` 已打通。
2. 返回内容已经能形成结构化 ProviderResult，不再只是 stalled / timeout 分类错误。
3. 当前结果内容仍偏保守，是因为探针只提供了单份通用知识摘要，没有给出真实设备现象、日志、target 或时间范围。
4. `feishu_agent.service` 当前已通过 `EnvironmentFile` 显式开启 `amr` 路由 PTY 开关；现在未完成的不是“服务是否启用”，而是“飞书真实消息入口下是否能稳定复现这条本地已验证的最小链路”。
5. 截至当前代码版本，服务侧已部署 `copilot -i <prompt>` 启动修复并重启到新进程；该修复已通过窄回归和本地 PTY probe 验证，仍待下一条飞书真实入口消息做最终验收。

### 6.4 首轮白名单范围

首轮试验应包含两类最小能力：

1. **最小知识白名单**：
    - `knowledge/common-faults.md`
    - `knowledge/error-codes.md`
    - `knowledge/error-tracing-methods.md`
    - `knowledge/cpu-high.md`
    - 与当前 route 强相关的 1 到 2 个垂直 SOP
2. **最小命令白名单**：仅保留最稳定、最容易判定结果的只读命令。

首轮试验只允许模型调用最稳定、最容易判定结果的只读命令。优先使用当前已经在白名单里的命令：

1. `rostopic echo /robot_state -n1`
2. `rostopic echo /low_level_error -n1`
3. `rosnode list`
4. `rosnode info ...`
5. `lsusb -t`
6. `ip -s -d link show can0`
7. `chronyc sources`
8. `dmesg ...`
9. `journalctl ...`

首轮试验不要放开以下命令族：

1. 带重定向、管道拼接过长、shell 变量替换复杂的命令。
2. 任何写入、重启、修改配置类命令。
3. 高噪声、长时运行、需要交互输入的命令。

### 6.5 最小改造顺序

建议按以下顺序推进，每一步都必须单独验收：

#### 第 1 步：先验证 `read_knowledge` 协议，不验证真实诊断深度

目标：确认 Copilot 在 `amr` 路由下能稳定请求补充 knowledge 文档，系统能回填摘要，最终能收到 `report`。

当前状态：截至 2026-06-11，这一步的本地最小链路已经通过验收。`read_knowledge-only` 探针已能稳定打出 `pty_read_knowledge`，`read_knowledge + report` 最小真链路也已能返回结构化结果；当前待验证的是飞书真实入口是否能复现同样的链路。

验收标准：

1. `provider_trace.log` 出现 `pty_prompt_ready` 与 `pty_session_finish`。
2. `provider_trace.log` 中至少出现一次 `pty_read_knowledge`，并能看到对应的 `path`。
3. `report_payload` 非空。
4. 飞书最终回复不是空回复，不是只重复协议文本，不是假装已经读取知识库。
5. 会话证据中能区分 `knowledge_candidates` 和 `knowledge_read[...]`，而不是把两者混成同一类“参考文档”。

#### 第 2 步：再验证 PTY 命令协议，只允许 1 到 2 条真实取证命令

目标：确认 Copilot 在 `amr` 路由下能稳定输出 `execute`，系统能回填 `result`，最终能收到 `report`。

验收标准：

1. `provider_trace.log` 出现 `pty_prompt_ready` 与 `pty_session_finish`。
2. `pty_session_finish.actions_executed >= 1`。
3. `report_payload` 非空。
4. 飞书最终回复不是认证提示，不是空回复，不是只重复协议文本。

目标：在单个真实 AMR 问题里，只允许模型执行 1 到 2 次只读命令，例如先看 `/low_level_error`，再看 `rosnode list`。

验收标准：

1. 返回内容里能引用真实执行结果，而不是只重复“建议下一步”。
2. `provider_evidence` 中能看到由执行结果生成的证据摘要。
3. 超时、空 report、协议污染比例可接受。

#### 第 3 步：再验证 follow-up 下的 PTY 连续推进

目标：验证“继续后续检查，核对后给我结果”时，模型能基于上一轮 reply、previous evidence，以及必要的 `read_knowledge` / `execute` 再补一次动作，而不是重新讲首轮结论。

验收标准：

1. follow-up 请求仍命中同一会话。
2. provider prompt 中包含“上一轮回复”和 `previous_evidence`。
3. 若上一轮已通过 `read_knowledge` 读取过文档，follow-up provider prompt 应优先展示这些已读文档；只有在没有已读文档时才回退到候选文档。
4. 第二轮 PTY 至少新增一次 `read_knowledge` 或 `execute`，或输出更明确的 report 收束。

### 6.6 建议测试问题

首轮 PTY 试验不要选太开放的问题，优先选“最多需要两步补证就能收束”的问题。推荐测试句式：

1. `看下从机 leefung-t9 当前 /low_level_error 和 rosnode 状态，判断是否存在雷达或底层通信异常。`
2. `只做协议连通性测试：先补一条 knowledge，再根据结果输出 report。`
3. `只做协议连通性测试：先执行一条只读命令，再根据结果输出 report。`

不建议首轮就测这类问题：

1. 需要长时间翻日志或跨多个时间段比对的问题。
2. 需要 bag、launch、系统日志多源交叉验证的问题。
3. 一上来就要求“继续后续所有步骤直到核对完成”的开放式问题。

### 6.7 失败停止条件

出现以下任一情况，应停止扩大 PTY 范围，先修协议或包装层：

1. 真实问题下持续输出 TUI 污染、ANSI 噪声或非结构化文本，无法稳定提取 `execute` / `report`。
2. `pty_session_finish` 经常没有 `report_payload`。
3. 知识补证或命令执行明明成功，但模型无法基于回填结果继续推进。
4. 一次问题内频繁申请 3 次以上 `read_knowledge` 或 `execute`，仍不能收束到 report。

### 6.8 明确不在本阶段做的事

本阶段先不做：

1. 不把固定 `collect.py` 全量替换成“模型自由申请所有动作”。
2. 不引入更宽的 SSH 白名单。
3. 不把 PTY 设为全局默认。
4. 不把真实生产排障完全依赖 PTY。

本阶段目标只有一个：证明 Copilot 在受控知识白名单和命令白名单下，能对单个 AMR 问题稳定完成一次最小 `read_knowledge` / `execute` / `report` 混合闭环。
