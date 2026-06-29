#!/bin/bash
# 网络诊断脚本
# 用法: ./network_diag.sh <amr_ip_or_hostname>
# 示例: ./network_diag.sh 192.168.1.250
#
# 说明:
# - 本脚本主要用于“当前网络状态快照”。
# - 如果是历史掉线、历史网络抖动或任务链路中断复盘，
#   应优先结合故障时间、主从机日志、上一个 boot 或对应 not_permanent 目录回看，而不是只看当前连通性。

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <amr_ip_or_hostname> [window_start] [window_end]"
    exit 1
fi

HOST="$1"
WINDOW_START="${2:-}"
WINDOW_END="${3:-}"
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
if [ -n "$WINDOW_START" ] || [ -n "$WINDOW_END" ]; then
    echo "时间窗口: ${WINDOW_START:-N/A} ~ ${WINDOW_END:-N/A}"
fi
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

if [ -n "$WINDOW_START" ] && [ -n "$WINDOW_END" ]; then
echo ""
echo "== 8. 历史时间窗口回溯 =="
ssh_remote "
echo '--- kernel window ---'
journalctl -k --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | tail -n 120 || true
echo
echo '--- network stack window ---'
journalctl --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | grep -i 'network\\|wifi\\|wlan\\|tailscale\\|vpn\\|disconnect\\|reconnect\\|carrier\\|dhcp\\|dns\\|ssh' | tail -n 120 || true
" || echo "[WARN] 历史网络时间窗口日志提取失败"
fi
