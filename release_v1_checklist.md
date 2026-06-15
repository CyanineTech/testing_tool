# V1 发布检查清单

用于将当前仓库作为第一版正式推送到 GitHub 前的自检。

## 1. 仓库内容检查

1. `README.md` 已更新为 GitHub 发布版说明
2. `.github/copilot-instructions.md` 已仅保留工具指令职责
3. `knowledge/README.md` 与当前分层结构一致
4. `v3_implementation_tracker.md` 反映当前真实进度
5. `config.example.yaml` 已存在且不含真实密钥

## 2. 敏感信息检查

1. 仓库中不包含真实 `OPENAI_API_KEY`
2. 仓库中不包含 `.env` / `.env.*`
3. 仓库中不包含运行日志
4. 仓库中不包含飞书会话状态
5. 仓库中不包含本地虚拟环境

## 3. 忽略规则检查

确认 `.gitignore` 已覆盖：

1. `.venv/`
2. `.pytest_cache/`
3. `logs/`
4. `knowledge/_ai_drafts/`
5. `.env*`

## 4. 文档检查

1. 至少有一份根目录说明：`README.md`
2. 至少有一份上线说明：`feishu_agent/ONLINE_DEPLOYMENT.md`
3. 至少有一份迁移说明：`v2.1_to_v3_migration.md`
4. 至少有一份实施跟踪：`v3_implementation_tracker.md`
5. 知识库各目录 `README.md` 已存在

## 5. 测试检查

建议至少运行：

```bash
.venv/bin/python -m unittest \
  tests.test_orchestrator \
  tests.test_message_flow \
  tests.test_openai_provider \
  tests.test_feishu_listener \
  tests.test_knowledge_loader
```

## 6. 启动检查

如要发布可运行版本，建议本地至少确认：

1. `python -m feishu_agent.main` 可启动
2. 配置文件可加载
3. 脚本可执行
4. 知识库入口文档可正常打开

## 7. 发布后建议

1. 第一次推送后优先用 GitHub Issues 记录现场样例
2. 新问题优先补 `knowledge/`
3. 每次较大改动同步更新 `v3_implementation_tracker.md`
