# knowledge 目录索引

这个目录保存排障知识库的主入口和分层文档。当前目录结构已经开始按业务域拆开，目标是让开发后续可以直接按层级补 `knowledge/**/*.md`，同时保持编排器和历史会话兼容。

## 目录原则

1. 顶层只保留跨域入口、公共说明和总览文档。
2. 子目录按业务域划分，优先对应真实排障层次，而不是按作者习惯命名。
3. 具体症状页只解决一个明确问题，不要把入口说明、现场步骤和复盘模板混在一起。
4. 文档里优先写日志路径、错误码、取证方法和判定口径。
5. 新增文档优先放入对应子目录；旧的扁平路径只作为兼容别名，不再作为新增目标。

## 当前分层

### 顶层入口

- [system-architecture.md](system-architecture.md)
- [common-faults.md](common-faults.md)
- [error-codes.md](error-codes.md)
- [error-tracing-methods.md](error-tracing-methods.md)
- [log-paths.md](log-paths.md)
- [deployment-ops.md](deployment-ops.md)
- [indv-params-tuning.md](indv-params-tuning.md)
- [cpu-high.md](cpu-high.md)
- [error-code-scene-bag-joint-analysis.md](error-code-scene-bag-joint-analysis.md)
- [error-code-cluster-low-level-link-break.md](error-code-cluster-low-level-link-break.md)
- [error-code-cluster-pallet-handling-failures.md](error-code-cluster-pallet-handling-failures.md)
- [error-code-cluster-location-navigation-failures.md](error-code-cluster-location-navigation-failures.md)
- [error-code-cluster-forklift-pallet-handling-special-cases.md](error-code-cluster-forklift-pallet-handling-special-cases.md)
- [error-code-cluster-mecanum-narrow-aisle-special-cases.md](error-code-cluster-mecanum-narrow-aisle-special-cases.md)
- [error-code-cluster-task-chain-timeout.md](error-code-cluster-task-chain-timeout.md)
- [model-parameter-scene-boundary-joint-analysis.md](model-parameter-scene-boundary-joint-analysis.md)
- [master-slave-redis-http-ros-joint-breakpoint-analysis.md](master-slave-redis-http-ros-joint-breakpoint-analysis.md)

用途：提供全局架构、通用故障入口、错误码和日志追溯总入口。

### `hardware_bus/`

- [hardware_bus/README.md](hardware_bus/README.md)
- [hardware_bus/usb-device-troubleshooting.md](hardware_bus/usb-device-troubleshooting.md)
- [hardware_bus/can-eb-communication-abnormal.md](hardware_bus/can-eb-communication-abnormal.md)

用途：USB、CAN、嵌入式板卡、外设与总线层故障。

### `ros/`

- [ros/README.md](ros/README.md)
- [ros/location-loss.md](ros/location-loss.md)

用途：定位、节点、topic、机器人侧 ROS 运行态问题。

### `network/`

- [network/README.md](network/README.md)
- [network/network-connectivity-failure.md](network/network-connectivity-failure.md)

用途：主从机连通性、WiFi、路由器、SSH、掉线问题。

### `backend/`

- [backend/README.md](backend/README.md)
- [backend/service-timeout.md](backend/service-timeout.md)
- [backend/rcs-backend-service-failure.md](backend/rcs-backend-service-failure.md)
- [backend/python-ros-call-chain-monitoring.md](backend/python-ros-call-chain-monitoring.md)

用途：RCS 后端、服务超时、调用链监控与主从机服务交互问题。

### `task_dispatch/`

- [task_dispatch/README.md](task_dispatch/README.md)
- [task_dispatch/rcs-task-system.md](task_dispatch/rcs-task-system.md)
- [task_dispatch/rcs-task-dispatch-failure.md](task_dispatch/rcs-task-dispatch-failure.md)
- [task_dispatch/fork-pickup-misalignment.md](task_dispatch/fork-pickup-misalignment.md)

用途：任务系统、调度不派发、取放货流程和场景动作问题。

### `cbs/`

- [cbs/README.md](cbs/README.md)
- [cbs/navigation-route-rules.md](cbs/navigation-route-rules.md)

用途：路线、地图、CBS 规划与导航规则。

## 开发补充方式

1. 先判断问题属于哪一层。
2. 直接把新文档补到对应目录下。
3. 如果是新的大类，再先补目录说明或入口文档。
4. 如果会被现有路由命中，再同步更新知识索引和候选文档策略。

建议优先遵循这组映射：

- 机器人硬件/总线/外设：`knowledge/hardware_bus/`
- 机器人 ROS 运行态：`knowledge/ros/`
- 网络与连通性：`knowledge/network/`
- RCS 后端与调用链：`knowledge/backend/`
- 任务系统与动作场景：`knowledge/task_dispatch/`
- 路线与 CBS：`knowledge/cbs/`

## 最小开发规范

后续新增知识文档时，按下面规则判断是否只加 Markdown，还是要同步改代码。

### 1. 只加 Markdown 就可以

满足以下条件时，通常只需要把文档放进对应目录：

1. 文档属于现有业务域之一。
2. 文档只是补充已有知识，不是新增一个大类。
3. 文件名和用户提问关键词比较接近。
4. 允许它先作为普通候选页，不要求首轮稳定高优先级命中。

示例：

- 在 `knowledge/network/` 下新增 `wifi-roaming-instability.md`
- 在 `knowledge/ros/` 下新增 `topic-not-publishing.md`

### 2. 需要同步改知识索引

满足以下任一条件时，新增文档后还应同步更新
[feishu_agent/knowledge/index.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/knowledge/index.py)：

1. 希望某类问题稳定优先命中这篇文档。
2. 文档名和用户实际提问词不完全一致。
3. 这篇文档应该成为某个 route 的默认入口候选之一。
4. 这篇文档属于高频故障，不能只靠文件名弱匹配。

通常要改两类位置：

1. `PLAYBOOK_DOCS`
   作用：补某个 route 的默认入口文档。
2. `match_supporting_docs()`
   作用：补关键词到文档路径的显式映射。

### 3. 需要补兼容别名

满足以下条件时，还应同步更新
[feishu_agent/knowledge/loader.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/knowledge/loader.py)：

1. 旧文档路径已经在历史草稿、旧 prompt、旧会话或外部文档里被引用。
2. 本次是“迁移路径”而不是“新增一篇全新文档”。

这时要把旧路径映射到新路径，避免历史引用直接失效。

### 4. 需要补目录入口页

满足以下条件时，还应同步补对应目录下的 `README.md`：

1. 新增了一个新的业务域目录。
2. 某个目录下的知识页数量明显变多，需要单独说明适用范围和子类划分。

### 5. 推荐开发顺序

后续按下面顺序落地最稳：

1. 先把文档放到正确目录。
2. 再判断它是否属于高频场景。
3. 如果是高频场景，再补 `index.py` 的显式匹配。
4. 如果是旧路径迁移，再补 `loader.py` alias。
5. 最后更新对应目录 `README.md` 或总入口说明。

### 6. 评审时快速判断

可以用这张简表做判断：

- `现有目录下新增普通知识页`：只加 md
- `高频问题页，希望稳定命中`：加 md + 改 `index.py`
- `旧文档改到新目录`：加 md/迁移 + 改 `loader.py`
- `新增业务域`：加目录 + 入口 README + 改 `index.py`

## 目录 README 写法

为了尽量做到“开发只加 md 和目录索引，不改 Python”，建议每个目录 `README.md` 按下面方式维护。

### 1. 必写内容

1. `适用范围`
2. `当前已覆盖文档`
3. `常见检索词`
4. `关联总入口`

其中：

- `当前已覆盖文档` 用 Markdown 链接列出本目录下实际知识页
- `常见检索词` 用用户真实提问里常出现的短语来写

### 2. 常见检索词怎么写

优先写用户在飞书里最可能直接发出来的说法，而不是只写内部术语。

推荐写法：

- 接口超时
- 服务不通
- 掉线
- 叉不到位
- 定位丢失
- WiFi 漫游

不推荐只写：

- 通信异常
- 链路问题
- 模块故障

原因：

1. 这类词太泛，所有文档都可能沾边。
2. 用户真实提问往往更具体。
3. 现在召回层会吃标题、README 和正文里的词，短而具体的短语更容易命中。

### 3. 检索词数量建议

每个目录 `README.md` 的 `常见检索词` 建议先写 `5` 到 `12` 个，不要贪多。

太少：

- 覆盖不够

太多：

- 会把目录入口写得过泛，反而压住具体子页

### 4. 目录索引的推荐顺序

建议按下面顺序组织目录 `README.md`：

1. 适用范围
2. 常见检索词
3. 建议优先补充的子类页
4. 当前已覆盖文档
5. 推荐命名方式
6. 关联总入口

## 文档模板

建议每个具体症状页都按 [TEMPLATE.md](TEMPLATE.md) 结构写，最小字段如下：

```markdown
# 问题标题

## 适用范围
- 说明哪些机器人、机型、版本或场景会出现这个问题。

## 典型现象
- 列出用户最容易描述的症状。

## 优先检查
1. 第一条命令。
2. 第二条命令。
3. 第三条命令。

## 关键日志
- 说明要看哪些日志文件、bag topic 或错误码。

## 常见根因
- 根因 1
- 根因 2

## 处理建议
1. 先做什么。
2. 再做什么。
3. 什么情况下需要停机或人工介入。

## 参考文档
- 指向上一级入口或关联文档。
```

## 编排器如何使用这里的内容

1. 先读 [system-architecture.md](system-architecture.md) 了解总入口和环境边界。
2. 再根据 route 命中对应大类入口。
3. 再从顶层入口文档和子目录文档里挑候选页。
4. 最后按症状、错误码、日志路径或机型进入更细页面。

## 维护建议

- 新增场景时，优先补子目录中的症状页；只有跨域复用时再补顶层入口。
- 如果某个文档出现“什么都写一点”的倾向，就拆成更细的两到三份。
- 如果某个命令会修改系统状态，放回受控执行层，不要放到知识库里当默认步骤。
- 历史扁平路径目前仍可被兼容解析，但后续新增内容不要继续写回旧位置。
- 如果新增文档希望更容易被命中，优先先补目录 `README.md` 的链接和检索词，而不是先改 Python 规则。
