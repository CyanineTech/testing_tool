#!/bin/bash
# RCS 主机历史重启回溯脚本
# 用法: ./check_rcs_reboot_history.sh <rcs_ip>
# 示例: ./check_rcs_reboot_history.sh 192.168.1.170

set -e

if [ -z "$1" ]; then
    echo "用法: $0 <rcs_ip> [window_start] [window_end]"
    echo "示例: $0 192.168.1.170"
    echo "示例: $0 192.168.1.170 '2026-06-15 17:10:00' '2026-06-15 18:10:00'"
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
echo "RCS 历史重启回溯: $HOST"
echo "时间: $(date)"
if [ -n "$WINDOW_START" ] || [ -n "$WINDOW_END" ]; then
    echo "时间窗口: ${WINDOW_START:-N/A} ~ ${WINDOW_END:-N/A}"
fi
echo "======================================"

print_section() {
    local title="$1"
    local command="$2"
    echo ""
    echo "== $title =="
    ssh_remote "$command" || echo "[WARN] $title 获取失败"
}

echo ""
echo "== 1. 当前开机时间 =="
ssh_remote "who -b 2>/dev/null; echo '---'; uptime -s 2>/dev/null" || echo "[WARN] 当前开机时间获取失败"

echo ""
echo "== 2. 最近 boot 历史 =="
ssh_remote "journalctl --list-boots -n 4 --no-pager 2>/dev/null || last -x | head -n 8" || echo "[WARN] boot 历史获取失败"

echo ""
echo "== 3. 上一个 boot 的 kernel / docker / supervisor =="
ssh_remote '
echo "--- kernel(-1) ---"
journalctl -k -b -1 -n 120 --no-pager 2>/dev/null || true
echo
echo "--- docker(-1) ---"
journalctl -u docker -b -1 -n 120 --no-pager 2>/dev/null || true
echo
echo "--- supervisor(-1) ---"
journalctl -u supervisor -b -1 -n 120 --no-pager 2>/dev/null || true
echo
echo "--- supervisor backend focus(-1) ---"
journalctl -u supervisor -b -1 --no-pager 2>/dev/null | grep -i 'master_backend\|cbs_master_server\|exit\|exited\|fatal\|spawnerr\|backoff\|waiting for' | tail -n 80 || true
' || echo "[WARN] 上一个 boot 的 kernel/docker/supervisor 日志获取失败"

echo ""
echo "== 4. 上一个 boot 的 backend / mysql 容器日志 =="
ssh_remote '
echo "--- backend log file ---"
tail -n 120 /var/run/log/new_backend.log 2>/dev/null || true
echo
echo "--- backend container ---"
docker logs docker-backend_1 --tail 120 2>/dev/null || true
echo
echo "--- mysql container ---"
docker logs docker-mysql_5_7-1 --tail 120 2>/dev/null || true
' || echo "[WARN] 上一个 boot 的 backend/mysql 日志获取失败"

echo ""
echo "== 5. 最近重启前后的错误关键词 =="
ssh_remote "
journalctl -b -1 --no-pager 2>/dev/null | grep -i 'error\\|fail\\|exception\\|oom\\|segfault\\|killed process\\|connection refused\\|supervisor\\|backend\\|mysql' | tail -n 80 || true
" || echo "[WARN] 重启前后错误关键词提取失败"

if [ -n "$WINDOW_START" ] && [ -n "$WINDOW_END" ]; then
echo ""
echo "== 6. 指定时间窗口内的关键日志 =="
ssh_remote "
echo '--- supervisor window ---'
journalctl -u supervisor --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | tail -n 120 || true
echo
echo '--- docker window ---'
journalctl -u docker --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | tail -n 120 || true
echo
echo '--- kernel window ---'
journalctl -k --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | tail -n 120 || true
echo
echo '--- supervisor backend focus window ---'
journalctl -u supervisor --since '$WINDOW_START' --until '$WINDOW_END' --no-pager 2>/dev/null | grep -i 'master_backend\\|cbs_master_server\\|exit\\|exited\\|fatal\\|spawnerr\\|backoff\\|waiting for' | tail -n 80 || true
" || echo "[WARN] 指定时间窗口日志提取失败"
fi

echo ""
echo "======================================"
echo "检查完成"
echo "======================================"
