#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import subprocess
import socket
from datetime import datetime, timedelta
import glob
import tempfile

def parse_datetime_str(dt_str):
    """
    解析日期时间字符串，支持多种格式
    格式: YYYY_MM_DD-HH_MM_SS
    """
    dt_str = dt_str.strip()
    
    # 主要格式
    formats_to_try = [
        "%Y_%m_%d-%H_%M_%S",      # 2026_01_04-23_58_53
        "%Y-%m-%d-%H-%M-%S",       # 2026-01-04-23-58-53
        "%Y%m%d-%H%M%S",           # 20260104-235853
        "%Y-%m-%d %H:%M:%S",       # 2026-01-09 10:26:35
        "%Y/%m/%d %H:%M:%S",       # 2026/01/09 10:26:35
        "%Y.%m.%d %H:%M:%S",       # 2026.01.09 10:26:35
    ]
    
    for fmt in formats_to_try:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    
    # 尝试处理带下划线的格式
    if '_' in dt_str and '-' not in dt_str:
        # 尝试将下划线替换为连字符
        dt_str_modified = dt_str.replace('_', '-')
        try:
            return datetime.strptime(dt_str_modified, "%Y-%m-%d-%H-%M-%S")
        except ValueError:
            pass
    
    # 尝试更灵活的解析
    # 移除所有非数字字符，只保留数字
    digits = re.sub(r'[^\d]', '', dt_str)
    if len(digits) >= 14:  # YYYYMMDDHHMMSS
        try:
            # 格式化为标准格式
            dt_str_formatted = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
            return datetime.strptime(dt_str_formatted, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    elif len(digits) >= 12:  # YYYYMMDDHHMM
        try:
            dt_str_formatted = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}:00"
            return datetime.strptime(dt_str_formatted, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    
    raise ValueError(f"无法解析时间字符串: {dt_str}")

def parse_kernel_time(time_str, year):
    """
    解析内核日志时间格式: Jan 05 01:26:06.624738
    返回datetime对象
    """
    # 月份缩写映射
    month_map = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4,
        'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8,
        'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    
    # 解析格式: Jan 05 01:26:06.624738
    parts = time_str.split()
    if len(parts) < 3:
        raise ValueError(f"无效的内核时间格式: {time_str}")
    
    month_str = parts[0]
    day_str = parts[1]
    time_part = parts[2]
    
    # 获取月份
    month = month_map.get(month_str)
    if month is None:
        raise ValueError(f"无效的月份缩写: {month_str}")
    
    # 获取日
    day = int(day_str)
    
    # 解析时间部分: HH:MM:SS.microseconds
    time_parts = time_part.split('.')
    if len(time_parts) != 2:
        raise ValueError(f"无效的时间格式: {time_part}")
    
    hms = time_parts[0]
    microsecond = int(time_parts[1])
    
    # 解析时:分:秒
    hour, minute, second = map(int, hms.split(':'))
    
    return datetime(year, month, day, hour, minute, second, microsecond)

def find_closest_earlier_directory(dirs, input_timestamp, dir_timestamps):
    """
    查找输入时间之前最近的目录
    """
    closest_dir = None
    min_diff = float('inf')
    
    for dir_name in dirs:
        if dir_name in dir_timestamps:
            dir_timestamp = dir_timestamps[dir_name]
            
            # 只考虑输入时间之前的目录（目录时间 <= 输入时间）
            if dir_timestamp <= input_timestamp:
                diff = input_timestamp - dir_timestamp
                if diff < min_diff:
                    min_diff = diff
                    closest_dir = dir_name
    
    return closest_dir, min_diff

def extract_and_sort_log_from_launch_file(launch_file_path, output_file_path, start_timestamp, end_timestamp, input_time_str):
    """
    从launch文件中提取指定时间范围的日志，先转换时间戳，然后按时间排序
    """
    extracted_entries = []  # 存储(时间戳, 转换后的行内容)
    
    # 首先检查文件是否存在
    if not os.path.exists(launch_file_path):
        print(f"  文件不存在: {launch_file_path}")
        return 0
    
    # 尝试不同编码
    encodings_to_try = ['utf-8', 'gbk', 'latin-1', 'iso-8859-1']
    file_encoding = None
    
    for encoding in encodings_to_try:
        try:
            with open(launch_file_path, 'r', encoding=encoding, errors='ignore') as f:
                f.read(1024)  # 测试读取
            file_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    
    if not file_encoding:
        file_encoding = 'latin-1'
    
    # 提取日志
    try:
        with open(launch_file_path, 'r', encoding=file_encoding, errors='ignore') as infile:
            for line_num, line in enumerate(infile, 1):
                # 查找10位Unix时间戳
                matches = re.finditer(r'\b(\d{10})\b', line)
                
                for match in matches:
                    ts_str = match.group(1)
                    try:
                        timestamp = int(ts_str)
                        
                        # 检查时间戳是否在范围内
                        if start_timestamp <= timestamp <= end_timestamp:
                            # 将Unix时间戳转换为可读格式
                            try:
                                readable_time = datetime.fromtimestamp(timestamp).strftime("%Y_%m_%d-%H_%M_%S")
                                # 替换时间戳为可读格式
                                converted_line = line.replace(ts_str, readable_time, 1)
                                
                                # 存储条目（按时间戳排序）
                                extracted_entries.append((timestamp, converted_line))
                            except (ValueError, OSError):
                                # 如果转换失败，使用原始时间戳
                                extracted_entries.append((timestamp, line))
                            break  # 这一行已经匹配，不需要再检查其他时间戳
                    except ValueError:
                        continue
    
    except Exception as e:
        print(f"  处理文件时出错: {e}")
        return 0
    
    # 按时间戳排序
    extracted_entries.sort(key=lambda x: x[0])
    
    # 写入排序后的内容到文件
    try:
        with open(output_file_path, 'w', encoding='utf-8') as outfile:
            # 写入文件头
            outfile.write(f"# 提取日志 - 输入时间: {input_time_str}\n")
            outfile.write(f"# 搜索范围: {start_timestamp} - {end_timestamp}\n")
            outfile.write(f"# 源文件: {launch_file_path}\n")
            outfile.write(f"# 条目数: {len(extracted_entries)}\n")
            outfile.write(f"# 时间范围: {datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M:%S')} - {datetime.fromtimestamp(end_timestamp).strftime('%Y-%m-%d %H:%M:%S')}\n")
            outfile.write("#" * 80 + "\n\n")
            
            # 写入排序后的内容
            for timestamp, line in extracted_entries:
                outfile.write(line)
        
        return len(extracted_entries)
    
    except Exception as e:
        print(f"  写入文件时出错: {e}")
        return 0

def find_and_copy_bag_files(autobag_dir, input_dt, output_dir):
    """
    查找并复制bag文件和caution文件
    """
    copied_files = []
    
    # 计算bag文件时间范围：输入时间的前两分钟到输入时间
    bag_start_time = input_dt - timedelta(minutes=2)
    bag_end_time = input_dt
    
    # 计算caution文件时间范围：输入时间的前后一分钟
    caution_start_time = input_dt - timedelta(minutes=1)
    caution_end_time = input_dt + timedelta(minutes=1)
    
    print(f"搜索bag文件时间范围: {bag_start_time.strftime('%Y-%m-%d-%H-%M-%S')} 到 {bag_end_time.strftime('%Y-%m-%d-%H-%M-%S')}")
    print(f"搜索caution文件时间范围: {caution_start_time.strftime('%Y-%m-%d-%H-%M-%S')} 到 {caution_end_time.strftime('%Y-%m-%d-%H-%M-%S')}")
    
    # 查找所有.bag文件
    bag_files = glob.glob(os.path.join(autobag_dir, "*.bag"))
    bag_files.extend(glob.glob(os.path.join(autobag_dir, "*.bag.*")))  # 包含扩展名
    
    # 复制bag文件
    for bag_file in bag_files:
        filename = os.path.basename(bag_file)
        
        # 跳过caution开头的文件（稍后专门处理）
        if filename.startswith("caution_"):
            continue
            
        # 解析时间
        bag_time = None
        
        # 匹配格式: _2026-01-05-01-04-59_71.bag
        match = re.search(r'_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})_\d+\.bag', filename)
        if match:
            try:
                year, month, day, hour, minute, second = match.groups()
                bag_time = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second))
            except ValueError:
                continue
        
        # 如果找到时间且在范围内，复制文件
        if bag_time and bag_start_time <= bag_time <= bag_end_time:
            dest_path = os.path.join(output_dir, filename)
            try:
                shutil.copy2(bag_file, dest_path)
                copied_files.append((filename, bag_time, "bag"))
                print(f"  复制bag文件: {filename} (时间: {bag_time.strftime('%Y-%m-%d-%H-%M-%S')})")
            except Exception as e:
                print(f"  复制文件失败 {filename}: {e}")
    
    # 查找caution文件
    caution_patterns = [
        "caution_*",
    ]
    
    for pattern in caution_patterns:
        caution_files = glob.glob(os.path.join(autobag_dir, pattern))
        
        for caution_file in caution_files:
            filename = os.path.basename(caution_file)
            
            # 跳过非caution文件
            if not filename.startswith("caution_"):
                continue
                
            # 匹配格式: caution_TX_20260105_014010.bag.zip
            match = re.search(r'caution_[A-Za-z0-9]+_(\d{8})_(\d{6})\.', filename)
            if match:
                try:
                    date_str, time_str = match.groups()
                    year = int(date_str[0:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    hour = int(time_str[0:2])
                    minute = int(time_str[2:4])
                    second = int(time_str[4:6])
                    caution_time = datetime(year, month, day, hour, minute, second)
                    
                    # 检查时间是否在caution文件时间范围内
                    if caution_start_time <= caution_time <= caution_end_time:
                        dest_path = os.path.join(output_dir, filename)
                        try:
                            shutil.copy2(caution_file, dest_path)
                            copied_files.append((filename, caution_time, "caution"))
                            print(f"  复制caution文件: {filename} (时间: {caution_time.strftime('%Y-%m-%d-%H-%M-%S')})")
                        except Exception as e:
                            print(f"  复制文件失败 {filename}: {e}")
                except (ValueError, IndexError):
                    continue
    
    return copied_files

def get_journalctl_boot_option(input_dt):
    """
    根据~/log/permanent/目录中比输入时间晚的目录数量确定journalctl的-b选项
    """
    permanent_dir = os.path.expanduser("~/log/permanent")
    
    if not os.path.isdir(permanent_dir):
        print(f"永久日志目录不存在: {permanent_dir}")
        return 0  # 使用-b -0
    
    # 查找所有日期格式的目录
    dirs = []
    try:
        for item in os.listdir(permanent_dir):
            item_path = os.path.join(permanent_dir, item)
            if os.path.isdir(item_path):
                # 匹配日期格式的目录名
                if re.match(r'^\d{4}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}$', item.replace('.', '_')):
                    dirs.append(item)
    except FileNotFoundError:
        print(f"无法访问目录 {permanent_dir}")
        return 0
    
    if not dirs:
        print(f"在 {permanent_dir} 中未找到日期格式的目录")
        return 0
    
    # 解析目录时间并统计比输入时间晚的目录数量
    count_after = 0
    
    for dir_name in dirs:
        try:
            # 尝试解析目录名
            dir_dt = None
            
            # 尝试第一种格式: YYYY_MM_DD-HH_MM_SS
            try:
                dir_dt = datetime.strptime(dir_name, "%Y_%m_%d-%H_%M_%S")
            except ValueError:
                pass
            
            # 尝试第二种格式: YYYY-MM-DD-HH-MM-SS
            if not dir_dt:
                try:
                    dir_dt = datetime.strptime(dir_name, "%Y-%m-%d-%H-%M-%S")
                except ValueError:
                    pass
            
            # 尝试第三种格式: YYYYMMDD-HHMMSS
            if not dir_dt:
                try:
                    dir_dt = datetime.strptime(dir_name, "%Y%m%d-%H%M%S")
                except ValueError:
                    pass
            
            if dir_dt and dir_dt > input_dt:
                count_after += 1
                
        except Exception:
            continue
    
    print(f"在永久日志目录中找到 {count_after} 个比输入时间晚的目录")
    return count_after

def extract_journalctl_logs(input_dt, output_dir, input_time_str):
    """
    提取journalctl内核日志，根据boot选项和输入时间前后两分钟过滤
    """
    # 获取boot选项
    boot_option = get_journalctl_boot_option(input_dt)
    
    # 计算时间范围
    kernel_start_dt = input_dt - timedelta(minutes=2)
    kernel_end_dt = input_dt + timedelta(minutes=2)
    
    print(f"内核日志搜索时间范围: {kernel_start_dt.strftime('%Y-%m-%d %H:%M:%S')} 到 {kernel_end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 构建journalctl命令
    if boot_option > 0:
        journalctl_cmd = f"sudo journalctl -o short-precise -k -b -{boot_option}"
        print(f"使用journalctl命令: {journalctl_cmd}")
    else:
        journalctl_cmd = "sudo journalctl -o short-precise -k -b -0"
        print(f"使用journalctl命令: {journalctl_cmd}")
    
    # 提取journalctl日志，但输出文件名为dmesg开头
    journal_output_file = os.path.join(output_dir, f"dmesg_{input_time_str.replace(':', '').replace('-', '_')}.log")
    
    journal_matched = 0
    
    try:
        print("正在运行journalctl命令...")
        journal_result = subprocess.run(journalctl_cmd, shell=True, capture_output=True, text=True, timeout=30)
        
        if journal_result.returncode == 0:
            journal_lines = journal_result.stdout.split('\n')
            
            with open(journal_output_file, 'w', encoding='utf-8') as f:
                f.write(f"# 内核日志(journalctl) - 输入时间: {input_time_str}\n")
                f.write(f"# 搜索范围: {kernel_start_dt.strftime('%Y-%m-%d %H:%M:%S')} 到 {kernel_end_dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 使用命令: {journalctl_cmd}\n")
                f.write(f"# boot选项: -{boot_option}\n")
                f.write("#" * 80 + "\n\n")
                
                for line in journal_lines:
                    # 解析内核日志时间格式: Jan 05 01:26:06.624738 hostname kernel: [...]
                    # 匹配时间部分
                    time_match = re.match(r'^([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d+)', line)
                    if time_match:
                        time_str = time_match.group(1)
                        try:
                            # 解析时间，使用输入时间的年份
                            log_dt = parse_kernel_time(time_str, input_dt.year)
                            
                            # 检查是否在时间范围内
                            if kernel_start_dt <= log_dt <= kernel_end_dt:
                                f.write(line + "\n")
                                journal_matched += 1
                        except ValueError as e:
                            # 如果解析失败，跳过这一行
                            continue
                
            if journal_matched > 0:
                print(f"  成功提取 {journal_matched} 行journalctl日志")
                print(f"  保存到: {os.path.basename(journal_output_file)}")
            else:
                print("  未在时间范围内找到journalctl日志")
                # 保留文件，但标记为空
                with open(journal_output_file, 'a', encoding='utf-8') as f:
                    f.write("# 未找到时间范围内的日志\n")
        else:
            print(f"  journalctl命令失败: {journal_result.stderr}")
            with open(journal_output_file, 'w', encoding='utf-8') as f:
                f.write(f"# journalctl命令失败\n")
                f.write(f"# 错误信息: {journal_result.stderr}\n")
    
    except subprocess.TimeoutExpired:
        print("  journalctl命令超时")
        with open(journal_output_file, 'w', encoding='utf-8') as f:
            f.write("# journalctl命令执行超时\n")
    except Exception as e:
        print(f"  运行journalctl命令时出错: {e}")
        with open(journal_output_file, 'w', encoding='utf-8') as f:
            f.write(f"# 运行journalctl命令时出错: {e}\n")
    
    return journal_matched

def get_clean_time_str(input_time_str):
    """
    清理时间字符串，用于文件名
    移除所有特殊字符，只保留数字和下划线
    """
    # 替换常见的分隔符为下划线
    clean_str = input_time_str.replace(' ', '_').replace(':', '_').replace('-', '_').replace('.', '_').replace('/', '_')
    
    # 移除非字母数字下划线的字符
    clean_str = re.sub(r'[^\w]', '', clean_str)
    
    return clean_str

def find_matching_files(target_dir, keywords):
    """
    在目标目录中查找匹配关键词的文件
    支持模糊匹配，如'we'匹配'websocket_subscriber.launch'
    """
    matching_files = []
    
    if not os.path.exists(target_dir):
        return matching_files
    
    # 列出目标目录中的所有launch文件
    all_files = os.listdir(target_dir)
    launch_files = [f for f in all_files if f.endswith('.launch')]
    
    if not keywords:
        return []
    
    # 分割关键词（支持空格分隔多个关键词）
    keyword_list = [k.strip() for k in keywords.split()]
    
    for keyword in keyword_list:
        # 确保关键词是完整的文件名或部分文件名
        for launch_file in launch_files:
            # 检查是否精确匹配（带或不带.launch）
            if keyword == launch_file or keyword == launch_file[:-7]:
                if launch_file not in matching_files:
                    matching_files.append(launch_file)
            # 检查是否部分匹配（包含关键词）
            elif keyword.lower() in launch_file.lower():
                if launch_file not in matching_files:
                    matching_files.append(launch_file)
    
    return matching_files

def get_hostname():
    """
    获取主机名
    """
    try:
        return socket.gethostname()
    except:
        return "ubuntu-330"  # 默认主机名

def generate_scp_command(download_dir):
    """
    生成SCP下载命令
    """
    username = "robot"
    hostname = get_hostname()
    download_dir_name = os.path.basename(download_dir)
    
    # 获取用户的家目录
    home_dir = os.path.expanduser("~")
    relative_path = os.path.relpath(download_dir, home_dir)
    
    scp_command = f"scp -C -r {username}@{hostname}:~/{relative_path} ."
    return scp_command

def main():
    # 设置目录路径
    base_log_dir = os.path.expanduser("~/log/not_permanent")
    autobag_dir = os.path.expanduser("~/autobag")
    
    # 检查基础日志目录是否存在
    if not os.path.isdir(base_log_dir):
        print(f"错误：目录 {base_log_dir} 不存在！")
        print("请确认目录是否存在，或者使用完整路径")
        sys.exit(1)
    
    print(f"日志目录: {base_log_dir}")
    
    # 获取用户输入的时间
    print("支持的时间格式:")
    print("  1. 2026_01_04-23_58_53")
    print("  2. 2026-01-04-23-58-53")
    print("  3. 2026-01-09 10:26:35")
    print("  4. 2026/01/09 10:26:35")
    print("  5. 20260104-235853")
    input_time_str = input("请输入日期和时间: ").strip()
    
    try:
        # 解析输入时间
        input_dt = parse_datetime_str(input_time_str)
        
        # 转换为Unix时间戳
        input_timestamp = int(input_dt.timestamp())
        
        # 生成用于文件名的干净时间字符串
        clean_time_str = get_clean_time_str(input_time_str)
        
        print(f"输入时间: {input_time_str}")
        print(f"解析为: {input_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"对应时间戳: {input_timestamp}")
        print(f"文件名时间: {clean_time_str}")
        
        # 计算前后一分钟的时间戳（用于launch文件）
        start_timestamp = input_timestamp - 60
        end_timestamp = input_timestamp + 60
        
        start_dt = datetime.fromtimestamp(start_timestamp)
        end_dt = datetime.fromtimestamp(end_timestamp)
        
        print(f"launch文件搜索时间范围: {start_dt.strftime('%Y-%m-%d %H:%M:%S')} 到 {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"时间戳范围: {start_timestamp} - {end_timestamp}")
        
        # 查找所有日期格式的目录
        dirs = []
        try:
            for item in os.listdir(base_log_dir):
                item_path = os.path.join(base_log_dir, item)
                if os.path.isdir(item_path):
                    # 匹配日期格式的目录名
                    if re.match(r'^\d{4}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}$', item.replace('.', '_')):
                        dirs.append(item)
        except FileNotFoundError:
            print(f"错误：无法访问目录 {base_log_dir}")
            sys.exit(1)
        
        if not dirs:
            print(f"警告：在 {base_log_dir} 中未找到日期格式的目录")
            sys.exit(1)
        
        print(f"找到 {len(dirs)} 个可能的日志目录")
        
        # 解析所有目录的时间戳
        dir_timestamps = {}
        valid_dirs = []
        
        for dir_name in dirs:
            try:
                # 尝试解析目录名
                dir_dt = None
                
                # 尝试第一种格式: YYYY_MM_DD-HH_MM_SS
                try:
                    dir_dt = datetime.strptime(dir_name, "%Y_%m_%d-%H_%M_%S")
                except ValueError:
                    pass
                
                # 尝试第二种格式: YYYY-MM-DD-HH-MM-SS
                if not dir_dt:
                    try:
                        dir_dt = datetime.strptime(dir_name, "%Y-%m-%d-%H-%M-%S")
                    except ValueError:
                        pass
                
                # 尝试第三种格式: YYYYMMDD-HHMMSS
                if not dir_dt:
                    try:
                        dir_dt = datetime.strptime(dir_name, "%Y%m%d-%H%M%S")
                    except ValueError:
                        pass
                
                if dir_dt:
                    dir_timestamp = int(dir_dt.timestamp())
                    dir_timestamps[dir_name] = dir_timestamp
                    valid_dirs.append(dir_name)
            except Exception:
                continue
        
        if not valid_dirs:
            print("错误：无法解析任何目录的时间")
            sys.exit(1)
        
        print(f"成功解析 {len(valid_dirs)} 个目录的时间")
        
        # 查找输入时间之前最近的目录
        closest_dir, min_diff = find_closest_earlier_directory(valid_dirs, input_timestamp, dir_timestamps)
        
        if not closest_dir:
            # 如果没有找到之前的目录，找之后最近的目录
            print("警告：未找到输入时间之前的目录，将使用之后最近的目录")
            closest_dir = min(valid_dirs, key=lambda x: abs(dir_timestamps[x] - input_timestamp))
            min_diff = abs(dir_timestamps[closest_dir] - input_timestamp)
        
        closest_timestamp = dir_timestamps[closest_dir]
        closest_dt = datetime.fromtimestamp(closest_timestamp)
        
        print(f"\n找到最近目录: {closest_dir}")
        print(f"目录时间: {closest_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"时间差: {min_diff} 秒 ({min_diff/60:.1f} 分钟)")
        print(f"目录在输入时间之{'前' if closest_timestamp <= input_timestamp else '后'}")
        
        # 创建download目录
        download_dir_name = f"download_{clean_time_str}"
        download_dir = os.path.join(os.path.expanduser("~"), download_dir_name)
        
        if os.path.exists(download_dir):
            print(f"\n警告：目录 {download_dir} 已存在，将覆盖内容")
            try:
                shutil.rmtree(download_dir)
            except Exception as e:
                print(f"删除目录失败: {e}")
                sys.exit(1)
        
        os.makedirs(download_dir, exist_ok=True)
        print(f"创建输出目录: {download_dir}")
        
        # 目标目录
        target_dir = os.path.join(base_log_dir, closest_dir)
        
        # 获取用户输入的额外launch文件关键词
        print("\n请输入额外的launch日志文件名或关键词（多个用空格隔开，直接回车则跳过）：")
        print("示例:")
        print("  'we' - 匹配所有包含'we'的文件，如websocket_subscriber.launch")
        print("  'limited' - 匹配limited_zone.launch")
        print("  'navigation.launch' - 精确匹配navigation.launch")
        extra_files_input = input("额外文件或关键词: ").strip()
        
        # 定义基础要处理的launch文件列表
        base_launch_files = [
            {
                "filename": "mobile_base.launch",
                "description": "移动基础日志"
            },
            {
                "filename": "pure_laser_amcl.launch",
                "description": "纯激光AMCL日志"
            },
            {
                "filename": "lift_cargo.launch",
                "description": "提升货物日志"
            },
            {
                "filename": "state_monitor_wrapper.launch",
                "description": "状态监视器日志"
            }
        ]
        
        # 添加额外文件到处理列表
        launch_files = base_launch_files.copy()
        
        # 处理额外文件关键词
        if extra_files_input:
            print(f"搜索关键词: {extra_files_input}")
            matching_files = find_matching_files(target_dir, extra_files_input)
            
            if matching_files:
                print(f"找到匹配文件: {', '.join(matching_files)}")
                
                for extra_file in matching_files:
                    # 检查是否已经在基础列表中
                    already_in_list = any(launch_info["filename"] == extra_file for launch_info in launch_files)
                    
                    if not already_in_list:
                        launch_files.append({
                            "filename": extra_file,
                            "description": f"额外文件: {extra_file}"
                        })
            else:
                print("未找到匹配的文件")
        else:
            print("未添加额外文件，只处理默认的4个launch文件")
        
        # 处理每个launch文件
        print(f"\n开始处理 {len(launch_files)} 个launch文件:")
        all_extracted_lines = 0
        
        for launch_info in launch_files:
            launch_filename = launch_info["filename"]
            launch_desc = launch_info["description"]
            
            print(f"\n处理 {launch_desc} ({launch_filename}):")
            
            # 源文件路径
            launch_file_path = os.path.join(target_dir, launch_filename)
            
            # 输出文件路径 - 使用完整文件名+时间
            output_filename = f"{launch_filename}_{clean_time_str}.log"
            output_file_path = os.path.join(download_dir, output_filename)
            
            # 提取并排序日志
            extracted_lines = extract_and_sort_log_from_launch_file(
                launch_file_path, 
                output_file_path,
                start_timestamp,
                end_timestamp,
                input_time_str
            )
            
            if extracted_lines > 0:
                print(f"  成功提取并排序 {extracted_lines} 行日志")
                print(f"  保存到: {output_filename}")
                
                # 显示排序后的前几行
                try:
                    with open(output_file_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        # 跳过文件头，显示前5条数据行
                        data_lines = [line for line in lines if not line.startswith('#')]
                        if data_lines:
                            print(f"  前3条数据:")
                            for i, line in enumerate(data_lines[:3]):
                                print(f"    {line.strip()}")
                except Exception:
                    pass
                    
                all_extracted_lines += extracted_lines
            else:
                print(f"  警告：未找到匹配的日志")
        
        # 处理bag文件
        print("\n开始处理bag文件:")
        
        # 检查autobag目录是否存在
        if not os.path.isdir(autobag_dir):
            print(f"警告：autobag目录不存在: {autobag_dir}")
            print("跳过bag文件下载")
        else:
            print(f"搜索autobag目录: {autobag_dir}")
            copied_files = find_and_copy_bag_files(autobag_dir, input_dt, download_dir)
            
            if copied_files:
                print(f"\n成功复制 {len(copied_files)} 个文件:")
                # 按时间排序显示
                copied_files.sort(key=lambda x: x[1])
                for filename, file_time, file_type in copied_files:
                    print(f"  {file_type}: {filename} (时间: {file_time.strftime('%Y-%m-%d-%H-%M-%S')})")
            else:
                print("未找到符合条件的bag/caution文件")
        
        # 处理内核日志（只保留journalctl，但输出文件名为dmesg开头）
        print("\n开始处理内核日志:")
        journal_matched = extract_journalctl_logs(input_dt, download_dir, input_time_str)
        
        # 生成SCP下载命令
        scp_command = generate_scp_command(download_dir)
        
        # 显示处理摘要
        print("\n" + "="*70)
        print("处理完成摘要")
        print("="*70)
        print(f"输入时间: {input_time_str}")
        print(f"解析时间: {input_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"输入时间戳: {input_timestamp}")
        print(f"launch文件搜索范围: {start_timestamp} - {end_timestamp}")
        print(f"找到目录: {closest_dir}")
        print(f"目录时间: {closest_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"时间差: {min_diff} 秒 ({'前' if closest_timestamp <= input_timestamp else '后'})")
        print(f"输出目录: {download_dir}")
        print(f"处理文件数: {len(launch_files)}")
        print(f"launch文件提取行数: {all_extracted_lines}")
        print(f"dmesg日志行数: {journal_matched}")
        
        # 列出输出目录内容
        print(f"\n输出目录内容:")
        try:
            files = os.listdir(download_dir)
            total_size = 0
            for file in sorted(files):
                file_path = os.path.join(download_dir, file)
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    total_size += size
                    file_size = f"{size:,} 字节"
                    if size > 1024*1024:
                        file_size = f"{size/(1024*1024):.2f} MB"
                    elif size > 1024:
                        file_size = f"{size/1024:.2f} KB"
                    print(f"  {file} ({file_size})")
            
            # 显示总大小
            total_size_str = f"{total_size:,} 字节"
            if total_size > 1024*1024:
                total_size_str = f"{total_size/(1024*1024):.2f} MB"
            elif total_size > 1024:
                total_size_str = f"{total_size/1024:.2f} KB"
            print(f"\n总大小: {total_size_str}")
        except Exception as e:
            print(f"  无法列出目录内容: {e}")
        
        # 显示SCP下载命令
        print("\n" + "="*70)
        print("一键下载命令")
        print("="*70)
        print("将以下命令复制到您的电脑上执行，即可下载所有日志文件：")
        print("\n" + "="*70)
        print(f"{scp_command}")
        print("="*70)
        print("\n命令说明:")
        print(f"  scp      - 安全复制命令")
        print(f"  -C       - 启用压缩，加快传输速度")
        print(f"  -r       - 递归复制整个目录")
        print(f"  robot    - 远程机器用户名")
        print(f"  {get_hostname()} - 远程机器主机名")
        print(f"  ~/{os.path.basename(download_dir)} - 远程机器上的目录")
        print(f"  .        - 下载到当前目录")
        print("\n使用方法:")
        print("  1. 在您的电脑上打开终端")
        print("  2. 进入您想要保存文件的目录")
        print("  3. 粘贴并执行上面的scp命令")
        print("  4. 输入密码（如果需要）")
        print("="*70)
        
    except ValueError as e:
        print(f"错误：时间转换失败 - {e}")
        print("请确保时间格式正确")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"错误：处理过程中发生错误 - {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()