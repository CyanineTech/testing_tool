#!/bin/bash
# AMR 日志收集脚本
# 用法: ./collect_logs.sh <amr_ip> [时间关键词]
# 示例: ./collect_logs.sh 192.168.1.250 "2025_04_02"
#       ./collect_logs.sh leefung-t8

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <amr_ip_or_hostname> [时间关键词] [window_start] [window_end]"
    echo "示例: $0 192.168.1.250 2025_04_02"
    echo "示例: $0 192.168.1.250 '' '2026-06-15 17:10:00' '2026-06-15 18:10:00'"
    exit 1
fi

HOST="$1"
TIME_KEY="${2:-}"
WINDOW_START="${3:-}"
WINDOW_END="${4:-}"
TARGET_TS="${5:-}"
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

resolve_boot_logdir() {
    local base_dir="$1"
    if [ -n "$TARGET_TS" ]; then
        ssh_remote "TARGET_KEY=\$(date -d '$TARGET_TS' +%Y_%m_%d-%H_%M_%S 2>/dev/null) && ls -1 $base_dir/ 2>/dev/null | awk -v target=\"\$TARGET_KEY\" '\$1 <= target' | tail -1 | sed 's#^#$base_dir/#'"
    elif [ -n "$WINDOW_END" ]; then
        ssh_remote "TARGET_KEY=\$(date -d '$WINDOW_END' +%Y_%m_%d-%H_%M_%S 2>/dev/null) && ls -1 $base_dir/ 2>/dev/null | awk -v target=\"\$TARGET_KEY\" '\$1 <= target' | tail -1 | sed 's#^#$base_dir/#'"
    elif [ -n "$TIME_KEY" ]; then
        ssh_remote "ls -d $base_dir/*$TIME_KEY* 2>/dev/null | tail -1"
    else
        ssh_remote "ls -dt $base_dir/*/ 2>/dev/null | head -1"
    fi
}
OUTPUT_DIR="/tmp/amr_logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "======================================"
echo "AMR 日志收集: $HOST"
echo "输出目录: $OUTPUT_DIR"
if [ -n "$WINDOW_START" ] || [ -n "$WINDOW_END" ]; then
    echo "时间窗口: ${WINDOW_START:-N/A} ~ ${WINDOW_END:-N/A}"
fi
if [ -n "$TARGET_TS" ]; then
    echo "目标故障时间: $TARGET_TS"
fi
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

# 4. 收集 ROS 日志（按故障时间回溯对应开机目录）
echo "收集 ROS 日志..."
LOGDIR=$(resolve_boot_logdir "/home/robot/log/not_permanent")
PERM_LOGDIR=$(resolve_boot_logdir "/home/robot/log/permanent")
PERM_ERROR_MONITOR_FILE=""
if [ -n "$PERM_LOGDIR" ]; then
    PERM_ERROR_MONITOR_FILE=$(ssh_remote "find '$PERM_LOGDIR' -maxdepth 3 \\( -type f -o -type l \\) -name 'error_monitor_server.launch' 2>/dev/null | head -1")
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
    if [ -n "$PERM_ERROR_MONITOR_FILE" ]; then
        ssh_remote "tail -500 '$PERM_ERROR_MONITOR_FILE' 2>/dev/null" > "$OUTPUT_DIR/error_monitor_server.txt" 2>/dev/null || true
    fi
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

if [ -n "$WINDOW_START" ] && [ -n "$WINDOW_END" ]; then
    echo "收集历史时间窗口日志..."
    ssh_remote "journalctl -k --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | tail -200" > "$OUTPUT_DIR/kernel_window.txt" 2>/dev/null || true
    ssh_remote "journalctl -k --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | grep -i 'oom\\|out of memory\\|killed process\\|kswapd\\|swap\\|page allocation failure\\|allocstall\\|can\\|pcan\\|usb\\|disconnect\\|reset embedded\\|driver' | tail -200" > "$OUTPUT_DIR/kernel_window_keywords.txt" 2>/dev/null || true
    ssh_remote "journalctl --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | grep -i 'oom\\|out of memory\\|killed process\\|kswapd\\|swap\\|page allocation failure\\|allocstall\\|can\\|pcan\\|usb\\|disconnect\\|reset embedded\\|driver\\|manual\\|recover\\|retry' | tail -200" > "$OUTPUT_DIR/system_window_keywords.txt" 2>/dev/null || true
    if [ -n "$LOGDIR" ]; then
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) { print \$0 }' $LOGDIR/default.launch 2>/dev/null | tail -400" > "$OUTPUT_DIR/default_launch_window.txt" 2>/dev/null || true
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) { print \$0 }' $LOGDIR/mobile_base.launch 2>/dev/null | tail -400" > "$OUTPUT_DIR/mobile_base_window.txt" 2>/dev/null || true
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) { print \$0 }' $LOGDIR/state_monitor_wrapper.launch 2>/dev/null | tail -400" > "$OUTPUT_DIR/state_monitor_window.txt" 2>/dev/null || true
        if [ -n "$PERM_ERROR_MONITOR_FILE" ]; then
            ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) { print \$0 }' '$PERM_ERROR_MONITOR_FILE' 2>/dev/null | tail -400" > "$OUTPUT_DIR/error_monitor_window.txt" 2>/dev/null || true
        fi
    fi
fi

if [ -n "$TARGET_TS" ] && [ -n "$LOGDIR" ]; then
    echo "收集故障秒级对齐证据..."
    TARGET_EPOCH=$(date -d "$TARGET_TS" +%s 2>/dev/null || true)
    if [ -n "$TARGET_EPOCH" ]; then
        EXACT_START=$((TARGET_EPOCH - 20))
        EXACT_END=$((TARGET_EPOCH + 60))
        echo "故障时间戳窗口: ${EXACT_START} ~ ${EXACT_END}" > "$OUTPUT_DIR/exact_window_meta.txt"
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) {ts=substr(\$0,RSTART+1,RLENGTH-2)+0; if (ts>=$EXACT_START && ts<=$EXACT_END) print}' $LOGDIR/default.launch 2>/dev/null | tail -200" > "$OUTPUT_DIR/default_launch_exact.txt" 2>/dev/null || true
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) {ts=substr(\$0,RSTART+1,RLENGTH-2)+0; if (ts>=$EXACT_START && ts<=$EXACT_END) print}' $LOGDIR/mobile_base.launch 2>/dev/null | tail -200" > "$OUTPUT_DIR/mobile_base_exact.txt" 2>/dev/null || true
        ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) {ts=substr(\$0,RSTART+1,RLENGTH-2)+0; if (ts>=$EXACT_START && ts<=$EXACT_END) print}' $LOGDIR/state_monitor_wrapper.launch 2>/dev/null | tail -200" > "$OUTPUT_DIR/state_monitor_exact.txt" 2>/dev/null || true
        if [ -n "$PERM_ERROR_MONITOR_FILE" ]; then
            ssh_remote "awk 'match(\$0, /\\[[0-9]+\\.[0-9]+\\]/) {ts=substr(\$0,RSTART+1,RLENGTH-2)+0; if (ts>=$EXACT_START && ts<=$EXACT_END) print}' '$PERM_ERROR_MONITOR_FILE' 2>/dev/null | tail -200" > "$OUTPUT_DIR/error_monitor_exact.txt" 2>/dev/null || true
        fi
    fi
fi

echo ""
echo "======================================"
echo "日志收集完成，保存在: $OUTPUT_DIR"
echo "文件列表:"
ls -la "$OUTPUT_DIR"
echo "======================================"
