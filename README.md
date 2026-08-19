# Testing Tool Platform

基于 `ARCHITECTURE.md` 的多容器测试工具平台。当前部署脚本执行器和摄像头模拟器，电梯模拟器保留为计划工具，不参与当前部署。

## 架构

```text
Browser -> Nginx gateway:5000 -> tools_network
                           |-> tool-script-runner:8000
                           `-> tool-camera-sim:8002
```

业务容器不直接暴露宿主机端口，所有访问经由网关。网关认证可通过 `offline_bundle/.env` 的 `PLATFORM_AUTH_ENABLED` 控制。

## 启动

```bash
cd /home/robot/testing_tool
./start.sh
```

首次启动前修改 `offline_bundle/.env`：

```dotenv
PLATFORM_USER=admin
PLATFORM_PASSWORD=replace-with-a-strong-password
PLATFORM_AUTH_ENABLED=1
```

不需要登录时设置 `PLATFORM_AUTH_ENABLED=0`；需要登录时设置为 `1`，然后访问 `http://<部署机器IP>:5000`。

## 统一接口

脚本服务使用 `/api/v1/scripts/`，摄像头模拟器使用 `/api/v1/camera/`。健康检查分别是 `/health`，网关健康检查是 `/nginx-health`。

脚本配置位于 `offline_bundle/runtime/config.ini`，脚本位于 `offline_bundle/scripts/`。日志和摄像头状态使用 Docker named volume 持久化。

## 运维

```bash
cd offline_bundle
docker compose ps
docker compose logs -f gateway
docker compose logs -f tool-script-runner
docker compose restart tool-script-runner
docker compose restart tool-camera-sim
docker compose down
```

修改脚本只需重新执行对应任务；修改服务代码、Nginx 配置或前端静态文件后执行：

```bash
docker compose up -d --build gateway tool-script-runner tool-camera-sim
```

不要提交真实账号、密码、token、日志、`__pycache__` 或运行数据。
