# CyanineTech AMR/RCS Troubleshooting Toolkit

面向 CyanineTech AMR / RCS 场景的排障工具包。  
当前仓库优先服务于“故障已经发生，事后回溯原因”的场景，而不是只做当下状态体检。第一版目标不是做成一个完美平台，而是先提供一套可上线、可持续迭代的历史故障排查基础设施：

1. 分层知识库
2. 现场诊断脚本
3. 飞书接入与会话 follow-up
4. OpenAI / Copilot provider 接入骨架
5. 可持续沉淀历史案例、机型差异、专项页与错误码簇页

## 当前状态

当前仓库已经达到“可上线试运行”的基础状态：

1. `feishu_agent.main` 可作为正式启动入口
2. 飞书消息入站、线程内 follow-up 和回帖主链路已打通
3. `knowledge/` 已完成分层重构，并已补多批高频知识页
4. 本地排障脚本和知识召回链路可独立使用
5. 历史故障场景已开始按“先找时间点 / 重启点，再回看日志和调用链”的方式收敛

更完整的上线说明见：

- [ONLINE_DEPLOYMENT.md](/home/robot/amr-rcs-troubleshoot/feishu_agent/ONLINE_DEPLOYMENT.md)

## 仓库结构

```text
.
├── .github/
│   └── copilot-instructions.md      # GitHub Copilot 仓库级指令
├── AGENTS.md                        # Agent 运行模式约束
├── config.yaml                      # 本地运行配置
├── config.example.yaml              # 配置示例
├── feishu_agent/                    # 飞书接入、provider、orchestrator、sandbox
├── knowledge/                       # 分层排障知识库
├── prompts/                         # 提示词模板
├── scripts/                         # 只读排障脚本
├── tests/                           # 单元测试
├── v2.1_to_v3_migration.md          # 迁移说明
└── v3_implementation_tracker.md     # 实施跟踪清单
```

## 知识库结构

知识库已经按业务域拆分，主入口见：

- [knowledge/README.md](/home/robot/amr-rcs-troubleshoot/knowledge/README.md)

当前主要目录：

1. `knowledge/hardware_bus/`
2. `knowledge/ros/`
3. `knowledge/network/`
4. `knowledge/backend/`
5. `knowledge/task_dispatch/`
6. `knowledge/cbs/`

知识库维护原则：

1. 普通新增页：优先直接新增 `md`
2. 同步更新目录 `README.md`
3. 补 `常见检索词`
4. 默认写成“历史故障复盘 / 事后回溯”口径，除非明确是实时值班场景
5. 尽量不改 Python，除非涉及新业务域或召回逻辑调整

## 快速开始

### 1. 创建环境

```bash
cd /home/robot/amr-rcs-troubleshoot
python3 -m venv .venv
source .venv/bin/activate
pip install -r feishu_agent/requirements.txt
```

### 2. 查看配置

复制并修改示例配置：

```bash
cp config.example.yaml config.yaml
```

如需启用 OpenAI provider，请通过环境变量注入密钥：

```bash
export OPENAI_API_KEY=...
```

### 3. 运行排障脚本

```bash
bash scripts/check_amr_status.sh <amr_ip_or_hostname>
bash scripts/check_rcs_status.sh <rcs_ip_or_hostname>
bash scripts/check_rcs_reboot_history.sh <rcs_ip_or_hostname>
bash scripts/network_diag.sh <amr_ip_or_hostname>
bash scripts/collect_logs.sh <amr_ip_or_hostname> [time_key]
```

说明：

1. `check_amr_status.sh` / `check_rcs_status.sh` 更适合做当前状态快照。
2. 如果问题已经发生并且设备/主机重启过，优先走历史日志和重启回溯，不要直接把当前状态当成历史根因。
3. `check_rcs_reboot_history.sh` 用于主机类“死机后重启恢复”场景，先看最近一次重启点，再回看上一个 `boot` 的 `supervisor`、`backend`、`docker`、`kernel` 日志。
4. `collect_logs.sh` 现在支持带精确故障时间回溯到对应开机目录；对于 AMR 历史故障，建议按“开机目录与基础日志 -> 低层与运行态 -> caution / bag 与恢复动作”三阶段逐步收口，而不是只看首轮摘要。

### 4. 启动飞书服务

```bash
source .venv/bin/activate
python -m feishu_agent.main
```

## 常用文档

### 项目与部署

- [ONLINE_DEPLOYMENT.md](/home/robot/amr-rcs-troubleshoot/feishu_agent/ONLINE_DEPLOYMENT.md)
- [v2.1_to_v3_migration.md](/home/robot/amr-rcs-troubleshoot/v2.1_to_v3_migration.md)
- [v3_implementation_tracker.md](/home/robot/amr-rcs-troubleshoot/v3_implementation_tracker.md)

### 知识库入口

- [knowledge/README.md](/home/robot/amr-rcs-troubleshoot/knowledge/README.md)
- [system-architecture.md](/home/robot/amr-rcs-troubleshoot/knowledge/system-architecture.md)
- [error-tracing-methods.md](/home/robot/amr-rcs-troubleshoot/knowledge/error-tracing-methods.md)
- [error-codes.md](/home/robot/amr-rcs-troubleshoot/knowledge/error-codes.md)
- [log-paths.md](/home/robot/amr-rcs-troubleshoot/knowledge/log-paths.md)

## 适用方式

这个仓库可以以 3 种方式使用：

1. 只把它当知识库和脚本仓库
2. 本地用 Copilot / Codex / Claude Code 直接读仓库辅助做历史故障复盘
3. 通过 `feishu_agent` 接入飞书做线程式历史排障

## 安全与提交注意事项

1. 不要提交真实密钥、口令、运行日志、会话状态
2. 不要提交 `logs/`、`.venv/`、`knowledge/_ai_drafts/`
3. 诊断脚本和 AI 结论应默认只读优先
4. 生产写操作、重启、恢复动作必须在真实现场确认影响范围

## 推送前建议

正式推送到 GitHub 前，建议至少检查：

1. [copilot-instructions.md](/home/robot/amr-rcs-troubleshoot/.github/copilot-instructions.md) 是否只保留工具指令职责
2. [knowledge/README.md](/home/robot/amr-rcs-troubleshoot/knowledge/README.md) 是否与当前知识库结构一致
3. [v3_implementation_tracker.md](/home/robot/amr-rcs-troubleshoot/v3_implementation_tracker.md) 是否反映真实实现状态
4. `.gitignore` 是否拦住本地运行产物
5. 关键测试是否通过
