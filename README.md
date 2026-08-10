# 测试工具集

这是一个面向仓储、搬运和调度接口的测试工具集，提供 Python 任务脚本和 Web 管理页面，用于登录认证、查询库位、生成测试任务、持续调度任务以及查看运行日志。

`amr-rcs-troubleshoot/` 是独立的 AMR/RCS 排障子项目，不属于本项目的任务脚本运行链路。

## 快速启动

运行环境要求：Docker、Docker Compose，以及能够访问 Python 依赖源和目标仓储服务的网络环境。

```bash
git clone <仓库地址>
cd testing_tool
chmod +x start.sh
./start.sh
```

首次启动会根据模板创建 `offline_bundle/runtime/config.ini`。请编辑该文件，填写目标服务地址、账号和密码，然后再次执行 `./start.sh`。页面地址为：

```text
http://<部署机器IP>:5000
```

## 目录结构

```text
testing_tool/
├── start.sh                         # 根目录一键启动入口
├── README.md
├── offline_bundle/                  # 唯一的测试工具源码和部署目录
│   ├── service/                     # Flask Web 服务和页面模板
│   ├── scripts/                     # 所有可执行任务脚本
│   ├── runtime/                     # 配置、脚本描述和运行日志
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── offline_deploy.sh
└── amr-rcs-troubleshoot/            # 独立排障项目
```

后续更新任务脚本时，只修改 `offline_bundle/scripts/`。Docker Compose 会把该目录挂载到容器的 `/app/scripts`，不要再维护另一份脚本目录。

## 配置说明

配置文件：

```text
offline_bundle/runtime/config.ini
```

主要配置段：

| 配置段 | 作用 |
| --- | --- |
| `[base]` | 登录账号、密码和 token |
| `[service]` | 目标服务 host 和 port |
| `[map]` | 地图或场景 ID |
| `[business]` | 任务规则、区域和固定目标库位 |
| `[task]` | 任务库位列表 |
| `[excel]` | Excel 文件路径和工作表名称 |
| `[request]` | 请求超时、重试次数和重试间隔 |
| `[log]` | 调试开关和日志文件路径 |

账号、密码和 token 属于敏感信息，不要提交到 GitHub。`login.py` 会在登录成功后自动更新 `[base]` 中的 token。

## Web 页面功能

- 查看和刷新可执行脚本列表
- 编辑脚本描述和执行流程
- 查看、修改配置文件
- 启动和停止任务脚本
- 实时查看脚本输出和最近输出
- 查看任务日志文件
- 下载脚本文件

终端输出支持实时更新。用户上翻查看历史内容后，页面不会强制跳回最新一行；回到底部后会恢复自动跟随。

## 脚本说明

所有脚本位于 `offline_bundle/scripts/`：

| 脚本 | 用途 |
| --- | --- |
| `login.py` | 登录目标服务并更新 token |
| `get_area.py` | 获取区域信息并更新配置 |
| `get_Location_info.py` | 获取库位信息并生成 Excel 数据 |
| `leefung-s1-random-task-dispatcher.py` | 随机查询库位并持续发送任务 |
| `GFS_Random_task.py` | 仓库任务调度和库位释放任务 |
| `lift_cargo_to_zone.py` | 批量发送库位到区域的搬运任务 |
| `region_pickup_to_lift_task.py` | 按区域规则执行取货到提升机任务 |
| `auto_start_location_call_task.py` | 根据规则和频率自动发送任务 |
| `Download.py` | 下载、提取和整理日志 |
| `p2p_monitor.py` | P2P 监控工具 |
| `analyze_traffic.py` | 分析网络流量统计文件 |

其中 `leefung-s1-random-task-dispatcher.py` 启动时会先调用同目录的 `login.py`。登录失败时不会继续发送任务，后续请求使用登录获得的 Bearer token。

## 手动执行脚本

通常建议通过 Web 页面执行。需要进入容器手动运行时：

```bash
docker exec -it testing_tool_web bash
cd /app/scripts
python login.py --config /app/scripts/config.ini
python leefung-s1-random-task-dispatcher.py
```

## 更新代码

更新任务脚本：

```bash
git pull
```

然后在页面中停止旧进程并重新执行脚本。任务脚本目录是挂载目录，通常不需要重建镜像。

更新 Web 服务代码或页面模板：

```bash
cd offline_bundle
docker compose restart testing-tool-web
```

更新依赖、Dockerfile 或 Compose 配置：

```bash
./start.sh
```

## 查看服务状态和日志

```bash
cd offline_bundle
docker compose ps
docker compose logs -f testing-tool-web
```

停止服务：

```bash
docker compose down
```

任务日志通常位于 `offline_bundle/scripts/*.log`。Web 页面也会从 `runtime/logs/` 和 `scripts/` 中读取日志文件。

## 离线部署

默认启动方式从源码构建 Docker 镜像。如果目标机器无法访问依赖下载源，但另外提供了 `offline_bundle/image.tar`，可以使用：

```bash
USE_OFFLINE_IMAGE=1 ./start.sh
```

`image.tar` 体积较大，不应提交到 GitHub，应通过内部文件服务器或其他离线介质单独分发。

## 安全和提交规范

不要提交真实账号、密码、token、`runtime/config.ini`、日志文件、`image.tar`、压缩包、`.venv/`、`__pycache__/` 或 `.pyc` 文件。

提交前检查：

```bash
git status
git diff --cached --stat
```

如果敏感信息曾经提交到 Git 历史中，应立即更换对应密码和 token，并清理 Git 历史。
