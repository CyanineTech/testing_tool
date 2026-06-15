#!/bin/bash
# RCS 后端系统状态检查脚本
# 用法: ./check_rcs_status.sh <rcs_ip>
# 示例: ./check_rcs_status.sh 192.168.1.170

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <rcs_ip>"
    echo "示例: $0 192.168.1.170"
    exit 1
fi

HOST="$1"
USER="robot"
PASS="qweasdzxc"
SSH_TIMEOUT="${SSH_TIMEOUT:-30}"

ssh_remote() {
    local remote_cmd="$1"
    local remote_quoted
    remote_quoted=$(printf '%q' "$remote_cmd")
    timeout "$SSH_TIMEOUT" sshpass -p "$PASS" ssh -T \
        -o PreferredAuthentications=password \
        -o PubkeyAuthentication=no \
        -o NumberOfPasswordPrompts=1 \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=5 \
        -o ServerAliveInterval=3 \
        -o ServerAliveCountMax=1 \
        "$USER@$HOST" bash --noprofile --norc -lc "$remote_quoted"
}

echo "======================================"
echo "RCS 系统状态检查: $HOST"
echo "时间: $(date)"
echo "======================================"

# 1. 连通性
echo ""
echo "== 1. 连通性 =="
if ping -c 1 -W 2 "$HOST" > /dev/null 2>&1; then
    echo "[OK] Ping 正常"
else
    echo "[FAIL] Ping 不通"
    exit 1
fi

# 2. Docker 基础服务
echo ""
echo "== 2. Docker 基础服务 =="
ssh_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null"

# 3. 关键端口检查
echo ""
echo "== 3. 关键端口检查 =="
ssh_remote '
ports="3737:后端API 9998:调度中心 18888:主站通信 4040:地图服务 4096:充电服务 3434:认证中心"
for item in $ports; do
    port=$(echo $item | cut -d: -f1)
    name=$(echo $item | cut -d: -f2)
    if ss -tlnp | grep -q ":$port "; then
        echo "[OK] $name (:$port) 正在监听"
    else
        echo "[FAIL] $name (:$port) 未监听"
    fi
done
'

# 4. Supervisor 服务状态
echo ""
echo "== 4. Supervisor 服务 =="
ssh_remote "supervisorctl status 2>/dev/null || echo '[INFO] supervisor 未运行'"

# 5. 后端 API 健康检查
echo ""
echo "== 5. 后端 API 检查 =="
ssh_remote "curl -s -o /dev/null -w 'HTTP状态码: %{http_code}\n响应时间: %{time_total}s\n' http://127.0.0.1:3737/infos/ros/ 2>/dev/null || echo '[FAIL] 后端 API 无响应'"

# 6. 数据库连接
echo ""
echo "== 6. 数据库状态 =="
ssh_remote '
# Redis
if docker exec docker-redis_6_2-1 redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[OK] Redis 正常"
else
    echo "[FAIL] Redis 异常"
fi
# MongoDB
if docker exec docker-mongo_5_0-1 mongosh --eval "db.adminCommand({ping:1})" --quiet 2>/dev/null | grep -q "ok"; then
    echo "[OK] MongoDB 正常"
else
    echo "[FAIL] MongoDB 异常"
fi
# MySQL
if docker exec docker-mysql_5_7-1 mysqladmin ping -u root 2>/dev/null | grep -q alive; then
    echo "[OK] MySQL 正常"
else
    echo "[FAIL] MySQL 异常"
fi
'

# 7. 磁盘空间
echo ""
echo "== 7. 磁盘空间 =="
ssh_remote "df -h / /home 2>/dev/null | grep -v tmpfs"

# 8. 系统负载
echo ""
echo "== 8. 系统资源 =="
ssh_remote "uptime; echo ''; free -h | head -2"

# 9. 最近错误日志
echo ""
echo "== 9. 最近错误日志(后端) =="
ssh_remote "tail -20 /var/run/log/new_backend.log 2>/dev/null | grep -i 'error\|fail\|exception' | tail -5 || echo '无错误日志'"

echo ""
echo "======================================"
echo "检查完成"
echo "======================================"
