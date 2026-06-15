#!/bin/bash
# 网络诊断脚本
# 用法: ./network_diag.sh <amr_ip_or_hostname>
# 示例: ./network_diag.sh 192.168.1.250

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <amr_ip_or_hostname>"
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
echo "网络诊断: $HOST"
echo "时间: $(date)"
echo "======================================"

# 1. 本机到 AMR 的连通性
echo ""
echo "== 1. 本机 → AMR 连通性 =="
ping -c 5 "$HOST" 2>/dev/null || echo "[FAIL] 无法 ping 通"

# 2. AMR 网络接口
echo ""
echo "== 2. AMR 网络接口 =="
ssh_remote "ip addr show | grep -E 'inet |state'" 2>/dev/null

# 3. AMR 到 RCS 主机
echo ""
echo "== 3. AMR → RCS/网关连通性 =="
ssh_remote '
echo "--- 默认路由 ---"
ip route | head -3
echo ""
echo "--- 检查常见目标 ---"
# 尝试 ping 1300D 路由器
if ping -c 1 -W 2 192.168.127.254 > /dev/null 2>&1; then
    echo "[OK] 1300D 路由器 (192.168.127.254)"
else
    echo "[FAIL] 1300D 路由器 (192.168.127.254)"
fi
# 尝试 ping RCS 主机（需要知道具体IP）
for rcs_ip in 192.168.1.170 10.3.8.47; do
    if ping -c 1 -W 2 $rcs_ip > /dev/null 2>&1; then
        echo "[OK] RCS 主机 ($rcs_ip)"
    fi
done
'

# 4. WiFi 状态
echo ""
echo "== 4. WiFi 状态 =="
ssh_remote "nmcli d wifi list 2>/dev/null | head -10 || iwconfig 2>/dev/null | grep -A3 'wl'" 2>/dev/null

# 5. Tailscale 状态
echo ""
echo "== 5. Tailscale VPN =="
ssh_remote "tailscale status 2>/dev/null | head -15 || echo '[INFO] Tailscale 未安装'" 2>/dev/null

# 6. DNS 解析
echo ""
echo "== 6. DNS 解析 =="
ssh_remote "cat /etc/resolv.conf | grep -v '^#'; echo ''; nslookup google.com 2>/dev/null | head -5 || echo '[INFO] DNS 查询失败'" 2>/dev/null

# 7. 关键端口连通性
echo ""
echo "== 7. 关键端口检查 =="
ssh_remote '
# ROS Master
if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/11311" 2>/dev/null; then
    echo "[OK] ROS Master (11311)"
else
    echo "[INFO] ROS Master (11311) 未监听"
fi
# 后端
if timeout 2 bash -c "echo > /dev/tcp/127.0.0.1/3737" 2>/dev/null; then
    echo "[OK] 后端 API (3737)"
else
    echo "[INFO] 后端 API (3737) 未监听"
fi
# 前雷达
if ping -c 1 -W 1 10.10.10.101 > /dev/null 2>&1; then
    echo "[OK] 前雷达 (10.10.10.101)"
else
    echo "[WARN] 前雷达 (10.10.10.101) 不通"
fi
# 后雷达
if ping -c 1 -W 1 10.10.11.101 > /dev/null 2>&1; then
    echo "[OK] 后雷达 (10.10.11.101)"
else
    echo "[WARN] 后雷达 (10.10.11.101) 不通"
fi
'

echo ""
echo "======================================"
echo "网络诊断完成"
echo "======================================"
