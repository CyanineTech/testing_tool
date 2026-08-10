from scapy.all import sniff, IP
import time
import os

# 配置信息
TARGET_IP_1 = "192.168.127.1"
TARGET_IP_2 = "192.168.127.254"
INTERFACE = "enp88s0"
LOG_FILE = "p2p_traffic_realtime.log"

# 初始化统计变量
stats = {"rx_bytes": 0, "tx_bytes": 0, "last_time": time.time()}

# 如果文件不存在，写入表头
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        f.write("Time,RX_kbps,TX_kbps\n")

def packet_callback(pkt):
    global stats
    if pkt.haslayer(IP):
        src = pkt[IP].src
        dst = pkt[IP].dst
        size = len(pkt)

        # 判定方向
        if src == TARGET_IP_1 and dst == TARGET_IP_2:
            stats["tx_bytes"] += size
        elif src == TARGET_IP_2 and dst == TARGET_IP_1:
            stats["rx_bytes"] += size

        # 每隔 1 秒计算并保存
        current_time = time.time()
        if current_time - stats["last_time"] >= 1.0:
            rx_kbps = (stats["rx_bytes"] * 8) / 1024
            tx_kbps = (stats["tx_bytes"] * 8) / 1024
            timestamp = time.strftime("%H:%M:%S")
            
            log_line = f"{timestamp},{rx_kbps:.2f},{tx_kbps:.2f}\n"
            with open(LOG_FILE, "a") as f:
                f.write(log_line)
                f.flush()  # 强制刷新缓存到硬盘
                os.fsync(f.fileno()) # 确保物理写入
            
            # 重置计数器
            stats["rx_bytes"] = 0
            stats["tx_bytes"] = 0
            stats["last_time"] = current_time

print(f"🚀 开始监控 {TARGET_IP_1} <-> {TARGET_IP_2} ...")
sniff(iface=INTERFACE, prn=packet_callback, filter=f"host {TARGET_IP_1} and host {TARGET_IP_2}", store=0)