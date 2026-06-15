# 飞书自动排障代理

这个目录放当前推荐的本机服务主实现。上线主路径统一走 `feishu_agent.main`，由它装配 `FeishuListener -> Orchestrator`；`ws_agent` 仅保留兼容壳，不再作为推荐启动入口。

默认日志会同时输出到控制台和 [logs/feishu_agent.log](/home/robot/amr-rcs-troubleshoot/logs/feishu_agent.log)。如果你想改路径，可以设置 `FEISHU_LOG_FILE`。

## 1. 安装依赖

```bash
cd /home/robot/amr-rcs-troubleshoot
python3 -m venv .venv
source .venv/bin/activate
pip install -r feishu_agent/requirements.txt
```

## 2. 启动长连接客户端

```bash
export FEISHU_APP_ID=cli_xxxxxxxx
export FEISHU_APP_SECRET=xxxxxxxxxxxxxxxx
python -m feishu_agent.main
```

启动后，控制台应该能看到连接到 `wss://...` 的日志。
群消息 mention 门禁会优先自动解析机器人自身的 open_id；如果现场环境无法自动解析，也可以手动设置 `FEISHU_BOT_OPEN_ID` 或 `FEISHU_BOT_USER_ID`。

## 3. 本地验证

如果你还想保留 webhook 调试服务，也可以单独启动 HTTP 服务：

```bash
uvicorn feishu_agent.app:app --host 0.0.0.0 --port 8000
```

```bash
curl http://127.0.0.1:8000/health
```

再发一个事件回调测试：

```bash
curl -X POST http://127.0.0.1:8000/feishu/events \
  -H 'Content-Type: application/json' \
  -d '{"challenge":"test-challenge"}'
```

## 4. 飞书怎么接进来

在飞书开放平台创建一个自建应用，然后做下面几步：

1. 开启机器人能力。
2. 开启事件订阅。
3. 在“订阅方式”里选择**使用长连接接收事件**。
4. 这时**不要**填写公网回调地址，也**不要**配置加密策略。
5. 订阅事件 `im.message.receive_v1`。
6. 保存并发布应用版本。
7. 本机启动 `feishu_agent.main`，确认控制台出现 `connected to wss://...`。
8. 回到飞书后台点击“验证连接状态”。
9. 验证成功后，把应用拉进群，@机器人发送测试消息。

## 5. 原排障流程触发模式

当前这个最小版会把飞书消息映射到原来的排障 playbook，而不是直接进入模型复核或额外推理层。

- `network` → 走网络排障分支
- `amr` → 走 AMR 排障分支
- `rcs` → 走 RCS 排障分支

如果消息里没有足够的目标信息，机器人会先追问一次必要信息，例如设备 IP 或主机名；补齐后再继续按原排障流程推进。

当前已经补上的高频症状页包括 [cpu-high.md](cpu-high.md) 和 [service-timeout.md](service-timeout.md)，它们会优先被知识检索层挂到对应场景下。

## 6. 可选运行开关

如果你想把闭环继续往前推进，可以按需打开下面这些环境变量：

```bash
# 开启本地自动诊断：直接调用 scripts/ 下的排障脚本并输出标准结论
export FEISHU_ENABLE_LOCAL_DIAG=1

# 开启远程只读取证：在白名单内通过 SSH 采集证据
export FEISHU_ENABLE_REMOTE_COLLECT=1

# 开启本机 AI CLI 复核：调用 copilotcli 或 Claude Code 作为辅助推理层
export FEISHU_ENABLE_PROVIDER_REVIEW=1

# 自定义日志文件路径
export FEISHU_LOG_FILE=/home/robot/amr-rcs-troubleshoot/logs/feishu_agent.log

# 如果要启用 provider，需要额外配置命令
export COPILOTCLI_COMMAND=/path/to/copilotcli
export CLAUDE_CODE_COMMAND=/path/to/claude-code

# provider 默认超时 600 秒，超时后会终止对应进程组
export COPILOTCLI_TIMEOUT=600
export CLAUDE_CODE_TIMEOUT=600

# provider 详细 trace，默认写到 logs/provider_trace.log
export FEISHU_PROVIDER_TRACE_FILE=/home/robot/amr-rcs-troubleshoot/logs/provider_trace.log
```

如果已经配置了 `COPILOTCLI_COMMAND` 或 `CLAUDE_CODE_COMMAND`，编排器会优先尝试做模型复核；也可以显式打开 `FEISHU_ENABLE_PROVIDER_REVIEW=1`。

建议默认先只开 `FEISHU_ENABLE_LOCAL_DIAG=1`，这样最容易验证闭环；等稳定后，再逐步打开远程取证和模型复核。

## 7. 当前推荐上线模式

当前最建议的上线模式是：

1. 使用 systemd 启动 `feishu_agent.main`
2. 默认打开 `FEISHU_ENABLE_LOCAL_DIAG=1`
3. 根据现场情况决定是否开启 `FEISHU_ENABLE_REMOTE_COLLECT=1`
4. `FEISHU_ENABLE_PROVIDER_REVIEW=1` 只在本机 provider 已验证稳定后再打开

如果目标是“先上线可用，再逐步增强”，建议先保证飞书入站、路由、follow-up、本地脚本诊断和回帖全部稳定，再补 AI 复核优化。
