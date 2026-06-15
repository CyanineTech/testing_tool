# 部署与运维手册

## 系统服务 (systemd)

| 服务 | 功能 | 备注 |
|------|------|------|
| first-boot.service | 配置网络连接文件 | 新机仅运行一次后自动关闭 |
| update-robot-id.service | 计算机器人ID | 新机仅运行一次后自动关闭 |
| docker-compose.service | 加载Docker镜像并开启容器 | 每次开机自动启动 |
| verify_ros_env_for_supervisor.service | 更新supervisor环境变量(ROS) | 每次开机自动启动 |
| supervisor.service | 开启supervisor | 每次开机自动启动 |

启用服务：
```bash
sudo systemctl enable <service>
sudo systemctl start <service>
```

## 网络配置

### 镜像中预设连接

| 连接名 | 类型 | 默认IP | 备注 |
|--------|------|--------|------|
| router_wire | 有线 | 192.168.127.1/24, 10.10.10.100/24, 10.10.11.100/24 | 自动连接，工作环境 |
| WiFi | 无线 | 192.168.1.2/24 | 默认连TP-LINK_5G_4A49，办公室需关闭 |
| CTROS_Hotspot | 热点 | - | 仅存储信息，不通过此文件开启 |

### 修改有线网络
```bash
sudo nmcli connection edit router_wire
# 进入 ipv4 → addresses
goto ipv4
goto addresses
remove 192.168.1.239/24
add 192.168.1.XXX/24
back
set gateway 192.168.1.1
set dns 192.168.1.1
save
quit

# 重新连接
sudo nmcli connection down router_wire && sudo nmcli connection up router_wire
```

### 修改无线网络
```bash
sudo nmcli connection edit WiFi
goto wifi
set ssid <SSID>
back
goto wifi-sec
set psk <密码>
back
goto ipv4
goto addresses
remove 192.168.1.2/24
add XXX.XXX.XXX.XXX/xx
back
save
quit
```

### 修改主机 IP
1. 修改 `~/static/config/master_slave_system.yaml` 中 IP
   ```bash
   # vim 全局替换
   :%s/192.168.1.123/192.168.1.234/g
   ```
2. 修改网络配置 (nmcli 或从机页面)
3. 重启主机

### 修改从机 IP
1. 退出联机模式
2. 修改网络 IP (从机页面或 nmcli)

### 单机忘记剔除处理
```bash
nano ~/static/config/master.yaml
# Ctrl+\ 替换所有旧IP为 127.0.0.1
# 重启
```

### 切换国内源
```bash
sudo sed -i 's,p://archive.ubuntu,ps://mirrors.cloud.tencent,g' /etc/apt/sources.list
sudo sed -i 's,pkgs.tailscale.com/stable,mirrors.ustc.edu.cn/tailscale,g' /etc/apt/sources.list.d/tailscale.list
sudo sed -i 's,p://mirrors.tencent,ps://mirrors.cloud.tencent,g' /etc/apt/sources.list.d/ros-latest.list
sudo sed -i 's,download.docker.com,mirrors.cloud.tencent.com/docker-ce,g' /etc/apt/sources.list.d/docker.list
```

## 硬件配置

### CAN 总线
```bash
# root 用户执行
echo -e "can\ncan_raw" > /etc/modules-load.d/can.conf
echo -e "[Match]\nName=can0\n\n[CAN]\nBitRate=500K\nRestartSec=100ms" > /etc/systemd/network/80-can.network
```

解决 can0 导致启动变慢：修改 `/lib/systemd/system/systemd-networkd-wait-online.service`，在 `ExecStart` 末尾加 `--ignore can0`

### 声卡设置
```bash
aplay -l  # 找到目标声卡 card ID
echo -e "defaults.ctl.card 2\ndefaults.pcm.card 2\ndefaults.timer.card 2" > /etc/asound.conf
```

### RealSense 内核驱动
```bash
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-key F6E65AC044F831AC80A06380C8B3A55A6F3EFCDE
sudo add-apt-repository "deb https://librealsense.intel.com/Debian/apt-repo $(lsb_release -cs) main" -u
sudo apt update && sudo apt install librealsense2-dkms
# 验证
modinfo uvcvideo | grep "version:"  # 应含 realsense 字样
```

### 切断 DMA 越界（5.15 内核 IOMMU 与 xHCI 冲突）
```bash
sudo nano /etc/default/grub
# 修改为：
# GRUB_CMDLINE_LINUX_DEFAULT="quiet splash pcie_aspm=off intel_iommu=off"
sudo update-grub
# 重启后验证
cat /proc/cmdline
```

## 后端部署

### 从机后端部署 (backend_fastapi)
```bash
# 1. 拉取仓库
git clone git@bitbucket.org:CyanineTech/backend_fastapi.git
cd backend_fastapi && git checkout development

# 2. 创建代码目录
python3 backend_fastapi/automatic_deployment_project/create_code_directory.py

# 3. 切换分支
cp backend_fastapi/automatic_deployment_project/YixuanUpdateCodes/configure_code_git .
# vim configure_code_git → 改目标分支为 development
bash configure_code_git

# 4. 验证分支
bash backend_fastapi/automatic_deployment_project/YixuanUpdateCodes/show-codes-version

# 5. 更新代码
bash backend_fastapi/automatic_deployment_project/YixuanUpdateCodes/upgrade_code

# 6. 一键部署（全新机器执行两遍）
cd backend_fastapi/automatic_deployment_project
python3 automatic_deployment.py
# 选 Y 重启
```

### 主机后端部署 (backend_fastapi_master)
流程同上，将 `backend_fastapi` 替换为 `backend_fastapi_master`。

> **注意**：部署前确保 MySQL Docker 容器已启动。全新机器需执行两遍 `automatic_deployment.py`。

## 摄像头标定

### 进入标定模式
```bash
rosservice call /gw_XXXXXXXXXXXX/cy_node_sv/run_calibration "{}"
```

### 执行标定
```bash
# CT-04
roslaunch calibration_ct_agv_04_2_infra.launch
rosservice call /calibration_front_depthcamera/pose_calibration  # 前
rosservice call /calibration_depthcamera/pose_calibration        # 后
rosservice call /calibration_fork_depthcamera/pose_calibration   # 叉尖
```

标定物坐标配置：`roscd camera_pose_calibration/param/ct_agv_04_2/`

## 摄像头（智慧眼）配置

### RTSP 子码流配置
- 视频编码: H264
- 分辨率: 640x360
- 帧率: 5fps（25fps 无意义增加解码负担）
- 图像质量: 中
- 码率上限: ~300kbps

### 常用型号
TP-LINK TL-IPC445EP-W2.8（推荐 PoE 版本，单网线供电+数据）

## WiFi 网络要求

| 指标 | 要求 |
|------|------|
| 频段 | 2.4GHz 全覆盖 |
| 信号强度 | ≥ -55dBm（推荐≥-50dBm） |
| 平均延迟 | ≤ 20ms |
| 平均丢包率 | ≤ 0.3% |
| 协商速率 | ≥ 100Mbps |
| 漫游切换耗时 | ≤ 80ms |
| 漫游切换丢包率 | ≤ 0.3% |

## 批量部署 (Clonezilla)

使用再生龙方式：
1. 准备母机 + U盘(≥已用空间, USB3.0)
2. U盘分区：8G FAT32(启动盘) + 剩余EXT4(镜像存储)
3. 母机备份 → U盘 EXT4 分区
4. 子机还原 ← U盘

## 新机配置流程

1. BIOS: 通电自动开机 (After Power Failure → Power On)
2. BIOS: 关闭 Secure Boot
3. 安装 Ubuntu Server (HWE kernel, OpenSSH)
4. LVM 逻辑卷设满
5. `sudo systemctl start first-boot.service`（仅一次，生成网络连接）
6. 连网更新：`sudo apt update && sudo apt install linux-generic-hwe-20.04`
7. 重启 → 执行 `first-boot.service`
8. 后端部署 → 重启

## 镜像制作 (CUBIC)

### 工具安装
```bash
sudo apt-add-repository universe
sudo apt-add-repository ppa:cubic-wizard/release
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys B7579F80E494ED3406A59DF9081525E2B4F1283B
sudo apt update && sudo apt install --no-install-recommends cubic
```

### 镜像制作流程（root 阶段）
1. 添加 ROS/Docker/Tailscale 软件源
2. 安装所有依赖包（见下方完整列表）
3. 配置网络：netplan → NetworkManager
4. 配置 CAN、声卡、udev 规则
5. 创建 robot 用户（sudo/docker/audio/lxd 组）
6. 创建 `/opt/cyanine-tech`、`/docker_data/docker` 目录
7. 配置 sudoers 免密：`nmcli, cat, systemctl, sed, iw, alsactl, cp`
8. 设置时区 `Asia/Shanghai`，禁用 cloud-init

### 镜像制作流程（robot 阶段）
1. 解压 `cyanine-tech_20.04.tar.gz` → `/opt/`
2. 解压 `dependent-src.tar.gz` → `/opt/cyanine-tech/`
3. 解压 `docker-images.tar.gz` → `/opt/cyanine-tech/`
4. 解压 `home_files.tar.gz` → `~/`
5. 安装 pip, supervisor, shyaml
6. 启用用户级服务：`cyanine-os.service`, `gnome-keyring.service`

### 镜像制作流程（root 后续）
1. 创建 systemd 服务符号链接
2. 禁用不需要的服务（hostapd, dnsmasq）
3. 使能开机服务

### 系统安装后（新设备首次启动）
```bash
# root 执行（仅一次）
sudo systemctl start first-boot.service      # 生成网络连接文件
sudo systemctl start update-robot-id.service  # 计算机器人ID（确保不重复）
sudo systemctl start docker-compose.service   # 可能失败，后面重试

# 使能开机启动
sudo systemctl enable docker-compose.service
sudo systemctl enable supervisor.service
sudo systemctl enable verify_ros_env_for_supervisor.service

# robot 执行
cd ~/backend_fastapi/automatic_deployment_project
python3 automatic_deployment.py  # 第一次会失败（准备docker配置）
sudo systemctl start docker-compose.service  # docker启动后重试
python3 automatic_deployment.py  # 第二次成功
```
重启设备即完成。

## 开发环境配置 (20.04)

### 目录结构
| 路径 | 用途 |
|------|------|
| `/opt/cyanine-tech/cyanine-os/` | ROS 安装目录 |
| `/opt/cyanine-tech/cartographer/` | Cartographer 建图 |
| `/opt/cyanine-tech/opencv-3.3.1/` | OpenCV（避免与系统4.2冲突） |
| `/opt/cyanine-tech/dependent-src/` | 编译依赖源码（编译后可删） |
| `/opt/cyanine-tech/system/` | 自定义开机服务配置 |
| `/home/robot/static/` | 机器人个性化配置 |

### 编译依赖
需编译安装的关键组件：
- **abseil-cpp** → `/usr/local/stow/absl`（commit 21510581）
- **cartographer** → `/opt/cyanine-tech/cartographer`
- **libwebsockets** → `/usr/local`（v4.3-stable）

### udev 规则
| 规则文件 | 设备 | VID:PID | 符号链接 |
|----------|------|---------|----------|
| ls01b_v2.rules | 雷达 | 10c4:ea60 | /dev/ls01b_v2 |
| mecanumbot.rules | STM32(CH341) | 1a86:7523 | /dev/mecanumbot |
| usb_2_modbus.rules | Modbus | 0403:6001 | /dev/usb_2_modbus |
| usb_2_modbus_bty.rules | 电池Modbus | 0403:6001(AD0JGDEE) | /dev/usb_2_modbus_bty |
| usb_2_modbus_ir.rules | 红外Modbus | 0403:6001(AD0JF848) | /dev/usb_2_modbus_ir |

### 环境变量 (CT_ROBOT_NAME)
机器人ID 由主板序列号生成（12位，不足补X，超长截断）：
```bash
ROBOT_ID=$(dmidecode -s baseboard-serial-number)
# 写入 ~/.bashrc: export CT_ROBOT_NAME=<ROBOT_ID>
```

### 开机启动配置
```bash
# 关闭桌面（防休眠）
sudo systemctl disable gdm3.service

# 添加用户级服务
sudo ln -s /opt/cyanine-tech/system/cyanine-os.service /etc/systemd/user
systemctl --user enable cyanine-os.service

# 使 robot 用户上电即挂载（开机启动自定义服务）
sudo loginctl enable-linger robot
```

### 网络连接创建脚本
```bash
# 热点
nmcli connection add con-name CTROS_Hotspot ifname ap0 autoconnect no type wifi mode ap \
  ssid CT-AP_${MAC_IP} -- 802-11-wireless.band bg \
  802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk 88888888 \
  ipv6.method ignore ipv4.method shared ipv4.addresses 10.42.0.1/24

# WiFi（默认办公网络）
nmcli connection add con-name WiFi ifname '*' autoconnect yes type wifi \
  ssid TP-LINK_5G_4A49 -- 802-11-wireless-security.key-mgmt wpa-psk \
  802-11-wireless-security.psk Lanyinkejiccs ipv6.method ignore \
  ipv4.method manual ipv4.addresses 192.168.1.2/24 ipv4.gateway 192.168.1.254

# 有线（工作环境）
nmcli connection add con-name router_wire ifname '*' autoconnect yes type ethernet \
  -- ipv6.method ignore ipv4.method manual \
  ipv4.addresses 192.168.1.3/24,10.10.10.100/24,10.10.11.100/24 \
  ipv4.gateway 192.168.1.1 ipv4.dns 192.168.1.1
```
