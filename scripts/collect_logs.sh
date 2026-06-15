#!/bin/bash
# AMR 日志收集脚本
# 用法: ./collect_logs.sh <amr_ip> [时间关键词]
# 示例: ./collect_logs.sh 192.168.1.250 "2025_04_02"
#       ./collect_logs.sh leefung-t8

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <amr_ip_or_hostname> [时间关键词]"
    echo "示例: $0 192.168.1.250 2025_04_02"
    exit 1
fi

HOST="$1"
TIME_KEY="${2:-}"
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
OUTPUT_DIR="/tmp/amr_logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "======================================"
echo "AMR 日志收集: $HOST"
echo "输出目录: $OUTPUT_DIR"
echo "======================================"

# 1. 收集系统信息
echo "收集系统信息..."
ssh_remote "hostname; echo '---'; cat /home/robot/static/config/robot_id.yaml; echo '---'; uptime; echo '---'; df -h /" > "$OUTPUT_DIR/system_info.txt"

# 2. 收集 USB 状态
echo "收集 USB 状态..."
ssh_remote "lsusb -t" > "$OUTPUT_DIR/usb_tree.txt"

# 3. 收集内核日志
echo "收集内核日志..."
ssh_remote "dmesg -T | tail -200" > "$OUTPUT_DIR/dmesg.txt"

# 4. 收集 ROS 日志（最新的进模式日志）
echo "收集 ROS 日志..."
if [ -n "$TIME_KEY" ]; then
    LOGDIR=$(ssh_remote "ls -d /home/robot/log/not_permanent/*$TIME_KEY* 2>/dev/null | tail -1")
else
    LOGDIR=$(ssh_remote "ls -dt /home/robot/log/not_permanent/*/ 2>/dev/null | head -1")
fi

if [ -n "$LOGDIR" ]; then
    echo "  日志目录: $LOGDIR"
    ssh_remote "tail -500 $LOGDIR/default.launch 2>/dev/null" > "$OUTPUT_DIR/default_launch.txt" 2>/dev/null || true
    ssh_remote "tail -500 $LOGDIR/mobile_base.launch 2>/dev/null" > "$OUTPUT_DIR/mobile_base_launch.txt" 2>/dev/null || true
    ssh_remote "tail -500 $LOGDIR/pure_laser_amcl.launch 2>/dev/null" > "$OUTPUT_DIR/pure_laser_amcl.txt" 2>/dev/null || true
    ssh_remote "tail -500 $LOGDIR/state_monitor_wrapper.launch 2>/dev/null" > "$OUTPUT_DIR/state_monitor_wrapper.txt" 2>/dev/null || true
    # 提取错误行
    ssh_remote "grep -i 'error\|fail\|exception\|warn' $LOGDIR/default.launch 2>/dev/null | tail -100" > "$OUTPUT_DIR/errors_default.txt" 2>/dev/null || true
    ssh_remote "grep -i 'error\|fail\|exception\|warn' $LOGDIR/mobile_base.launch 2>/dev/null | tail -100" > "$OUTPUT_DIR/errors_mobile_base.txt" 2>/dev/null || true
    ssh_remote "grep -i 'laser\|scan\|lidar\|radar' $LOGDIR/*.launch 2>/dev/null | tail -200" > "$OUTPUT_DIR/radar_keywords.txt" 2>/dev/null || true
else
    echo "  [INFO] 未找到日志目录"
fi

if [ -n "$TIME_KEY" ]; then
    echo "收集 caution 录包索引..."
    DATE_COMPACT=$(printf '%s' "$TIME_KEY" | tr -d '_')
    ssh_remote "find /home/robot/autobag -maxdepth 1 -type f | grep '$DATE_COMPACT' | tail -100" > "$OUTPUT_DIR/caution_files.txt" 2>/dev/null || true
fi

# 5. 收集后端日志
echo "收集后端日志..."
ssh_remote "tail -200 /home/robot/log/backend_log/error_manage_server.log 2>/dev/null" > "$OUTPUT_DIR/backend_log.txt" 2>/dev/null || true

# 6. CAN 状态
echo "收集 CAN 状态..."
ssh_remote "ip -s -d link show can0 2>/dev/null" > "$OUTPUT_DIR/can_status.txt" 2>/dev/null || true

# 7. Docker 状态
echo "收集 Docker 状态..."
ssh_remote "docker ps -a 2>/dev/null; echo '---'; docker logs cy_yolo_human_detect --tail 20 2>/dev/null" > "$OUTPUT_DIR/docker_status.txt" 2>/dev/null || true

# 8. Chrony 状态
echo "收集时间同步状态..."
ssh_remote "chronyc sources 2>/dev/null; echo '---'; chronyc tracking 2>/dev/null" > "$OUTPUT_DIR/chrony.txt" 2>/dev/null || true

echo ""
echo "======================================"
echo "日志收集完成，保存在: $OUTPUT_DIR"
echo "文件列表:"
ls -la "$OUTPUT_DIR"
echo "======================================"
