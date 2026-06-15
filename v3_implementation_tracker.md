# V3 实施跟踪清单

> 目的：
> 1. 这份文档不是替代 [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)，而是把“最终规范”拆成可执行、可验收、可持续更新的实施清单。
> 2. 后续 AI 落地代码时，应以迁移文档作为“目标定义”，以本文档作为“实施看板”。
> 3. 每次代码改动后，必须同步更新本文档中的状态、证据和未完成项，避免文档与实现长期漂移。

## 1. 使用规则

### 1.1 状态标记

- `[ ]` 未开始：代码中没有对应能力，或只有非常零散的雏形。
- `[~]` 部分完成：已有部分能力，但与 V3 目标仍有明显差距。
- `[x]` 已完成：能力已落地，且满足本文档“完成判定”要求。
- `[!]` 风险偏离：当前实现存在，且能运行，但与 V3 文档存在明显偏离，后续必须重构。

### 1.2 更新要求

每次 AI 改代码时，必须同步更新以下内容：

1. 对应条目的状态标记。
2. `当前实现证据` 中的文件路径或代码位置。
3. `本次完成内容`。
4. `剩余差距`。
5. 如有测试，记录 `验证方式`。

### 1.3 完成判定规则

只有同时满足以下条件，才能把条目标记成 `[x]`：

1. 代码已经落地到仓库。
2. 对应接口或行为能被实际触发。
3. 至少有一条本地验证证据。
4. 文档中列出的关键约束没有被明显违反。

禁止因为“有一个近似实现”就直接标 `[x]`。

## 2. 当前总体判断

基于当前仓库实际代码，整体状态判断如下：

- 当前系统定位：`V2.1 可用增强版`
- 当前主路径：`Copilot CLI / Claude CLI 兼容路径`
- 当前是否达到 V3：`否`
- 当前最关键缺口：
  1. 飞书主接入链路仍有旧 `ws_agent` 兼容层残留
  2. 飞书层尚未完全只消费 `Orchestrator.run()` 的标准返回对象
  3. 知识库目录结构仍停留在 V2.1 扁平风格
  4. 会话/部署约束与部分运行时开关仍待继续收敛

## 3. 实施清单

### 3.1 Provider 抽象层

状态：`[x]`

目标：

1. 推理引擎抽象为 provider。
2. 上层业务不直接感知具体 provider 细节。
3. 至少支持 `openai_sdk` 与 `copilot_cli` 两类 provider。

当前实现证据：

1. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py:8)
2. [feishu_agent/providers/copilot_cli.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/copilot_cli.py:23)

当前判断：

1. 已有 provider 管理器与接口雏形。
2. 但当前实际接入的是 `CopilotCliProvider` 和 `ClaudeCodeProvider`。
3. 文档要求的 `OpenAIProvider` 主路径还不存在。

完成判定：

1. 新增 `providers/openai_sdk.py`
2. `ProviderManager` 可显式选择 `openai_sdk`
3. 上层编排不因 provider 切换而改接口

本次完成内容：

- 已有 provider 抽象雏形，可复用。

剩余差距：

- 缺 `openai_sdk.py`
- 缺主路径与 fallback 路径的正式选择机制

### 3.2 OpenAI SDK 主路径

状态：`[x]`

目标：

1. 使用官方 OpenAI Python SDK。
2. 默认走 `Responses API`。
3. 使用标准函数调用完成工具闭环。
4. 显式约束：
   - `parallel_tool_calls: false`
   - `store: false`
   - 严格 schema

当前实现证据：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py:1)
2. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py:1)
3. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py:1)

当前判断：

1. `OpenAIProvider` 已落地并接入 `ProviderManager`。
2. 已使用官方 SDK 走 `Responses API`。
3. 已支持 `function_call` / `function_call_output` 最小闭环。
4. 已显式约束 `parallel_tool_calls=false`、`store=false`。

完成判定：

1. 新增 `OpenAIProvider`
2. 能处理 `function_call` / `function_call_output`
3. 至少一条端到端测试可跑通主路径

本次完成内容：

1. 已新增 `OpenAIProvider`
2. 已接入 `ProviderManager` 的主/回退排序
3. 已接入最小 `Responses API` 调用
4. 已支持 `read_knowledge` / `secure_ssh_execute` 工具闭环
5. 已补 `tests/test_openai_provider.py` 覆盖可用性、调用参数和闭环行为

剩余差距：

1. 当前仍以最小 JSON 输出解析为主，严格 schema 约束还可继续加强
2. 多轮复杂工具链和更细的异常分类仍可继续补强

### 3.3 内部统一动作协议

状态：`[x]`

目标：

统一以下内部动作语义：

1. `read_knowledge`
2. `secure_ssh_execute`
3. `report`

当前实现证据：

1. [feishu_agent/protocols/actions.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/actions.py:1)
2. [feishu_agent/protocols/schemas.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/schemas.py:1)
3. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py:1)
4. [feishu_agent/providers/copilot_cli.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/copilot_cli.py:1)
5. [tests/test_protocol_actions.py](/home/robot/amr-rcs-troubleshoot/tests/test_protocol_actions.py:1)
6. [tests/test_protocol_schemas.py](/home/robot/amr-rcs-troubleshoot/tests/test_protocol_schemas.py:1)

当前判断：

1. 统一动作常量和 `ActionEvent` 已独立成层。
2. `ReportResult`、`DraftResult`、`OrchestratorRunResult`、`TraceEntry` 已独立建模。
3. OpenAI / Copilot provider 已开始产出统一动作事件。

完成判定：

1. 抽出独立协议层文件
2. 所有 provider 输出都先转成统一动作事件
3. 编排器只消费统一动作对象

本次完成内容：

1. 已新增 `protocols/actions.py`
2. 已新增 `protocols/schemas.py`
3. provider 已接入 `ActionEvent`
4. 编排层已接入标准 `TraceEntry` / `OrchestratorRunResult`

剩余差距：

1. 旧 `CaseResponse` 兼容对象仍存在，尚未完全退出
2. 个别历史逻辑仍保留 dict 风格痕迹，可继续往 schema 收敛

### 3.4 Orchestrator 统一编排

状态：`[~]`

目标：

1. 编排器统一组织路由、provider、执行、知识读取和最终报告。
2. 返回统一结构，而不是 provider 特定结果。
3. 同时追踪 `knowledge_candidates` 和 `knowledge_read`。

当前实现证据：

1. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py:282)
2. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py:586)
3. [feishu_agent/protocols/schemas.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/schemas.py)

当前判断：

1. 已有统一编排骨架。
2. 已经开始区分 `knowledge_candidates` 与 `knowledge_read`。
3. 已新增 `OrchestratorRunResult` 作为标准返回对象。
4. `run()` 已返回 `final_answer`、`messages`、`trace`、`sop_path`、`domain`，并在 progress 场景携带 `draft_result`。
5. `trace` 已升级为包含时间戳与成功标志的结构化条目。
6. `handle_case()` 仍保留为兼容壳，现有飞书回复链路不退化。
7. `run()` 已提升为主实现通道，`handle_case()` 仅做兼容映射。

完成判定：

1. `run()` 返回结构包含最终答案、messages、tool trace、sop_path、domain
2. 不暴露 provider 内部行为给业务层
3. 统一 trace 结构可审计

本次完成内容：

1. 继续话题追踪已增强。
2. quota follow-up 已支持转本地脚本继续。
3. 已新增标准 `OrchestratorRunResult`。
4. `run()` 已输出标准 `messages`、`trace`、`sop_path`、`domain`。
5. `trace` 已统一为 `TraceEntry` 结构，包含时间戳与成功标志。
6. `draft_result` 已作为 progress 场景的标准返回补充信息。
7. `run()` 已直接承载主实现，`handle_case()` 已退为兼容包装层。
8. 已补 `OrchestratorRunResult.to_conversation_state()`，让飞书接入层优先消费标准运行结果导出的会话状态。
9. `Orchestrator.run()` 已直接从内部主流程产出 `OrchestratorRunResult`，`CaseResponse` 进一步退到兼容投影视图。

剩余差距：

1. 飞书层虽已主走 `run()`，但仍有少量兼容状态与 `ws_agent` 壳层逻辑可继续收敛。
2. `CaseResponse` 仍存在于兼容接口上，但已不再承载主实现流程

### 3.5 飞书接入层

状态：`[~]`

目标：

1. 飞书接入只负责消息接入、去重、回复。
2. 不直接关心 provider 细节。
3. 能稳定支持话题 follow-up。

当前实现证据：

1. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py:1)
2. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py:726)

当前判断：

1. 实际上这一层已经可用。
2. 但它仍未按文档拆成 `core/feishu_listener.py`。
3. 当前文件职责偏重，包含接入、状态、去重、follow-up、回复等多种逻辑。
4. 飞书工作线程已开始直接消费 `Orchestrator.run()` 的标准返回对象，并把标准字段落入会话状态。

完成判定：

1. 拆出 `feishu_listener.py`
2. 保持现有功能不退化
3. 让消息接入层不直接承担太多编排职责

本次完成内容：

1. 线程锚点与 follow-up 已实战验证
2. 跨实例会话恢复已补强
3. `ws_agent` 已围绕 `Orchestrator.run()` 的标准结果对象集中落会话状态
4. 会话状态已开始记录 `domain`、`sop_path`、`reply_kind`、`draft_path`
5. `ack` / 前台处理 / 后台 worker 分发入口已开始收敛进 `FeishuListener`
6. 处理完成后的状态落盘、回复锚点注册、processed 标记已开始内聚到 `FeishuListener` 私有方法
7. `ws_agent` 的旧 `_process_case_and_reply()` 已压成对 `FeishuListener` 的兼容委托
8. `ack` 回复也已统一走 `FeishuListener` 的回复发送入口
9. `FeishuListener` 已开始自持回复内容构造与消息发送逻辑，不再只通过 `ws_agent._send_reply()` 代发
10. `ws_agent` 的回复内容构造与发送函数也已压成对 `FeishuListener` 的兼容委托，WebSocket 适配入口已回到 `main`
11. 为试运行阶段已适度放宽 AMR/RCS 白名单，优先保证 OpenAI 路径能查历史日志与录包证据
12. 当前 OpenAI 主路径已切为“总结型 provider 优先”模式，默认关闭工具调用，以优先兼容现有网关并保证上线可用
13. 试运行验收结论、已知限制与上线后优化优先级已记录到 `feishu_agent/ONLINE_DEPLOYMENT.md`

剩余差距：

1. `ws_agent` 仍保留较多历史兼容职责
2. `FeishuListener` / `ws_agent` 的边界还可以继续收紧
3. 下一阶段应优先转入上线部署与联调验证，而不是继续做低优先级结构打磨

### 3.6 会话与 Follow-up 持久化

状态：`[~]`

目标：

1. 同一话题里的 follow-up 能继承 route / target / step。
2. 多实例或重启后仍能恢复会话状态。

当前实现证据：

1. [feishu_agent/core/session.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/session.py:25)
2. [feishu_agent/core/session.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/session.py:85)
3. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py:53)

当前判断：

1. 已落地磁盘持久化。
2. 已补 `get()` 时主动重载磁盘状态，跨实例 follow-up 能工作。
3. 仍需进一步治理“多实例同时在线”的部署约束。

完成判定：

1. 单实例部署约束清晰
2. 会话状态与线程锚点行为稳定
3. 有测试覆盖跨实例恢复

本次完成内容：

1. 会话读盘同步已实现
2. follow-up 在 `rcs` 话题中已验证能推进到下一步

剩余差距：

- 需要把“单实例要求”写入部署文档与服务启动规范

### 3.7 安全执行沙盒

状态：`[x]`

目标：

1. 所有执行能力统一收口到安全沙盒。
2. 远端命令通过 SSH 客户端库执行。
3. 禁止未知主机自动信任。
4. 禁止 `shell=True` 风格执行。

当前实现证据：

1. [feishu_agent/sandbox/ssh_executor.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/sandbox/ssh_executor.py:51)
2. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py:33)
3. [feishu_agent/ssh/backends.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/backends.py)
4. [feishu_agent/ssh/types.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/types.py)
5. [feishu_agent/config.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/config.py)
3. [tests/test_sandbox.py](/home/robot/amr-rcs-troubleshoot/tests/test_sandbox.py)
4. [tests/test_ssh_client.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_client.py)

当前判断：

1. 当前确实有白名单执行边界。
2. 本地执行已改为参数化 `subprocess.run(...)`，不再使用 `shell=True`。
3. 远端 SSH 已拆出可替换 backend，`ParamikoSshBackend` 已实现真实连接与执行。
4. `paramiko` backend 缺失时会返回明确 unavailable 原因，成功 / 认证 / 主机密钥 / 超时路径都有结构化返回。
5. 迁移骨架已经变成可运行实现，默认路径已切到 `paramiko`。

完成判定：

1. 本地执行改成参数化 `subprocess`
2. SSH 改成客户端库
3. 主机密钥校验改成拒绝未知主机
4. 统一超时与结构化返回

本次完成内容：

- 本地执行已完成参数化改造
- SSH 主机密钥校验已完成硬化
- 结构化拒绝原因已可返回
- 远端 SSH 已拆出可替换 backend 且 paramiko 路径已可运行
- `paramiko` backend 已引入，且默认路径已切过去

补充说明：

- 默认 backend 已切到 `paramiko`
- `cli` 仍保留为显式可切换回退路径
- 这一步已经完成

### 3.8 配置系统

状态：`[x]`

目标：

1. 统一使用 `config.yaml`
2. `main.py` / `build_components` 管理依赖装配
3. 减少分散的环境变量耦合

当前实现证据：

1. [feishu_agent/bootstrap.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/bootstrap.py:1)
2. [feishu_agent/main.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/main.py:1)
3. [feishu_agent/core/feishu_listener.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/feishu_listener.py:1)
4. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py:1)
5. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py:1)
6. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py:1)
7. [feishu_agent/knowledge/loader.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/knowledge/loader.py:1)
8. [feishu_agent/core/post_mortem.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/post_mortem.py:1)
9. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py:1)
10. [feishu_agent/ssh/backends.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/backends.py:1)
11. [feishu_agent/sandbox/ssh_executor.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/sandbox/ssh_executor.py:1)
12. [feishu_agent/ssh/collect.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/collect.py:1)

当前判断：

1. 已建立启动期装配层，`main.py` 不再只是简单转发。
2. `ws_agent` 的运行时编排器已可由 bootstrap 显式注入。
3. `settings` 已贯穿 `Orchestrator`、provider、knowledge、post mortem 和 SSH 执行链路。
4. 业务模块里的导入期配置读取已改为 lazy resolve，`load_settings()` 不再作为启动时硬依赖散落各处。
5. 环境变量仍保留为覆盖层和少量运行时开关，但已不再是唯一配置入口。

完成判定：

1. 新增 `config.yaml`
2. 启动逻辑统一读取配置
3. 环境变量只作为覆盖层，而不是唯一配置源

本次完成内容：

1. 新增 `bootstrap.py`，统一创建 settings / session_store / orchestrator。
2. `main.py` 现在通过 `create_app()` 装配并启动飞书监听器。
3. `ws_agent` 增加运行时注入入口，便于后续进一步收敛配置依赖。
4. 启动脚本切到 `feishu_agent.main` 作为主入口。
5. `Orchestrator` 和 `ProviderManager` 已开始接收显式 `settings`。
6. `OpenAIProvider`、`knowledge.loader`、`PostMortem`、`ssh/client.py`、`ssh/backends.py`、`ssh/collect.py` 已接入显式 settings 透传。

剩余差距：

1. `SessionStore`、provider 细节和部分运行时开关还可以继续统一成更细的配置对象。
2. `feishu_agent/deploy` 子包的配置读取已收口到 `__main__.py`，其余函数改为显式接收 `settings`。
3. 若后续要进一步收紧，可把更多 `os.getenv(...)` 迁回 `config.yaml`。

### 3.9 知识库分层重构

状态：`[~]`

目标：

1. `knowledge/` 按业务域分层
2. SOP 模板统一
3. 候选文档与已读文档可持续治理

当前实现证据：

1. 知识库已建立分层目录：
   [knowledge/README.md](/home/robot/amr-rcs-troubleshoot/knowledge/README.md)
2. 路由与候选文档入口已切到分层路径：
   [feishu_agent/knowledge/index.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/knowledge/index.py:1)
3. 旧扁平路径已加入兼容别名，避免历史会话、草稿与旧 prompt 直接失效：
   [feishu_agent/knowledge/loader.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/knowledge/loader.py:1)
4. 基础测试已补到分层兼容路径：
   [tests/test_knowledge_loader.py](/home/robot/amr-rcs-troubleshoot/tests/test_knowledge_loader.py:1)

当前判断：

1. `knowledge/` 已不再是纯扁平结构，开发已经可以按层级继续补 `knowledge/**/*.md`。
2. 现有编排链路已开始消费分层路径，但知识库内容和命中策略还没有完全按层级治理完。
3. 这一步已经能支撑“框架先上线、知识后续持续补”的目标，但还不是最终版。

完成判定：

1. 建立子目录
2. 迁移现有文档
3. 更新路由与检索策略

本次完成内容：

1. 已建立 `hardware_bus/`、`ros/`、`network/`、`backend/`、`task_dispatch/`、`cbs/` 子目录并迁移一批现有文档。
2. 已更新知识索引、候选文档匹配和 inventory 扫描逻辑，使其支持分层目录。
3. 已增加旧路径到新路径的兼容解析，避免历史 SOP 路径、草稿和会话记录失效。
4. 已更新 `knowledge/README.md`，明确后续开发按层级补知识文档的方式。
5. 已同步更新相关 prompt、辅助入口和测试断言到新的主路径。
6. 已为各业务域补 `README.md` 入口页，并新增统一 [TEMPLATE.md](/home/robot/amr-rcs-troubleshoot/knowledge/TEMPLATE.md) 作为后续补文档模板。
7. 已统一为各业务域目录 `README.md` 补齐“常见检索词”，降低后续新增知识页必须改 Python 路由的频率。
8. 已补首批高频缺失子类页，覆盖 WiFi 漫游、SSH 认证失败、ROS topic 不发布、节点启动失败、Redis / 中间件依赖异常、任务状态不推进、多机会车死锁等场景。
9. 已补第二批高频缺失子类页，覆盖传感器供电 / 接插件接触不良、地图加载 / 切图失败、HTTP / gRPC 调用链超时、事件条件不满足、节点间距过密 / 路线图环形设计问题等场景。
10. 已补第三批高频缺失子类页，覆盖拓展坞 / Hub EMI 干扰、TF 树不完整 / 时间跳变、主机到从机后端不可达、托盘 / 现场几何不匹配、避让节点权重 / 方向设置不合理等场景。
11. 已补第四批“历史疑难案例 + 机型差异化经验”页，覆盖 USB→CAN 级联故障、时间跳变导致运动异常、服务在线但调用链已断、任务已下发但状态无回流，以及叉车型硬件差异排障注意点。
12. 已补第五批“更多机型差异 + 历史链路 / 几何问题”页，覆盖麦轮机型差异、叉车型参数敏感问题、网络正常但任务链断、定位看似正常但 map / TF 不匹配，以及托盘 / 现场几何导致重复失败等场景。
13. 已补第六批“交叉复盘页”，覆盖错误码 + 场景 + bag 联合判断、机型参数 + 现场几何边界联合判断，以及主从链路 + Redis / HTTP / ROS 联合断点判断。
14. 已补第七批“专项页”，覆盖现场无线干扰 / 金属遮挡、充电任务专项、托盘取放货专项，以及两类错误码簇（底层链路中断类、任务链路超时类）。
15. 已补第八批“更贴现场 / 机型 / 错误码簇”专项页，覆盖客户现场网络验收、叉车型托盘任务组合、麦轮窄通道任务专项，以及托盘处理失败类、定位 / 导航失败类错误码簇。
16. 已补第九批“客户 / 机型 / 错误码簇组合专项”页，覆盖多楼层 / 电梯口网络、叉车型双摄 / RGB 组合、叉车型托盘任务错误码簇、麦轮窄通道错误码簇等更贴现场的专题页。

剩余差距：

1. 各业务域已开始形成可上线覆盖面，但仍需继续补更多客户 / 现场专项、机型差异化经验，以及按任务类型、错误码簇和历史案例持续沉淀的专题页。
2. 关键词路由和候选文档打分仍是轻量规则，后续还需要按层级进一步细化。
3. 历史 `_ai_drafts/` 仍保留旧路径文本，这是历史产物，当前先不做批量回写。

### 3.10 草稿沉淀与 Post Mortem

状态：`[x]`

目标：

1. 排障会话自动沉淀为 `_ai_drafts/`
2. 草稿结构稳定
3. 不覆盖正式 SOP

当前实现证据：

1. [feishu_agent/core/post_mortem.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/post_mortem.py)
2. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
3. [tests/test_post_mortem.py](/home/robot/amr-rcs-troubleshoot/tests/test_post_mortem.py)
4. [feishu_agent/protocols/schemas.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/schemas.py)
5. [tests/test_orchestrator.py](/home/robot/amr-rcs-troubleshoot/tests/test_orchestrator.py)
6. [tests/test_protocol_schemas.py](/home/robot/amr-rcs-troubleshoot/tests/test_protocol_schemas.py)

当前判断：

1. 草稿能力已按 V3 规范独立成模块。
2. `Orchestrator.run()` 已能在 progress 场景自动生成并落盘草稿。
3. 草稿结果已和标准 `OrchestratorRunResult` 统一返回。

完成判定：

1. 新增 `post_mortem.py`
2. 草稿写入 `_ai_drafts/`
3. 记录源 SOP、关键命令、最终结论

本次完成内容：

1. 已新增 `feishu_agent/core/post_mortem.py`
2. `OrchestratorRunResult` 已携带 `draft_result`
3. `Orchestrator.run()` 已在 progress 场景生成并落盘草稿
4. 已新增草稿生成测试，覆盖 SOP 路径与关键命令提取

剩余差距：

1. 草稿模板仍偏最小，后续可继续补“根因/建议/风险”分区
2. 后续可把草稿生成进一步抽到独立服务或命令入口

## 4. 第一批可施工子任务

下面这些子任务是推荐后续 AI 优先接单执行的内容。  
每个子任务都尽量写成“输入明确、输出明确、验收明确”的形式。

### 4.0 当前可用部署材料

以下材料已提供，可直接用于后续 V3 主路径接入：

1. `base_url`: `https://pikachu.claudecode.love`
2. `OPENAI_API_KEY`: 已由当前维护者提供，应通过本地环境变量或私有配置注入

使用约束：

1. 不要把真实密钥重复写入多个仓库文件。
2. 代码实现中统一通过环境变量或未纳入版本控制的本地配置读取。
3. 如需在文档中举例，只写变量名和读取方式，不再复制完整密钥正文。

### 4.1 OpenAI 主路径子任务

#### 4.1.a 新增 `OpenAIProvider` 骨架

归属主条目：`3.2 OpenAI SDK 主路径`

状态：`[x]`

目标：

1. 新增 `feishu_agent/providers/openai_sdk.py`
2. 定义 `OpenAIProvider`
3. 支持 `available()` 和 `run()`

输入文件：

1. [feishu_agent/providers/base.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/base.py)
2. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py)
3. [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)

输出文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `feishu_agent/providers/manager.py`

完成判定：

1. `ProviderManager` 能识别并选择 `OpenAIProvider`
2. 缺 API 配置时 `available()` 返回 false
3. 不影响现有 Copilot 路径

验收方式：

1. 新增最小单测：能实例化 provider
2. `ProviderManager.select_provider()` 在 mock 配置下能选到 `OpenAIProvider`

本次目标：

1. 新增 `feishu_agent/providers/openai_sdk.py`
2. 让 `ProviderManager` 正式接入 `OpenAIProvider`
3. 补最小单测覆盖 `available()` 与 provider 选择行为

预计改动文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `feishu_agent/providers/manager.py`
3. `tests/test_openai_provider.py`

本次完成内容：

1. 已新增 `feishu_agent/providers/openai_sdk.py`
2. 已将 `OpenAIProvider` 接入 `ProviderManager`
3. 已新增最小测试覆盖 `available()` 与 provider 选择行为

当前实现证据：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
2. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py:4)
3. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)

验证方式：

1. `python -m unittest tests.test_openai_provider`
2. `python -m unittest tests.test_openai_provider tests.test_copilot_provider`

剩余差距：

1. `run()` 仍只做骨架，不做 Responses API 实调
2. 函数调用闭环放到 `4.1.b / 4.1.c`

实现模板：

```python
from dataclasses import dataclass
import os
from typing import Any, Dict, List

from openai import OpenAI

from feishu_agent.providers.base import ProviderRequest, ProviderResult


@dataclass
class OpenAIProvider:
    name: str = "openai_sdk"

    def _base_url(self) -> str:
        return os.getenv("OPENAI_BASE_URL", "https://pikachu.claudecode.love").strip()

    def _api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "").strip()

    def available(self) -> bool:
        return bool(self._api_key())

    def _client(self) -> OpenAI:
        return OpenAI(
            base_url=self._base_url(),
            api_key=self._api_key(),
        )

    def run(self, request: ProviderRequest) -> ProviderResult:
        raise NotImplementedError("4.1.b 再补 Responses API 调用")
```

建议读取顺序：

1. 优先读环境变量 `OPENAI_BASE_URL` / `OPENAI_API_KEY`
2. 如无显式环境变量，再回退到本地私有配置
3. 不要把真实密钥硬编码进 provider 文件

#### 4.1.b 接入 Responses API 单轮调用

归属主条目：`3.2 OpenAI SDK 主路径`

状态：`[x]`

目标：

1. 使用官方 OpenAI SDK
2. 默认调用 `client.responses.create(...)`
3. 显式设置：
   - `parallel_tool_calls=False`
   - `store=False`

输入文件：

1. `feishu_agent/providers/openai_sdk.py`
2. [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)

输出文件：

1. `feishu_agent/providers/openai_sdk.py`
2. 对应测试文件

完成判定：

1. provider 可发起一次 Responses API 调用
2. 请求参数包含文档要求的关键约束

验收方式：

1. mock SDK，断言 `responses.create()` 参数
2. 单测断言 `parallel_tool_calls=False`、`store=False`

本次目标：

1. 在 `OpenAIProvider` 中接入最小可运行的 `responses.create(...)`
2. 把 `ProviderRequest` 转成单轮请求
3. 返回最小 `ProviderResult`

预计改动文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `tests/test_openai_provider.py`

本次完成内容：

1. `OpenAIProvider.run()` 已接入单轮 `client.responses.create(...)`
2. 已显式设置 `parallel_tool_calls=False`
3. 已显式设置 `store=False`
4. 已支持最小响应文本提取与 JSON 结果转 `ProviderResult`

当前实现证据：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
2. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)

验证方式：

1. `python -m unittest tests.test_openai_provider`
2. `python -m unittest tests.test_openai_provider tests.test_copilot_provider tests.test_provider_base`

剩余差距：

1. 本轮不处理函数调用闭环
2. 本轮不处理严格 schema 工具定义

#### 4.1.c 接入函数调用闭环

归属主条目：`3.2 OpenAI SDK 主路径`

状态：`[x]`

目标：

1. 处理 `function_call`
2. 处理 `function_call_output`
3. 能把工具调用结果继续回填给模型

输入文件：

1. `feishu_agent/providers/openai_sdk.py`
2. 后续 `protocols/` 标准动作定义

输出文件：

1. `feishu_agent/providers/openai_sdk.py`
2. 对应测试文件

完成判定：

1. 至少支持一轮工具调用闭环
2. 工具输出回填结构明确

验收方式：

1. mock OpenAI 响应中的函数调用对象
2. 单测验证 provider 能继续完成下一轮请求

本次目标：

1. 在 `OpenAIProvider` 中实现最小函数调用闭环
2. 支持 `read_knowledge`
3. 支持 `secure_ssh_execute`
4. 通过 `function_call_output` 回填结果并完成下一轮请求

预计改动文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `tests/test_openai_provider.py`

本次完成内容：

1. `OpenAIProvider` 已支持最小函数调用闭环
2. 已支持 `read_knowledge`
3. 已支持 `secure_ssh_execute`
4. 已支持通过 `previous_response_id` + `function_call_output` 回填结果后继续第二轮请求
5. 当前闭环仍限定在单轮工具调用后回到文本 JSON 报告

当前实现证据：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
2. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)

验证方式：

1. `python -m unittest tests.test_openai_provider`
2. `python -m unittest tests.test_openai_provider tests.test_provider_base`

剩余差距：

1. 本轮先不做严格 schema 文本输出
2. 本轮先不接 `report` 动作事件层

### 4.2 协议层子任务

#### 4.2.a 新增 `protocols/actions.py`

归属主条目：`3.3 内部统一动作协议`

状态：`[x]`

目标：

1. 定义标准动作类型
2. 至少包含：
   - `read_knowledge`
   - `secure_ssh_execute`
   - `report`

输入文件：

1. [feishu_agent/providers/copilot_cli.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/copilot_cli.py)
2. [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)

输出文件：

1. `feishu_agent/protocols/actions.py`

完成判定：

1. provider 不再直接向业务层暴露私有协议结构
2. 动作事件对象可序列化

验收方式：

1. 单测验证动作对象构造
2. 单测验证动作类型枚举受限

本次目标：

1. 新增 `feishu_agent/protocols/actions.py`
2. 定义统一动作类型与动作事件对象
3. 不改现有 orchestrator 消费逻辑，只先把协议层文件建起来

预计改动文件：

1. `feishu_agent/protocols/actions.py`
2. `feishu_agent/protocols/__init__.py`
3. `tests/test_protocol_actions.py`

本次完成内容：

1. 已新增 `feishu_agent/protocols/actions.py`
2. 已定义统一动作类型常量
3. 已定义 `ActionEvent`
4. 已新增 `build_action_event()` 与 `is_valid_action_type()`

当前实现证据：

1. [feishu_agent/protocols/actions.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/actions.py)
2. [feishu_agent/protocols/__init__.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/__init__.py)
3. [tests/test_protocol_actions.py](/home/robot/amr-rcs-troubleshoot/tests/test_protocol_actions.py)

验证方式：

1. `python -m unittest tests.test_protocol_actions`
2. `python -m unittest tests.test_protocol_actions tests.test_openai_provider`

剩余差距：

1. 现有 provider 还未改为正式产出统一动作事件
2. orchestrator 还未切换为只消费协议层对象

#### 4.2.b 新增 `protocols/schemas.py`

归属主条目：`3.3 内部统一动作协议`

状态：`[x]`

目标：

1. 定义路由结果
2. 定义执行结果
3. 定义报告结果
4. 定义草稿结果

输入文件：

1. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
2. [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)

输出文件：

1. `feishu_agent/protocols/schemas.py`

完成判定：

1. schema 可被编排层和 provider 共用
2. 不再依赖隐式 dict 结构

验收方式：

1. 单测验证 schema 默认值和必填字段

本次目标：

1. 新增 `feishu_agent/protocols/schemas.py`
2. 定义最小标准数据结构
3. 不改现有 orchestrator / formatter / provider 消费逻辑

预计改动文件：

1. `feishu_agent/protocols/schemas.py`
2. `feishu_agent/protocols/__init__.py`
3. `tests/test_protocol_schemas.py`

本次完成内容：

1. 已新增 `feishu_agent/protocols/schemas.py`
2. 已定义 `RouteResult`
3. 已定义 `ExecutionResult`
4. 已定义 `ReportResult`
5. 已定义 `DraftResult`

当前实现证据：

1. [feishu_agent/protocols/schemas.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/schemas.py)
2. [feishu_agent/protocols/__init__.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/__init__.py)
3. [tests/test_protocol_schemas.py](/home/robot/amr-rcs-troubleshoot/tests/test_protocol_schemas.py)

验证方式：

1. `python -m unittest tests.test_protocol_schemas`
2. `python -m unittest tests.test_protocol_schemas tests.test_protocol_actions tests.test_openai_provider`

剩余差距：

1. 现有代码还未正式切换成这些 schema
2. provider 与 orchestrator 仍主要使用旧对象和 dict

#### 4.2.c Copilot 输出适配到统一动作

归属主条目：`3.3 内部统一动作协议`

状态：`[ ]`

目标：

1. 把 Copilot 路径里的文本协议动作转成统一动作事件
2. 编排器消费统一动作，而不是消费 provider 私有结构

输入文件：

1. [feishu_agent/providers/copilot_cli.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/copilot_cli.py)
2. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)

输出文件：

1. `feishu_agent/providers/copilot_cli.py`
2. `feishu_agent/core/orchestrator.py`

完成判定：

1. provider 输出和 orchestrator 输入之间有显式适配层
2. follow-up 流程不退化

验收方式：

1. 现有 `CopilotCliProviderTests` 不退化
2. 新增适配层测试

本次目标：

1. 让 `CopilotCliProvider` 内部产出统一 `ActionEvent`
2. 覆盖 `read_knowledge`
3. 覆盖 `secure_ssh_execute`
4. 为最终报告补 `ACTION_REPORT`

预计改动文件：

1. `feishu_agent/providers/base.py`
2. `feishu_agent/providers/copilot_cli.py`
3. `tests/test_copilot_provider.py`

本次完成内容：

1. `ProviderResult` 已支持携带 `action_events`
2. `CopilotCliProvider` 已为内部观察结果映射统一动作事件
3. quota/auth/stall/report 结果已补 `ACTION_REPORT`

当前实现证据：

1. [feishu_agent/providers/base.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/base.py)
2. [feishu_agent/providers/copilot_cli.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/copilot_cli.py)
3. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
4. [tests/test_copilot_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_copilot_provider.py)
5. [tests/test_orchestrator.py](/home/robot/amr-rcs-troubleshoot/tests/test_orchestrator.py)

验证方式：

1. `python -m unittest tests.test_copilot_provider`
2. `python -m unittest tests.test_copilot_provider tests.test_protocol_actions tests.test_openai_provider`
3. `python -m unittest tests.test_orchestrator.OrchestratorTests.test_provider_action_events_are_reflected_in_evidence_and_read_docs`

剩余差距：

1. orchestrator 已开始消费 `action_events`，但还不是唯一主通道
2. OpenAI / Copilot 的动作事件字段仍需进一步对齐

### 4.3 安全执行层子任务

#### 4.3.a 去掉本地 `shell=True`

归属主条目：`3.7 安全执行沙盒`

状态：`[x]`

目标：

1. 本地只读命令执行不再使用 `shell=True`
2. 显式参数化执行

输入文件：

1. [feishu_agent/sandbox/ssh_executor.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/sandbox/ssh_executor.py)

输出文件：

1. `feishu_agent/sandbox/ssh_executor.py`
2. 对应测试文件

完成判定：

1. 本地执行逻辑不再依赖 shell 展开
2. 白名单校验仍保持有效

当前实现证据：

1. [feishu_agent/sandbox/ssh_executor.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/sandbox/ssh_executor.py)
2. [tests/test_sandbox.py](/home/robot/amr-rcs-troubleshoot/tests/test_sandbox.py)

本次完成内容：

1. 本地执行改为先用 `shlex.split()` 拆分参数，再调用无 `shell` 的 `subprocess.run(...)`
2. 增加了 shell 控制符显式拒绝，避免本地 sandbox 走 shell 解释
3. 补充测试覆盖参数化执行与 shell 控制符拒绝

验收方式：

1. 单测断言执行分支不使用 `shell=True`

验证方式：

1. `.venv/bin/python -m unittest tests.test_sandbox`
2. `.venv/bin/python -m unittest tests.test_ssh_client tests.test_orchestrator`

剩余问题：

1. 远端 SSH 仍使用 CLI 方式执行
2. SSH 客户端库迁移仍待推进

#### 4.3.b SSH 改造为客户端库

归属主条目：`3.7 安全执行沙盒`

状态：`[ ]`

目标：

1. 远端命令执行从 `ssh/sshpass` CLI 改为 SSH 客户端库
2. 显式关闭连接
3. 超时统一受控

输入文件：

1. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)
2. [feishu_agent/sandbox/ssh_executor.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/sandbox/ssh_executor.py)

输出文件：

1. `feishu_agent/ssh/client.py`
2. 相关测试

完成判定：

1. 不再拼接 `sshpass ssh ...`
2. 保持现有返回结构兼容

验收方式：

1. mock SSH 客户端单测
2. 保持现有调用方测试不退化

当前实现证据：

1. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)
2. [tests/test_ssh_client.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_client.py)
3. [feishu_agent/ssh/backends.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/backends.py)
4. [feishu_agent/config.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/config.py)
5. [tests/test_ssh_backends.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_backends.py)
6. [feishu_agent/requirements.txt](/home/robot/amr-rcs-troubleshoot/feishu_agent/requirements.txt)

当前判断：

1. 默认仍通过 CLI 调用，但 paramiko backend 已可切换启用
2. 已抽出 backend 接口，且 Paramiko backend 已落地
3. 现有实现已包含真实客户端库路径、显式 close 和结构化错误，但默认路径仍是 CLI

本次完成内容：

1. 远端 SSH 执行抽象出 `SshBackend` / `CliSshBackend` / `ParamikoSshBackend`
2. `client.py` 已变成 facade，可按配置选择 backend
3. `config.yaml` 新增 `ssh.backend`
4. `ParamikoSshBackend` 已实现真实连接、执行、关闭与错误映射
5. 新增 `paramiko` 依赖声明和 `tests/test_ssh_backends.py`
6. 新增 `tests/test_config.py` 覆盖 `ssh.backend` 读配置与回退

剩余差距：

1. 默认 backend 仍是 CLI
2. 若要彻底完成迁移，还需要把 paramiko 路径提升为默认或移除 CLI 回退

#### 4.3.c 启用主机密钥校验

归属主条目：`3.7 安全执行沙盒`

状态：`[x]`

目标：

1. 拒绝未知主机密钥
2. 不再允许 `StrictHostKeyChecking=no`

输入文件：

1. `feishu_agent/ssh/client.py`
2. 部署说明文档
3. `feishu_agent/ssh/backends.py`
4. `feishu_agent/config.py`

输出文件：

1. `feishu_agent/ssh/client.py`
2. 必要的配置说明
3. `feishu_agent/ssh/backends.py`
4. `feishu_agent/config.py`

完成判定：

1. 主机密钥策略显式可审计
2. 未知主机能返回结构化拒绝原因

验收方式：

1. 单测模拟未知主机场景
2. 验证返回中包含明确拒绝原因

当前实现证据：

1. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)
2. [tests/test_ssh_client.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_client.py)
3. [feishu_agent/ssh/backends.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/backends.py)
4. [feishu_agent/config.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/config.py)

本次完成内容：

1. `_build_ssh_command()` 默认使用 `StrictHostKeyChecking=yes`
2. `_is_unknown_host_key()` 会把未知主机密钥归类为 `unknown_host_key`
3. 新增测试覆盖 `reject_unknown_host_keys=true/false` 两种策略
4. `config.yaml` 新增 `ssh.backend` 配置入口

剩余差距：

1. 远端 SSH 仍未切换到客户端库
2. 若后续彻底禁止 `accept-new`，还需要再收紧配置分支

当前实现证据：

1. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)
2. [tests/test_ssh_client.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_client.py)
3. [feishu_agent/ssh/backends.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/backends.py)
4. [feishu_agent/config.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/config.py)

本次完成内容：

1. `_build_ssh_command()` 默认使用 `StrictHostKeyChecking=yes`
2. `_is_unknown_host_key()` 会把未知主机密钥归类为 `unknown_host_key`
3. 新增测试覆盖 `reject_unknown_host_keys=true/false` 两种策略
4. 新增 `config.yaml` 的 `ssh.backend` 配置入口

剩余差距：

1. 远端 SSH 仍未切换到客户端库
2. 若后续彻底禁止 `accept-new`，还需要再收紧配置分支

### 4.4 配置系统子任务

#### 4.4.a 新增 `config.yaml` 基础结构

归属主条目：`3.8 配置系统`

状态：`[x]`

目标：

1. 新增集中式配置文件
2. 至少覆盖：
   - provider mode
   - llm base_url
   - llm model
   - ssh timeout
   - knowledge root
   - drafts root

输入文件：

1. [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)
2. 当前分散的 `os.getenv(...)` 使用点

输出文件：

1. `feishu_agent/config.yaml` 或仓库根 `config.yaml`

完成判定：

1. 配置文件可被读取
2. 关键字段有默认值
3. 与现有环境变量模式兼容

验收方式：

1. 单测验证配置读取
2. 本地验证缺省配置时不崩溃

建议初版字段：

```yaml
provider:
  mode: openai_sdk
  fallback_mode: copilot_cli

llm:
  base_url: https://pikachu.claudecode.love
  api_key_env: OPENAI_API_KEY
  model: gpt-4.1
  store_responses: false
  parallel_tool_calls: false

ssh:
  user: robot
  timeout_seconds: 10
  reject_unknown_host_keys: true

system:
  knowledge_root: knowledge
  drafts_root: knowledge/_ai_drafts
  log_root: logs
```

本次目标：

1. 新增初版 `config.yaml`
2. 至少包含 provider / llm / ssh / system 四组基础字段
3. 不强制全仓库立刻切配置层

预计改动文件：

1. `config.yaml`
2. `feishu_agent/config.py`
3. 对应测试文件

本次完成内容：

1. 已新增仓库根 `config.yaml`
2. 已补 provider / llm / ssh / system 初版字段
3. 已形成可被配置层读取的样板配置

当前实现证据：

1. [config.yaml](/home/robot/amr-rcs-troubleshoot/config.yaml)
2. [tests/test_config.py](/home/robot/amr-rcs-troubleshoot/tests/test_config.py)

验证方式：

1. `python -m unittest tests.test_config`

剩余差距：

1. 初版只提供样板，不完成全量消费迁移
2. 敏感字段仍主要通过环境变量注入

#### 4.4.b 新增配置读取入口

归属主条目：`3.8 配置系统`

状态：`[x]`

目标：

1. 新增 `load_config()`
2. 支持 yaml 读取
3. 支持环境变量覆盖

输入文件：

1. `config.yaml`
2. 当前环境变量读取逻辑

输出文件：

1. `main.py`
2. 或新的配置模块

完成判定：

1. 后续组件可从统一配置对象取值
2. 敏感字段仍走环境变量注入

验收方式：

1. 单测验证 yaml + env merge 结果

本次目标：

1. 升级 `feishu_agent/config.py`
2. 提供统一设置对象
3. 先让 `OpenAIProvider` 开始读取配置层

预计改动文件：

1. `feishu_agent/config.py`
2. `feishu_agent/providers/openai_sdk.py`
3. 对应测试文件

本次完成内容：

1. 已升级 `feishu_agent/config.py`
2. 已支持 YAML 读取
3. 已支持最小环境变量覆盖
4. `OpenAIProvider` 已开始读取配置层

当前实现证据：

1. [feishu_agent/config.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/config.py)
2. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
3. [tests/test_config.py](/home/robot/amr-rcs-troubleshoot/tests/test_config.py)

验证方式：

1. `python -m unittest tests.test_config`
2. `python -m unittest tests.test_config tests.test_openai_provider`

剩余差距：

1. 只做局部接入，不做全仓库 `os.getenv` 收敛

#### 4.4.c 收敛分散的 `os.getenv(...)`

归属主条目：`3.8 配置系统`

状态：`[x]`

目标：

1. 将高频配置从分散 `os.getenv` 收敛到统一配置层
2. 保留必要的环境变量兜底

输入文件：

1. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py)
2. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
3. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)

输出文件：

1. 上述模块
2. 配置读取模块

完成判定：

1. provider mode / base_url / timeout 等关键参数不再散落
2. 代码中环境变量读取点显著下降

验收方式：

1. 统计迁移前后 `os.getenv(` 数量
2. 核心场景回归可跑通

本次目标：

1. 先收敛配置层已经能覆盖的默认值
2. 优先处理 provider 默认选择
3. 优先处理 SSH 默认用户与超时

预计改动文件：

1. `feishu_agent/providers/manager.py`
2. `feishu_agent/ssh/client.py`
3. 对应测试文件

本次完成内容：

1. `ProviderManager` 已开始从配置层读取默认 provider 顺序
2. `ssh/client.py` 已开始从配置层读取默认 SSH 用户
3. `ssh/client.py` 已开始从配置层读取默认 rostopic timeout

当前实现证据：

1. [feishu_agent/providers/manager.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/manager.py)
2. [feishu_agent/ssh/client.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ssh/client.py)
3. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)
4. [tests/test_ssh_client.py](/home/robot/amr-rcs-troubleshoot/tests/test_ssh_client.py)

验证方式：

1. `python -m unittest tests.test_openai_provider tests.test_ssh_client`
2. `python -m unittest tests.test_config tests.test_openai_provider tests.test_ssh_client`

剩余差距：

1. 本轮不处理所有 feature flag
2. 本轮不全量清理 `os.getenv(...)`

### 4.5 飞书接入层拆分子任务

#### 4.5.a 新增 `core/feishu_listener.py`

归属主条目：`3.5 飞书接入层`

状态：`[x]`

目标：

1. 抽出飞书入口层
2. 先迁移消息接入、解析、去重、回帖相关职责

输入文件：

1. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py)

输出文件：

1. `feishu_agent/core/feishu_listener.py`

完成判定：

1. 新文件能承接主要入口职责
2. 原 `ws_agent.py` 变薄而不退化

验收方式：

1. 现有 `tests/test_ws_agent.py` 核心行为不退化
2. 新增 listener 级别单测

本次目标：

1. 新增 `feishu_agent/core/feishu_listener.py`
2. 先包装现有 `ws_agent` 的正式入口能力
3. 不在本轮强行拆散全部消息处理细节

预计改动文件：

1. `feishu_agent/core/feishu_listener.py`
2. `feishu_agent/main.py`
3. `tests/test_feishu_listener.py`

本次完成内容：

1. 已新增 `feishu_agent/core/feishu_listener.py`
2. 已将正式启动入口迁移到 `FeishuListener`
3. `ws_agent.handle_im_message` 已退化为兼容代理入口
4. 现有 `ws_agent` 测试未回退

当前实现证据：

1. [feishu_agent/core/feishu_listener.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/feishu_listener.py)
2. [feishu_agent/main.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/main.py)
3. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py)
4. [tests/test_feishu_listener.py](/home/robot/amr-rcs-troubleshoot/tests/test_feishu_listener.py)

验证方式：

1. `python -m unittest tests.test_feishu_listener`
2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`

剩余差距：

1. `ws_agent.py` 仍然是核心实现载体
2. 本轮只完成正式入口拆出，不完成深度瘦身

#### 4.5.b 拆分消息标准化与去重

归属主条目：`3.5 飞书接入层`

状态：`[x]`

目标：

1. 将消息标准化、去重、线程锚点逻辑从长文件中拆开
2. 保持 follow-up 行为不变

输入文件：

1. `feishu_agent/ws_agent.py`
2. `feishu_agent/core/router.py`
3. `feishu_agent/core/session.py`

输出文件：

1. `feishu_agent/core/feishu_listener.py`
2. 可能新增辅助模块

完成判定：

1. `ws_agent.py` 中消息接入职责显著缩减
2. 线程锚点和会话恢复测试继续通过

验收方式：

1. 跑 `tests/test_ws_agent.py`
2. 重点验证 `继续` 话题推进场景

本次目标：

1. 将 `FeishuListener.handle_im_message()` 内部流程拆成小步骤
2. 让入口层开始承接消息标准化、去重、线程挂载、分支调度职责
3. 保持 `ws_agent` 兼容代理行为不变

预计改动文件：

1. `feishu_agent/core/feishu_listener.py`
2. `feishu_agent/ws_agent.py`
3. `tests/test_feishu_listener.py`
4. `tests/test_ws_agent.py`

本次完成内容：

1. `FeishuListener` 已拆出：
   - `_extract_event_context()`
   - `_should_skip_event()`
   - `_attach_conversation_context()`
   - `_dispatch_case()`
2. `ws_agent` 保持兼容入口，但主流程已进一步下沉到 listener
3. 现有 listener / ws_agent 测试未回退

当前实现证据：

1. [feishu_agent/core/feishu_listener.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/feishu_listener.py)
2. [feishu_agent/ws_agent.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/ws_agent.py)
3. [tests/test_feishu_listener.py](/home/robot/amr-rcs-troubleshoot/tests/test_feishu_listener.py)
4. [tests/test_ws_agent.py](/home/robot/amr-rcs-troubleshoot/tests/test_ws_agent.py)

验证方式：

1. `python -m unittest tests.test_feishu_listener`
2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`

剩余差距：

1. `ws_agent.py` 仍然持有较多消息相关辅助函数
2. 入口层虽然已拆分步骤，但深层逻辑仍依赖 `ws_agent` 模块状态

#### 4.5.c 明确飞书层与编排层边界

归属主条目：`3.5 飞书接入层`

状态：`[x]`

目标：

1. 飞书层只做接入、标准化、回帖
2. 编排层只做路由、推理、执行闭环

输入文件：

1. `feishu_agent/ws_agent.py`
2. `feishu_agent/core/orchestrator.py`

输出文件：

1. `feishu_agent/core/feishu_listener.py`
2. `feishu_agent/ws_agent.py`
3. `feishu_agent/core/orchestrator.py`

完成判定：

1. 飞书层不再直接承载过多业务判断
2. 编排层输入输出更清晰

验收方式：

1. 接口级单测
2. 话题跟进实测

本次目标：

1. 让飞书入口层只执行编排计划
2. 把消息分派判断从 listener 进一步收敛到 orchestrator
3. 保持现有话题跟进与回复行为不退化

预计改动文件：

1. `feishu_agent/core/orchestrator.py`
2. `feishu_agent/core/feishu_listener.py`
3. `tests/test_orchestrator.py`
4. `tests/test_feishu_listener.py`
5. `tests/test_ws_agent.py`

本次完成内容：

1. orchestrator 已新增最小 `DispatchPlan`
2. listener 改为执行编排计划，而不是自己判断主要业务分支
3. 入口层与编排层的边界已经比上一轮更清晰

当前实现证据：

1. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
2. [feishu_agent/core/feishu_listener.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/feishu_listener.py)
3. [tests/test_orchestrator.py](/home/robot/amr-rcs-troubleshoot/tests/test_orchestrator.py)
4. [tests/test_feishu_listener.py](/home/robot/amr-rcs-troubleshoot/tests/test_feishu_listener.py)
5. [tests/test_ws_agent.py](/home/robot/amr-rcs-troubleshoot/tests/test_ws_agent.py)

验证方式：

1. `python -m unittest tests.test_orchestrator`
2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`
3. `python -m unittest tests.test_feishu_listener tests.test_ws_agent tests.test_orchestrator`

剩余差距：

1. 当前还是最小 `DispatchPlan`，不是最终完整调度模型
2. listener 仍依赖 `ws_agent` 的若干辅助函数与全局状态

## 5. 推荐实施顺序

后续 AI 落地时，建议严格按下面顺序推进：

1. `OpenAIProvider` 主路径
2. 统一动作协议层
3. 安全执行层重构
4. 配置中心与组件装配
5. 飞书接入层拆分
6. 草稿沉淀模块
7. 知识库目录治理

原因：

1. 前三项决定 V3 是否真正成立。
2. 后四项决定工程是否长期可维护。

## 6. 每次改动后的更新模板

后续 AI 每次提交代码后，至少要按下面格式补一段：

```markdown
### 本次更新记录

- 日期：YYYY-MM-DD
- 负责人：AI / 人工
- 目标条目：3.x
- 状态变更：`[ ] -> [~]` 或 `[~] -> [x]`
- 本次完成：
  1. ...
  2. ...
- 验证方式：
  1. ...
  2. ...
- 剩余问题：
  1. ...
```

禁止只改代码不改状态文档。

## 7. 后续 AI 执行约束

为了让后续 AI 真正可以“对照文档落代码”，执行时必须遵守以下约束。

### 6.1 单次只推进一个主条目

每次实现时：

1. 只能选择一个 `3.x` 主条目作为本轮主目标。
2. 允许顺手补与该条目直接相关的小修复。
3. 不允许一次同时推进多个无关主条目。

例如：

1. 做 `3.2 OpenAI SDK 主路径` 时，可以顺手补 `ProviderManager` 接线。
2. 但不能顺手同时重构 `3.9 知识库分层重构`。

### 6.2 先更新计划，再动代码

开始实现前，后续 AI 必须先在本文档对应条目下补充：

1. `本次目标`
2. `预计改动文件`
3. `完成判定`

只有补完这三项，才允许开始改代码。

### 6.3 代码变更必须带验证

每次实现后，必须至少完成一种验证：

1. 单元测试
2. 集成测试
3. 命令行本地验证
4. 日志行为验证

如果因为环境限制无法验证，必须明确写出：

1. 为什么不能验证
2. 哪一层存在未验证风险

### 6.4 状态更新顺序固定

后续 AI 完成一个条目时，必须按以下顺序更新：

1. 先改代码
2. 再跑验证
3. 再更新本文档状态
4. 最后记录剩余风险

禁止先把状态改成 `[x]`，再去补代码或补验证。

### 6.5 `[x]` 的使用限制

以下情况不能标记为 `[x]`：

1. 只有接口文件，没有真实调用路径
2. 只有代码，没有验证
3. 有主路径，但 fallback 或关键约束未实现
4. 文档要求的关键安全约束还未满足

这种情况应标记为：

1. `[~]` 部分完成
2. 或 `[!]` 风险偏离

### 6.6 允许新增子任务，但不能改写目标

后续 AI 可以在某个 `3.x` 条目下新增：

1. `3.x.a`
2. `3.x.b`
3. `阻塞项`
4. `依赖项`

但不能擅自修改：

1. 主条目目标定义
2. 完成判定口径
3. 文档中的 V3 最终约束

如果发现目标定义本身有问题，只能新增：

`评注：建议人工确认后调整`

### 6.7 遇到偏离必须回填

如果实现过程中发现当前代码与本文档预估不一致，后续 AI 必须回填：

1. `实际现状`
2. `与预期偏离点`
3. `是否影响本轮交付`
4. `建议修正顺序`

不能只在代码里偷偷修，不在文档里留下差异说明。

### 6.8 建议的标准执行流程

推荐每一轮都按下面流程执行：

1. 选择一个 `3.x` 主条目
2. 阅读对应实现文件
3. 在本文档中补 `本次目标 / 预计改动文件 / 完成判定`
4. 改代码
5. 跑验证
6. 更新状态标记
7. 填写 `本次更新记录`
8. 列出 `剩余问题`

## 8. 结论

这份文档的作用是：

1. 告诉后续 AI “先做什么”
2. 告诉后续 AI “做到什么程度才能算完成”
3. 告诉后续 AI “改完代码后必须更新哪部分状态”

如果后续 AI 只能看一份“怎么继续做”的文档，应优先看本文档；如果要看最终目标，再回看 [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)。

## 9. 第二批可施工子任务

### 9.1 OpenAI 输出适配到统一动作

归属主条目：`3.3 内部统一动作协议`

状态：`[x]`

目标：

1. 让 `OpenAIProvider` 产出统一 `ActionEvent`
2. 覆盖 `read_knowledge`
3. 覆盖 `secure_ssh_execute`
4. 为最终结果补 `ACTION_REPORT`

输入文件：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
2. [feishu_agent/protocols/actions.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/actions.py)
3. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)

输出文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `tests/test_openai_provider.py`

完成判定：

1. OpenAI provider 返回的 `ProviderResult` 包含 `action_events`
2. 工具调用事件与 Copilot 路径动作语义一致
3. 现有 OpenAI provider 测试不退化

验收方式：

1. `python -m unittest tests.test_openai_provider`
2. 新增断言验证 `action_events` 顺序与类型

本次目标：

1. 只实现 OpenAI provider 的 `action_events`
2. 不改 orchestrator 统一消费方式

预计改动文件：

1. `feishu_agent/providers/openai_sdk.py`
2. `tests/test_openai_provider.py`

本次完成内容：

1. `OpenAIProvider` 已为 `read_knowledge` 产出统一动作事件
2. `OpenAIProvider` 已为 `secure_ssh_execute` 产出统一动作事件
3. `OpenAIProvider` 已为最终结果补 `ACTION_REPORT`

当前实现证据：

1. [feishu_agent/providers/openai_sdk.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/providers/openai_sdk.py)
2. [tests/test_openai_provider.py](/home/robot/amr-rcs-troubleshoot/tests/test_openai_provider.py)

验证方式：

1. `python -m unittest tests.test_openai_provider`
2. `python -m unittest tests.test_openai_provider tests.test_protocol_actions tests.test_protocol_schemas`

剩余差距：

1. OpenAI / Copilot 事件 payload 字段仍可能有细微差异
2. orchestrator 还未完全协议层驱动

### 9.2 Orchestrator 结构化结果与 Trace 最小接入

归属主条目：`3.4 Orchestrator 统一编排`

状态：`[x]`

目标：

1. 让 orchestrator 能生成统一结构化结果对象
2. 增加最小 trace 记录
3. 不破坏现有 `CaseResponse` 和飞书回复链路

输入文件：

1. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
2. [feishu_agent/protocols/schemas.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/protocols/schemas.py)
3. [tests/test_orchestrator.py](/home/robot/amr-rcs-troubleshoot/tests/test_orchestrator.py)

输出文件：

1. `feishu_agent/core/orchestrator.py`
2. `tests/test_orchestrator.py`

完成判定：

1. orchestrator 内部有统一结构化结果对象
2. 至少能输出最小 trace
3. 不影响现有飞书回复测试

验收方式：

1. 新增 orchestrator 单测验证结构化结果与 trace
2. 跑现有 orchestrator 相关测试

本次目标：

1. 只做最小结构化结果与 trace 接入
2. 不改变 `handle_case()` 的主返回类型

预计改动文件：

1. `feishu_agent/core/orchestrator.py`
2. `tests/test_orchestrator.py`

本次完成内容：

1. `CaseResponse` 已支持携带最小 `report_result`
2. `CaseResponse` 已支持携带最小 `trace`
3. orchestrator 已生成 `knowledge_candidates` / `local_execution` / `provider_action` 三类最小 trace
4. 保持了现有飞书回复主链路不变

当前实现证据：

1. [feishu_agent/core/orchestrator.py](/home/robot/amr-rcs-troubleshoot/feishu_agent/core/orchestrator.py)
2. [tests/test_orchestrator.py](/home/robot/amr-rcs-troubleshoot/tests/test_orchestrator.py)

验证方式：

1. `python -m unittest tests.test_orchestrator.OrchestratorTests.test_progress_response_includes_structured_report_and_trace`
2. `python -m unittest tests.test_orchestrator tests.test_protocol_actions tests.test_protocol_schemas`

剩余差距：

1. `run()` 统一返回对象还未替代 `CaseResponse`
2. trace 仍只是最小版本

## 9. 本次更新记录

### 2026-06-12

- 负责人：AI
- 目标条目：`4.1.a 新增 OpenAIProvider 骨架`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. 新增 `feishu_agent/providers/openai_sdk.py`
  2. `ProviderManager` 已接入 `OpenAIProvider`
  3. 新增 `tests/test_openai_provider.py`
- 验证方式：
  1. `python -m unittest tests.test_openai_provider`
  2. `python -m unittest tests.test_openai_provider tests.test_copilot_provider`
- 剩余问题：
  1. OpenAI provider 仍未实现 `Responses API` 实调
  2. 仍未实现函数调用闭环

### 2026-06-12（第二次更新）

- 负责人：AI
- 目标条目：`4.1.b 接入 Responses API 单轮调用`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `OpenAIProvider.run()` 已接入单轮 `responses.create(...)`
  2. 已显式设置 `parallel_tool_calls=False`
  3. 已显式设置 `store=False`
  4. 已支持最小结构化输出解析
- 验证方式：
  1. `python -m unittest tests.test_openai_provider`
  2. `python -m unittest tests.test_openai_provider tests.test_copilot_provider tests.test_provider_base`
- 剩余问题：
  1. 尚未实现函数调用闭环
  2. 尚未实现严格 schema 工具定义

### 2026-06-12（第三次更新）

- 负责人：AI
- 目标条目：`4.1.c 接入函数调用闭环`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `OpenAIProvider` 已支持最小函数调用闭环
  2. 已支持 `read_knowledge`
  3. 已支持 `secure_ssh_execute`
  4. 已支持使用 `previous_response_id` 继续第二轮请求
- 验证方式：
  1. `python -m unittest tests.test_openai_provider`
  2. `python -m unittest tests.test_openai_provider tests.test_provider_base`
- 剩余问题：
  1. 尚未实现严格 schema 文本输出
  2. 尚未抽成统一协议层动作事件

### 2026-06-12（第四次更新）

- 负责人：AI
- 目标条目：`4.1.c 接入函数调用闭环`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `OpenAIProvider` 已支持最小函数调用闭环
  2. 已支持 `read_knowledge`
  3. 已支持 `secure_ssh_execute`
  4. 已支持 `previous_response_id + function_call_output` 第二轮请求
- 验证方式：
  1. `python -m unittest tests.test_openai_provider`
  2. `python -m unittest tests.test_openai_provider tests.test_provider_base`
- 剩余问题：
  1. 仍未实现严格 schema 文本输出
  2. 仍未抽象成统一协议层动作事件

### 2026-06-12（第五次更新）

- 负责人：AI
- 目标条目：`4.2.a 新增 protocols/actions.py`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. 新增 `feishu_agent/protocols/actions.py`
  2. 定义统一动作类型常量
  3. 定义 `ActionEvent`
  4. 新增 `build_action_event()` 和 `is_valid_action_type()`
- 验证方式：
  1. `python -m unittest tests.test_protocol_actions`
  2. `python -m unittest tests.test_protocol_actions tests.test_openai_provider`
- 剩余问题：
  1. provider 还未正式产出统一动作事件
  2. orchestrator 还未切换成协议层消费模式

### 2026-06-12（第六次更新）

- 负责人：AI
- 目标条目：`4.2.b 新增 protocols/schemas.py`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. 新增 `feishu_agent/protocols/schemas.py`
  2. 定义 `RouteResult`
  3. 定义 `ExecutionResult`
  4. 定义 `ReportResult`
  5. 定义 `DraftResult`
- 验证方式：
  1. `python -m unittest tests.test_protocol_schemas`
  2. `python -m unittest tests.test_protocol_schemas tests.test_protocol_actions tests.test_openai_provider`
- 剩余问题：
  1. 现有 provider 和 orchestrator 还未切换成正式使用这些 schema

### 2026-06-12（第七次更新）

- 负责人：AI
- 目标条目：`4.2.c Copilot 输出适配到统一动作`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `ProviderResult` 已支持 `action_events`
  2. `CopilotCliProvider` 已为 `read_knowledge` 产出统一动作事件
  3. `CopilotCliProvider` 已为 `secure_ssh_execute` 产出统一动作事件
  4. 各类最终结果已补 `ACTION_REPORT`
- 验证方式：
  1. `python -m unittest tests.test_copilot_provider`
  2. `python -m unittest tests.test_copilot_provider tests.test_protocol_actions tests.test_openai_provider`
- 剩余问题：
  1. orchestrator 已开始消费 `action_events`，但还不是唯一主通道
  2. OpenAI / Copilot 动作事件字段仍需进一步统一

### 2026-06-12（第八次更新）

- 负责人：AI
- 目标条目：`4.2.c Copilot 输出适配到统一动作`
- 状态变更：`[x] -> [x]`
- 本次完成：
  1. orchestrator 已开始消费 `provider_result.action_events`
  2. `read_knowledge` 动作已能反映到 `knowledge_read[...]` 证据
  3. `secure_ssh_execute` 动作已能反映到 `provider_execute[...]` 证据
  4. `report` 动作已能反映到 `provider_report: ...` 证据
- 验证方式：
  1. `python -m unittest tests.test_orchestrator.OrchestratorTests.test_provider_action_events_are_reflected_in_evidence_and_read_docs`
  2. `python -m unittest tests.test_orchestrator tests.test_protocol_actions tests.test_protocol_schemas`
- 剩余问题：
  1. orchestrator 还不是完全协议层驱动
  2. action_events 仍主要作为增强证据链，而不是唯一业务输入

### 2026-06-12（第九次更新）

- 负责人：AI
- 目标条目：`9.1 OpenAI 输出适配到统一动作`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. `OpenAIProvider` 已为 `read_knowledge` 产出统一动作事件
  2. `OpenAIProvider` 已为 `secure_ssh_execute` 产出统一动作事件
  3. `OpenAIProvider` 已为最终结果补 `ACTION_REPORT`
- 验证方式：
  1. `python -m unittest tests.test_openai_provider`
  2. `python -m unittest tests.test_openai_provider tests.test_protocol_actions tests.test_protocol_schemas`
- 剩余问题：
  1. OpenAI / Copilot 事件 payload 字段仍可能有细微差异
  2. orchestrator 仍未完全协议层驱动

### 2026-06-12（第十次更新）

- 负责人：AI
- 目标条目：`9.2 Orchestrator 结构化结果与 Trace 最小接入`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. `CaseResponse` 已支持最小 `report_result`
  2. `CaseResponse` 已支持最小 `trace`
  3. orchestrator 已生成 `knowledge_candidates` / `local_execution` / `provider_action` 三类最小 trace
  4. 保持现有飞书回复链路不变
- 验证方式：
  1. `python -m unittest tests.test_orchestrator.OrchestratorTests.test_progress_response_includes_structured_report_and_trace`
  2. `python -m unittest tests.test_orchestrator tests.test_protocol_actions tests.test_protocol_schemas`
- 剩余问题：
  1. `CaseResponse` 仍不是最终统一返回对象
  2. trace 仍只是最小实现，还未形成完整审计链

### 2026-06-12（第十一次更新）

- 负责人：AI
- 目标条目：`4.4.a 新增 config.yaml 基础结构`、`4.4.b 新增配置读取入口`
- 状态变更：
  1. `4.4.a [~] -> [x]`
  2. `4.4.b [~] -> [x]`
- 本次完成：
  1. 新增仓库根 `config.yaml`
  2. 升级 `feishu_agent/config.py` 支持 YAML 读取
  3. 增加最小环境变量覆盖
  4. `OpenAIProvider` 已开始读取配置层
- 验证方式：
  1. `python -m unittest tests.test_config`
  2. `python -m unittest tests.test_config tests.test_openai_provider`
- 剩余问题：
  1. 目前只有局部模块接入配置层
  2. 全仓库 `os.getenv(...)` 仍未系统收敛

### 2026-06-12（第十二次更新）

- 负责人：AI
- 目标条目：`4.4.c 收敛分散的 os.getenv(...)`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. `ProviderManager` 已开始从配置层读取默认 provider 顺序
  2. `ssh/client.py` 已开始从配置层读取默认 SSH 用户
  3. `ssh/client.py` 已开始从配置层读取默认 rostopic timeout
- 验证方式：
  1. `python -m unittest tests.test_openai_provider tests.test_ssh_client`
  2. `python -m unittest tests.test_config tests.test_openai_provider tests.test_ssh_client`
- 剩余问题：
  1. 本轮只收敛了部分高价值默认值
  2. 全仓库 `os.getenv(...)` 仍未全面统一

### 2026-06-12（第十三次更新）

- 负责人：AI
- 目标条目：`4.5.a 新增 core/feishu_listener.py`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. 新增 `feishu_agent/core/feishu_listener.py`
  2. 正式启动入口已迁到 `FeishuListener`
  3. `ws_agent.handle_im_message` 已改为兼容代理
  4. 保持现有 `ws_agent` 行为和测试不回退
- 验证方式：
  1. `python -m unittest tests.test_feishu_listener`
  2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`
- 剩余问题：
  1. `ws_agent.py` 仍偏重，后续需继续拆分消息标准化和去重逻辑
  2. 当前只是入口层拆出，不是完整职责下沉

### 2026-06-12（第十四次更新）

- 负责人：AI
- 目标条目：`4.5.b 拆分消息标准化与去重`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `FeishuListener.handle_im_message()` 已拆成多段小步骤方法
  2. 消息标准化、去重、线程挂载、分支调度已开始下沉到 listener
  3. `ws_agent` 仍保留兼容入口，不影响现有调用方
- 验证方式：
  1. `python -m unittest tests.test_feishu_listener`
  2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`
- 剩余问题：
  1. `ws_agent.py` 仍保留较多辅助函数
  2. listener 还未完全摆脱对 `ws_agent` 模块状态的依赖

### 2026-06-12（第十五次更新）

- 负责人：AI
- 目标条目：`4.5.c 明确飞书层与编排层边界`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. orchestrator 已新增最小 `DispatchPlan`
  2. listener 改为执行编排计划，而不是自己直接判断主要业务分支
  3. 飞书层与编排层边界进一步清晰化
- 验证方式：
  1. `python -m unittest tests.test_orchestrator`
  2. `python -m unittest tests.test_ws_agent tests.test_feishu_listener`
  3. `python -m unittest tests.test_feishu_listener tests.test_ws_agent tests.test_orchestrator`
- 剩余问题：
  1. 当前还是最小 `DispatchPlan`，不是最终完整调度模型
  2. listener 仍依赖 `ws_agent` 的辅助函数和模块级状态

### 2026-06-12（第十六次更新）

- 负责人：AI
- 目标条目：`4.3.a 去掉本地 shell=True`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. 本地 sandbox 执行改为参数化 `subprocess.run(...)`
  2. 添加 shell 控制符显式拒绝，避免 `|`、`&&`、`$()` 等进入本地 shell 解析
  3. 新增 `tests/test_sandbox.py` 覆盖参数化执行与拒绝分支
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_sandbox`
  2. `.venv/bin/python -m unittest tests.test_ssh_client tests.test_orchestrator`
- 剩余问题：
  1. 远端 SSH 仍是 CLI 方式
  2. 主机密钥校验尚未切到显式拒绝未知主机的最终方案

### 2026-06-12（第十七次更新）

- 负责人：AI
- 目标条目：`3.4 Orchestrator 统一编排`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. 新增 `OrchestratorRunResult` 作为标准返回对象
  2. `run()` 已返回 `final_answer`、`messages`、`trace`、`sop_path`、`domain`
  3. `trace` 已升级为带时间戳与成功标志的 `TraceEntry`
  4. 保留 `handle_case()` 兼容壳，现有飞书回复链路不回退
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_orchestrator.OrchestratorTests.test_run_returns_standard_result_with_messages_trace_and_sop tests.test_orchestrator.OrchestratorTests.test_progress_response_includes_structured_report_and_trace tests.test_protocol_schemas`
  2. `.venv/bin/python -m unittest tests.test_ws_agent tests.test_feishu_listener`
- 剩余问题：
  1. 飞书层尚未切到 `run()` 作为主消费接口
  2. `handle_case()` 仍保留作为兼容路径

### 2026-06-12（第十八次更新）

- 负责人：AI
- 目标条目：`3.10 草稿沉淀与 Post Mortem`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. 新增 `feishu_agent/core/post_mortem.py`
  2. `OrchestratorRunResult` 已携带 `draft_result`
  3. `Orchestrator.run()` 已在 progress 场景生成并落盘草稿
  4. 新增草稿生成测试，覆盖 SOP 路径与关键命令提取
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_post_mortem tests.test_protocol_schemas tests.test_orchestrator.OrchestratorTests.test_run_returns_standard_result_with_messages_trace_and_sop`
  2. `.venv/bin/python -m unittest tests.test_ws_agent tests.test_feishu_listener`
  3. `.venv/bin/python -m unittest tests.test_config tests.test_openai_provider tests.test_ssh_client`
- 剩余问题：
  1. 草稿模板仍偏最小
  2. 后续可把草稿生成继续抽象为独立命令或服务入口

### 2026-06-12（第十九次更新）

- 负责人：AI
- 目标条目：`4.3.c 启用主机密钥校验`
- 状态变更：`[ ] -> [x]`
- 本次完成：
  1. `_build_ssh_command()` 默认使用 `StrictHostKeyChecking=yes`
  2. `_is_unknown_host_key()` 会把未知主机密钥归类为 `unknown_host_key`
  3. 新增测试覆盖 `reject_unknown_host_keys=true/false` 两种策略
  4. `config.yaml` 新增 `ssh.backend` 配置入口
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_ssh_client`
- 剩余问题：
  1. 远端 SSH 默认仍未切换到客户端库
  2. 若后续彻底禁止 `accept-new`，还需要再收紧配置分支

### 2026-06-12（第二十次更新）

- 负责人：AI
- 目标条目：`4.3.b SSH 改造为客户端库`
- 状态变更：`[ ] -> [!]`
- 本次完成：
  1. `ParamikoSshBackend` 已实现真实连接、执行、关闭与错误映射
  2. `client.py` 仍通过 backend facade 选择执行路径，paramiko 分支可配置启用
  3. 新增 `tests/test_ssh_backends.py` 覆盖 paramiko 缺失、成功、未知主机密钥拒绝
  4. `tests/test_config.py` 补充 `ssh.backend` 读配置与回退测试
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_ssh_backends tests.test_ssh_client tests.test_config`
- 剩余问题：
  1. 默认 backend 仍是 CLI
  2. 若要彻底完成迁移，还需要把 paramiko 路径提升为默认或移除 CLI 回退

### 2026-06-12（第二十一次更新）

- 负责人：AI
- 目标条目：`3.8 配置系统`
- 状态变更：`[~] -> [x]`
- 本次完成：
  1. `OpenAIProvider`、`knowledge.loader`、`PostMortem`、`ssh/client.py`、`ssh/backends.py`、`ssh/collect.py` 已改为支持显式 `settings` 透传
  2. `Orchestrator` 已把 `settings` 继续向知识加载、远端采集和草稿生成链路下传
  3. 导入期 `load_settings()` 已改为 lazy resolve，配置读取不再在启动阶段四散发生
  4. 新增 `tests/test_knowledge_loader.py` 覆盖显式 settings root 场景
- 验证方式：
  1. `.venv/bin/python -m unittest tests.test_bootstrap tests.test_main tests.test_config tests.test_feishu_listener tests.test_message_flow tests.test_orchestrator tests.test_openai_provider tests.test_provider_base tests.test_ssh_client tests.test_ssh_backends tests.test_post_mortem tests.test_knowledge_loader tests.test_sandbox`
  2. `.venv/bin/python -m py_compile feishu_agent/core/orchestrator.py feishu_agent/core/post_mortem.py feishu_agent/knowledge/loader.py feishu_agent/providers/manager.py feishu_agent/providers/openai_sdk.py feishu_agent/sandbox/ssh_executor.py feishu_agent/ssh/backends.py feishu_agent/ssh/client.py feishu_agent/ssh/collect.py tests/test_knowledge_loader.py`
- 剩余问题：
  1. 少量部署辅助脚本仍直接调用 `load_settings()`
  2. 一些运行时开关仍由 `os.getenv(...)` 控制，后续可继续向 `config.yaml` 收敛
