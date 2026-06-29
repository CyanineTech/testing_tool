# AMR 与 RCS 系统高级日志排查 SOP (AI 专用指南)

> **核心纪律：** 作为 AI 排障助手，你在查询本地日志时**必须**遵守以下取证规则。严禁执行无限制的全文 `cat` 或大范围无边界的 `grep`，所有日志检索命令**必须**设置返回行数上限（如 `tail -n 50`）或明确的时间区间，否则将导致系统上下文崩溃。

## 1. 结构化系统服务日志查询 (Systemd / Journalctl)

对于由 `systemd` 托管的后台服务（包括 ROS 节点守护进程、网络服务、自研后端服务），这是最精准的查法。

### 取证规则：
1. **精确时间段排查（首选）：** 提取故障时间，转换为 `YYYY-MM-DD HH:MM:SS` 格式。
   * *命令示例：* `journalctl -u [服务名] --since "2026-06-16 14:00:00" --until "2026-06-16 14:10:00" --no-pager`
2. **近期相对时间排查：**
   * *命令示例：* `journalctl -u [服务名] --since "30 minutes ago" --no-pager`
3. **内核故障跨重启排查：** 针对底盘硬件断连或网络硬件报错。
   * *当前开机：* `journalctl -k --since "1 hour ago" --no-pager`
   * *上一次开机（-1），上上次开机（-2）：* `journalctl -k -b -1 --no-pager`

---

## 2. 动态目录寻址日志查询（按开机时间分卷的 ROS 日志）

**核心约束：** `/home/robot/log/not_permanent/` 下的日志文件夹是按**开机时间**（`YYYY_MM_DD-HH_MM_SS`）生成的。当用户给出具体的故障时间（如 "2026-06-13 01:14:15"），你**绝对不能**直接用该时间去拼接目录名，必须先找到包含该时间段的“上一次开机目录”。

### 取证步骤：
**第 1 步：格式化目标时间并查找对应目录**
将用户提供的时间转换为下划线与短横线格式（如 `2026_06_13-01_14_15`），使用 `awk` 过滤出所有早于该时间的文件夹，并取最近的一个。
* *执行命令获取目录名：*
  `ls -1 /home/robot/log/not_permanent/ | awk '$1 <= "2026_06_13-01_14_15"' | tail -n 1`

**第 2 步：拿到目录名后，执行具体日志查询**
假设第 1 步返回结果为 `2026_06_12-14_05_04`，拼接完整绝对路径进行排查。
* *特定模块报错速查：*
  `grep -i "error" /home/robot/log/not_permanent/2026_06_12-14_05_04/rosout.log | tail -n 50`
* *特定时间点附件精准匹配：*
  `grep "^\[.* 01:1[0-9]:.*\]" /home/robot/log/not_permanent/2026_06_12-14_05_04/default.launch | tail -n 50`

---

## 3. 滚动轮转日志查询（数字后缀 .log, .log.1 等）

**核心约束：** `/home/robot/log/backend_log/` 下的日志会滚动轮转。最新日志在 `.log` 中，旧日志依次顺延至 `.log.1`, `.log.2`。排查特定时间点时，**绝对不能只查最新文件**，必须覆盖历史轮转记录。

### 取证步骤：
**第 1 步：利用文件修改时间定界（必须先执行）**
查看所有同名轮转日志的最后修改时间，推断目标故障时间落在哪个文件内。
* *执行定界命令：*
  `ls -lt --time-style="+%Y-%m-%d %H:%M:%S" /home/robot/log/backend_log/slave_backend.log*`

**第 2 步：跨文件通配搜索（纯文本）**
如果确认目标时间落在未压缩的 `.log` 或 `.log.x` 中，使用带通配符的 `grep` 跨文件搜索，**必须限制输出行数**。
* *特定时间搜索：*
  `grep "^\[.*14:05:.*\]" /home/robot/log/backend_log/slave_backend.log* | tail -n 50`
* *报错摘要搜索：*
  `grep -i "error\|exception\|timeout" /home/robot/log/backend_log/slave_backend.log* | tail -n 50`

**第 3 步：压缩文件搜索（.gz）**
如果在第 1 步发现目标时间已经落入被压缩的历史日志（如 `.log.5.gz`），**必须使用 `zgrep`**。
* *压缩包特定时间搜索：*
  `zgrep "^\[.*14:05:.*\]" /home/robot/log/backend_log/slave_backend.log*.gz | tail -n 50`
