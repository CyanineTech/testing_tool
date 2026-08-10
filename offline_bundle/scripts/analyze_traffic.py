import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

def analyze_wifi_load(log_file='ip_traffic_stats.log'):
    try:
        # 1. 加载数据
        df = pd.read_csv(log_file)
        
        # 2. 计算基本统计量
        rx_max = df['RX_kbps'].max()
        tx_max = df['TX_kbps'].max()
        rx_avg = df['RX_kbps'].mean()
        tx_avg = df['TX_kbps'].mean()

        print("="*50)
        print(f"📊 流量统计分析报告 ({datetime.now().strftime('%Y-%m-%d')})")
        print("-" * 50)
        print(f"单机录得最高下行 (RX): {rx_max:.2f} kbps")
        print(f"单机录得最高上行 (TX): {tx_max:.2f} kbps")
        
        # 3. 9台设备并发推演
        total_peak_mbps = (rx_max + tx_max) * 9 / 1024
        print("-" * 50)
        print(f"🚀 9台设备并发理论峰值: {total_peak_mbps:.2f} Mbps")
        
        # 4. WiFi 标准判定
        print("🛡️  硬件建议:")
        if total_peak_mbps < 100:
            print("   [稳] 当前 TP-Link 1300D 绰绰有余。")
        elif 100 <= total_peak_mbps < 300:
            print("   [警] 接近 WiFi 5 实测极限，建议开启 MU-MIMO。")
        else:
            print("   [危] 强烈建议升级到 Wi-Fi 6 (AX3000+)，以防高延迟丢包。")
        print("=" * 50)

        # 5. 绘图
# 修正版绘图代码
        times = df['Time'].to_numpy()
        rx_vals = df['RX_kbps'].to_numpy()
        tx_vals = df['TX_kbps'].to_numpy()

        plt.figure(figsize=(12, 6))
        plt.plot(times, rx_vals, label='Download (RX)', color='blue', alpha=0.7)
        plt.plot(times, tx_vals, label='Upload (TX)', color='green', alpha=0.7)
        
        plt.title('Real-time Traffic Monitor (Single Device)')
        plt.xlabel('Time')
        plt.ylabel('Speed (kbps)')
        plt.xticks(rotation=45)
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.tight_layout()
        
        # 保存图片
        plt.savefig('traffic_analysis.png')
        print("📈 走势图已保存为: traffic_analysis.png")

    except Exception as e:
        print(f"❌ 运行失败: {e}\n请确保 ip_traffic_stats.log 文件存在且已有数据。")

if __name__ == "__main__":
    analyze_wifi_load()