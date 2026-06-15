#!/bin/bash
# AMR 状态全面检查脚本
# 用法: ./check_amr_status.sh <amr_ip_or_hostname>
# 示例: ./check_amr_status.sh 192.168.1.250
#       ./check_amr_status.sh leefung-t8

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <amr_ip_or_hostname>"
    echo "示例: $0 192.168.1.250"
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
echo "AMR 状态检查: $HOST"
echo "时间: $(date)"
echo "======================================"

# 1. 连通性检查
echo ""
echo "== 1. 连通性 =="
if ping -c 1 -W 2 "$HOST" > /dev/null 2>&1; then
    echo "[OK] Ping 正常"
else
    echo "[FAIL] Ping 不通，请检查网络连接"
    exit 1
fi

if ssh_remote 'echo ok' > /dev/null 2>&1; then
    echo "[OK] SSH 连接正常"
else
    echo "[FAIL] SSH 连接失败"
    exit 1
fi

# 2. 机器人基本信息
echo ""
echo "== 2. 机器人基本信息 =="
ssh_remote "cat /home/robot/static/config/robot_id.yaml 2>/dev/null; echo ''; hostname; echo ''; uptime"

# 3. USB 设备状态
echo ""
echo "== 3. USB 设备状态 =="
ssh_remote "lsusb -t 2>/dev/null"

echo ""
echo "-- USB 关键设备检查 --"
ssh_remote '
missing=""
# Intel 深度相机
if ! lsusb | grep -q "8086:"; then missing="${missing}Intel深度相机 "; fi
# Orbbec 深度相机
if ! lsusb | grep -q "2bc5:"; then missing="${missing}Orbbec深度相机 "; fi
# PCAN
if ! lsusb | grep -q "0c72:"; then missing="${missing}PCAN "; fi
# CH341 串口
if ! lsusb | grep -q "1a86:"; then missing="${missing}CH341串口 "; fi
if [ -z "$missing" ]; then
    echo "[OK] 所有关键USB设备已识别"
else
    echo "[WARN] 以下设备未检测到: $missing"
fi
'

# 4. ROS 状态
echo ""
echo "== 4. ROS 节点状态 =="
ssh_remote "source /opt/ros/noetic/setup.bash 2>/dev/null; rosnode list 2>/dev/null | wc -l | xargs -I {} echo 'ROS节点数量: {}'; rosnode list 2>/dev/null || echo '[INFO] ROS未运行或未在模式中'"

# 5. CAN 总线状态
echo ""
echo "== 5. CAN 总线状态 =="
ssh_remote "ip -s -d link show can0 2>/dev/null || echo '[INFO] CAN 接口未找到'"

# 6. Docker 容器
echo ""
echo "== 6. Docker 容器状态 =="
ssh_remote "docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo '[INFO] Docker未安装或无容器'"

# 7. 磁盘空间
echo ""
echo "== 7. 磁盘空间 =="
ssh_remote "df -h / /home 2>/dev/null | grep -v tmpfs"

# 8. 自动录包空间
echo ""
echo "== 8. 自动录包 =="
ssh_remote "du -sh /home/robot/autobag 2>/dev/null || echo '无autobag目录'"

# 9. 时间同步
echo ""
echo "== 9. 时间同步状态 =="
ssh_remote "chronyc sources 2>/dev/null | head -5 || echo '[WARN] chrony 未安装'"

# 10. 系统负载
echo ""
echo "== 10. 系统资源 =="
ssh_remote "echo '--- CPU/内存 ---'; top -bn1 | head -5; echo ''; echo '--- 温度 ---'; cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | awk '{printf \"%.1f°C\\n\", \$1/1000}' || echo 'N/A'"

echo ""
echo "======================================"
echo "检查完成"
echo "======================================"
