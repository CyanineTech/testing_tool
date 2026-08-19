---

## 1. 推荐让 AI 遵循的行业工程标准

在给 AI 发送需求时，可以直接声明遵循以下 4 个行业主流规范：

* **The Twelve-Factor App（12-Factor 规范）**：云原生和容器化架构的黄金标准（重点强调配置与代码分离、无状态进程、快速启动与优雅终止、通过端口绑定暴露服务）。
* **Docker Compose Specification (Compose Spec)**：标准化的多容器服务编排规范（包括 Healthcheck 健康检查、Restart 策略、隔离 Network、资源配额 limits 等）。
* **OpenAPI Specification (OAS 3.0/3.1)**：所有小工具后端接口（FastAPI、Node.js）统一使用 OpenAPI 契约，保证前后端通信接口严格对齐。
* **Nginx Reverse Proxy / WebSocket RFC 6455 规范**：针对长连接、反向代理缓冲、超时时间（`proxy_read_timeout`）和升级标头（`Connection "Upgrade"`）的配置标准。

---

## 2. 供 AI 阅读的《系统架构规范文档》（可直接复制）

可以将下方这段 Markdown 内容保存为 `ARCHITECTURE.md`，或者直接全选发送给 AI：

```markdown
# 系统架构设计规范：多容器测试工具集成平台 (Test Tools Web Platform)

## 1. 系统概述与设计目标
- **定位**：一个基于 Web 的轻量级测试工具集成工作台，聚合脚本执行、设备模拟（电梯/摄像头等）等功能。
- **高可用与隔离性**：各个工具在运行时完全独立。任何单一工具的异常崩溃、代码修改、构建或容器重启，不得影响平台其他工具及前端 UI 的正常运行。
- **扩展原则**：遵循开闭原则（OCP），新增工具只需新增独立服务目录并在 Gateway 注册路由，无需侵入改造现有工具。

## 2. 核心架构与技术栈规范

### 2.1 整体拓扑
- **Client (Browser)** -> **API Gateway (Nginx)** -> **Docker Network (Bridge)** -> **Microservices (Tools)**

### 2.2 角色与技术选型
| 服务名称 | 建议技术栈 | 职责与通信协议 |
| :--- | :--- | :--- |
| `frontend` | Vue 3 / React / 原生 JS | 纯静态前端，负责多工具 Tab 面板展示与交互 |
| `gateway` | Nginx (Alpine) | 统一端口接入，静态资源代理，反向代理 HTTP/WebSocket，处理 CORS |
| `tool-script-runner` | Python (FastAPI / Uvicorn) | 负责异步执行测试脚本、管理进程、提供执行日志查看 |
| `tool-elevator-sim` | Node.js 或 Python | 模拟电梯状态机，通过 HTTP 接收指令，通过 WebSocket 广播状态 |
| `tool-camera-sim` | Python (OpenCV/Flask) | 模拟视频流（MJPEG / RTSP 转 HTTP 流）与图像数据生成 |

## 3. 容器生命周期与网络规范

1. **网络隔离**：
   - 建立名为 `tools_network` 的自定义 Docker bridge 网络。
   - 所有业务工具容器**禁止直接对外暴露 host 端口**，仅在 `tools_network` 内部监听，所有流量统一经由 `gateway` 转发。
2. **容错与恢复 (Fault Tolerance)**：
   - 每个容器配置 `restart: unless-stopped`。
   - 每个工具微服务必须配置 `healthcheck`（如 `GET /health`），网关根据健康状态进行请求路由。
3. **日志与状态管理**：
   - 容器内进程遵循 12-Factor 规范：所有日志输出到 `stdout`/`stderr`，避免在容器内持久化日志文件。
   - 脚本执行器如需读写持久化文件，必须使用 Docker Named Volume 明确挂载。

## 4. API 契约与网关路由规则

### 4.1 统一路由前缀
- 静态页面：`/` -> `frontend`
- 脚本工具：`/api/v1/scripts/` -> `tool-script-runner:8000/`
- 电梯模拟：`/api/v1/elevator/` -> `tool-elevator-sim:8001/`
- 摄像头模拟：`/api/v1/camera/` -> `tool-camera-sim:8002/`

### 4.2 WebSocket 支持规范
针对电梯模拟器和持续日志推送等长连接，Nginx 必须显式配置：
```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400s;

```

## 5. 目录结构规范

```text
project-root/
├── docker-compose.yml
├── .env.example
├── gateway/
│   ├── Dockerfile
│   └── nginx.conf
├── frontend/
│   ├── Dockerfile
│   └── src/
└── tools/
    ├── script-runner/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    ├── elevator-sim/
    │   ├── Dockerfile
    │   └── app/
    └── camera-sim/
        ├── Dockerfile
        └── app/

```

## 6. AI 任务交付清单 (Tasks)

请基于上述架构规范，按以下顺序输出代码与配置文件：

1. 编写生产就绪的 `docker-compose.yml`，包含网络定义、健康检查、日志上限与依赖关系。
2. 编写 `gateway/nginx.conf`，实现静态文件托管、API 转发以及 WebSocket 长连接代理。
3. 编写 `tools/script-runner` 的最小可行性实现（FastAPI + 非阻塞脚本调用 + Dockerfile）。
4. 说明如何实现单工具的热重载/单服务重启指令（如 `docker compose restart <service_name>`）。

```

---

## 3. 使用建议

* **作为 Prompt 上下文**：如果使用的是 **Cursor / GitHub Copilot**，建议在项目根目录下新建 `.cursorrules` 或 `ARCHITECTURE.md`，并将上述文档存入，AI 在写代码时会自动遵守这些规范。
* **分阶段生成**：让 AI 先输出 `docker-compose.yml` 和 `nginx.conf`，确认网络拓扑和路由无误后，再让它分别实现 `script-runner`、`elevator-sim` 和 `camera-sim` 的具体业务逻辑。

<ElicitationsGroup message="想要先从哪一步开始落地？">
  <Elicitation label="让 AI 生成标准的 docker-compose.yml 和 nginx.conf" query="请按照上述系统架构规范，生成完整的 docker-compose.yml 和 nginx.conf 配置文件。"/>
  <Elicitation label="设计非阻塞运行外部脚本的 FastAPI 模板代码" query="请提供 script-runner 服务的 FastAPI 详细实现，要求支持异步非阻塞执行外部脚本，并能实时返回进程状态。"/>
  <Elicitation label="了解如何在 Cursor 中配置 .cursorrules" query="如何将这份架构规范配置到 Cursor 的 .cursorrules 中，让 AI 在开发过程中始终遵守？"/>
</ElicitationsGroup>

```