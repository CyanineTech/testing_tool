# 上线部署说明

本文档面向“新机器从零部署”场景。  
目标不是一次性打开所有高级能力，而是先稳定跑通这条最小闭环：

1. 飞书长连接入站
2. 消息分类与 follow-up
3. 本地排障脚本执行
4. 飞书线程内回帖
5. 之后再逐步打开远程取证和模型复核

## 1. 目标机器要求

推荐新机器满足以下条件：

1. Linux 系统
2. 可安装 Python 3.10+ 或当前项目依赖所需 Python 版本
3. 可访问飞书开放平台长连接接口
4. 如需现场诊断脚本，需能访问 AMR / RCS 主机网络
5. 如需远程排障，建议预装：
   - `sshpass`
   - `openssh-client`

## 2. 获取代码

```bash
cd /home/robot
git clone <your-github-repo-url> amr-rcs-troubleshoot
cd amr-rcs-troubleshoot
```

如果不是放在 `/home/robot/amr-rcs-troubleshoot`，后续 systemd 文件与启动脚本中的路径也要一起调整。

## 3. 创建 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r feishu_agent/requirements.txt
```

如果未来要跑测试，也建议一并保留这个 `.venv`。

## 4. 准备配置文件

项目配置分两层：

1. `config.yaml`
   - 仓库内配置
   - 定义 provider 模式、llm 默认值、ssh 默认值、知识库路径
2. `/etc/default/feishu_agent`
   - 机器本地环境变量
   - 用于存放飞书凭据、OpenAI 凭据、运行开关

推荐做法：

```bash
cp config.example.yaml config.yaml
sudo cp feishu_agent/system/feishu_agent.env.example /etc/default/feishu_agent
sudoedit /etc/default/feishu_agent
```

## 5. 环境变量说明

下面这些环境变量是部署时最常用、最重要的。

### 5.1 必填变量

#### `FEISHU_APP_ID`

- 作用：飞书机器人应用的 App ID
- 是否必须：是
- 不配置会怎样：
  - 服务启动失败
  - 长连接无法建立

#### `FEISHU_APP_SECRET`

- 作用：飞书机器人应用的 App Secret
- 是否必须：是
- 不配置会怎样：
  - 服务启动失败
  - 无法通过飞书鉴权

### 5.2 OpenAI 相关变量

#### `OPENAI_API_KEY`

- 作用：OpenAI 兼容接口密钥
- 是否必须：
  - 仅在使用 `openai_sdk` provider 时必须
- 不配置会怎样：
  - `openai_sdk` provider 不可用
  - 只能走 fallback provider 或纯本地排障

#### `OPENAI_BASE_URL`

- 作用：OpenAI 兼容服务地址
- 是否必须：
  - 如果你不使用默认地址，则必须配置
- 当前项目默认参考值：
  - 由 `config.yaml` 提供基础默认值

#### `OPENAI_MODEL`

- 作用：指定模型名
- 是否必须：
  - 不必须，但建议显式配置，便于环境迁移

#### `OPENAI_ENABLE_TOOL_CALLS`

- 作用：是否允许 OpenAI provider 使用工具调用闭环
- 推荐值：
  - `1`：允许模型继续使用 `read_knowledge` / `secure_ssh_execute`
  - `0`：只基于现有证据总结
- 当前建议：
  - 当前这套上线方案建议直接开启

### 5.3 飞书运行开关

#### `FEISHU_ENABLE_LOCAL_DIAG`

- 作用：开启本地排障脚本执行
- 推荐值：
  - `1`
- 作用结果：
  - 能执行本地排障脚本并生成结构化结果
- 当前上线建议：
  - 第一阶段必须开

#### `FEISHU_ENABLE_REMOTE_COLLECT`

- 作用：是否自动做远程取证 / SSH 补充采集
- 推荐值：
  - 第一阶段：`0`
  - 第二阶段：`1`
- 风险：
  - 会增加链路复杂度、执行时长与环境依赖

#### `FEISHU_ENABLE_PROVIDER_REVIEW`

- 作用：是否开启模型复核
- 推荐值：
  - 第一阶段：`0` 或按现场稳定性决定
  - 第二阶段：`1`
- 说明：
  - 关闭后，系统仍可走本地排障主链路

#### `FEISHU_BACKGROUND_CASE_PROCESSING`

- 作用：是否在后台线程处理飞书消息
- 是否必须：否
- 说明：
  - 如不显式配置，系统也可能因其它开关而启用后台处理

### 5.4 Copilot CLI 相关变量

如果还要保留 Copilot 路径，常见变量如下：

#### `COPILOTCLI_COMMAND`

- 作用：Copilot CLI 可执行文件路径
- 是否必须：
  - 仅当启用 `copilot_cli` provider 时必须

#### `COPILOTCLI_TIMEOUT`

- 作用：Copilot CLI 调用超时时间（秒）
- 推荐值：
  - `600`

#### `COPILOTCLI_ADDITIONAL_MCP`

- 作用：额外 MCP 配置文件路径
- 是否必须：否
- 说明：
  - 若现场没用 MCP，可不配

### 5.5 会话 / 观测相关变量

#### `FEISHU_PROVIDER_TRACE_FILE`

- 作用：记录 provider trace 日志
- 是否必须：否
- 适用场景：
  - 调试 provider 或试运行排查

#### `FEISHU_SESSION_TTL_SECONDS`

- 作用：飞书会话状态保留时间
- 是否必须：否
- 说明：
  - 不配时走代码默认值

### 5.6 Bot 身份变量

#### `FEISHU_BOT_OPEN_ID`
#### `FEISHU_BOT_USER_ID`

- 作用：在自动解析机器人身份失败时，手工指定 bot 身份
- 是否必须：否
- 建议：
  - 如果群内 mention 判断异常，再补配置

## 6. 推荐的首版环境变量模板

新机器第一次部署，推荐最小配置如下：

```bash
FEISHU_APP_ID=your_feishu_app_id
FEISHU_APP_SECRET=your_feishu_app_secret

OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint.example
OPENAI_MODEL=gpt-5.4-mini

FEISHU_ENABLE_LOCAL_DIAG=1
FEISHU_ENABLE_REMOTE_COLLECT=0
FEISHU_ENABLE_PROVIDER_REVIEW=0
```

如果你要保留 Copilot fallback，再补：

```bash
COPILOTCLI_COMMAND=/absolute/path/to/copilot
COPILOTCLI_TIMEOUT=600
COPILOTCLI_ADDITIONAL_MCP=@/etc/copilot/mcp-config.json
```

## 7. systemd 部署

项目推荐通过 systemd 启动。

### 7.1 服务文件

服务文件位置：

- [feishu_agent.service](/home/robot/amr-rcs-troubleshoot/feishu_agent/system/feishu_agent.service)

安装：

```bash
sudo cp feishu_agent/system/feishu_agent.service /etc/systemd/system/feishu_agent.service
sudo systemctl daemon-reload
```

### 7.2 启动脚本

启动脚本位置：

- [start.sh](/home/robot/amr-rcs-troubleshoot/feishu_agent/start.sh)

这个脚本会：

1. 加载 `/etc/default/feishu_agent`
2. 校验 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
3. 自动选择 `.venv/bin/python`
4. 最终启动：

```bash
python -m feishu_agent.main
```

### 7.3 启用服务

```bash
sudo systemctl enable --now feishu_agent.service
sudo systemctl status feishu_agent.service --no-pager
```

## 8. 首次上线建议开关

### 第一阶段：最小闭环优先

建议：

```bash
FEISHU_ENABLE_LOCAL_DIAG=1
FEISHU_ENABLE_REMOTE_COLLECT=0
FEISHU_ENABLE_PROVIDER_REVIEW=0
```

适合目标：

1. 先验证飞书入站
2. 先验证消息回帖
3. 先验证本地脚本排障
4. 先验证线程内 `继续`

### 第二阶段：逐步增强

再逐步打开：

```bash
FEISHU_ENABLE_REMOTE_COLLECT=1
FEISHU_ENABLE_PROVIDER_REVIEW=1
```

当前建议直接开启：

```bash
OPENAI_ENABLE_TOOL_CALLS=1
```

## 9. 新机器部署后的验收步骤

### 9.1 配置验收

1. `config.yaml` 可读取
2. `/etc/default/feishu_agent` 已填值
3. `.venv` 存在
4. `pip install -r feishu_agent/requirements.txt` 成功

### 9.2 服务验收

```bash
sudo systemctl status feishu_agent.service --no-pager
journalctl -u feishu_agent.service -n 100 --no-pager
```

确认：

1. 服务成功启动
2. 没有缺 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`
3. 没有缺 Python 依赖
4. 飞书长连接已建立

### 9.3 飞书验收

确认飞书开放平台：

1. 已启用长连接接收事件
2. 已订阅 `im.message.receive_v1`
3. 机器人已加入测试群

群内验证：

1. `@机器人 网络连不上 192.168.1.250`
2. `@机器人 RCS 任务不派发`
3. 在同一线程回复 `继续`

### 9.4 功能验收

至少验证：

1. 新消息可入站
2. 可正常回帖
3. `继续` 能继承上下文
4. 本地排障结果能回传

## 10. 常见部署问题

### 10.1 服务起不来

优先检查：

1. `/etc/default/feishu_agent` 是否存在
2. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 是否为空
3. `.venv` 是否创建
4. `lark_oapi` 是否安装成功

### 10.2 飞书有消息但不回帖

优先检查：

1. 飞书应用事件订阅配置
2. 机器人是否已在群里
3. 日志里是否有入站记录
4. 是否因为环境变量缺失导致 provider / 本地脚本链未启动

### 10.3 Provider 不可用

优先检查：

1. `OPENAI_API_KEY`
2. `OPENAI_BASE_URL`
3. `OPENAI_MODEL`
4. 如果使用 Copilot fallback，再检查 `COPILOTCLI_COMMAND`

## 11. 现在这版推到 GitHub 前怎么做

按下面步骤走最稳：

### 第一步：确认不提交本地产物

仓库已经通过 `.gitignore` 拦住这些内容：

1. `.venv/`
2. `.pytest_cache/`
3. `logs/`
4. `knowledge/_ai_drafts/`
5. `.env*`

### 第二步：运行一轮最小回归

```bash
.venv/bin/python -m unittest \
  tests.test_orchestrator \
  tests.test_message_flow \
  tests.test_openai_provider \
  tests.test_feishu_listener \
  tests.test_knowledge_loader
```

### 第三步：检查发布文档

确认以下文件已更新：

1. [README.md](/home/robot/amr-rcs-troubleshoot/README.md)
2. [copilot-instructions.md](/home/robot/amr-rcs-troubleshoot/.github/copilot-instructions.md)
3. [knowledge/README.md](/home/robot/amr-rcs-troubleshoot/knowledge/README.md)
4. [release_v1_checklist.md](/home/robot/amr-rcs-troubleshoot/release_v1_checklist.md)
5. [v3_implementation_tracker.md](/home/robot/amr-rcs-troubleshoot/v3_implementation_tracker.md)

### 第四步：初始化并推送 GitHub

如果本地还没建仓：

```bash
git init
git add .
git commit -m "feat: initial v1 release"
git branch -M main
git remote add origin <your-github-repo-url>
git push -u origin main
```

如果已经是 Git 仓库，只需要：

```bash
git add .
git commit -m "feat: prepare v1 github release"
git push
```

## 12. 发布后建议

1. 先以 `v1` 身份开始真实现场试运行
2. 用 GitHub Issues 收集真实问题样例
3. 新问题优先补 `knowledge/`
4. 每次较大改动同步更新 `v3_implementation_tracker.md`
