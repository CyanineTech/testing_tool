import requests
import time
import random
import argparse
import sys
import json
import os
import re
from typing import List, Optional, Tuple, Any, Dict, Union
import logging
from logging.handlers import RotatingFileHandler
from configparser import ConfigParser
from urllib.parse import urlparse
from dataclasses import dataclass, asdict
from datetime import datetime

# ====================== 常量集中管理（便于维护）======================
# 路径配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "config.ini")
TOKEN_FILE = DEFAULT_CONFIG  # 兼容原有逻辑，实际优先读取config.ini[base]token
ENDPOINT_PATH = "/dispatch_server/dispatch/start/location_call/task/"
LOG_FILE = os.path.join(SCRIPT_DIR, f"{os.path.splitext(os.path.basename(__file__))[0]}.log")

# 运行配置
MAX_CONSECUTIVE_FAIL = 5  # 最大连续失败次数
VALID_HTTP_METHODS = ["PUT"]  # 支持的HTTP方法
PORT_RANGE = (1, 65535)  # 合法端口范围
TARGET_ERROR_ID = 50421021  # 目标成功error_id（仅当等于该值时视为业务成功）

# 日志配置（简化格式，提升可读性）
CONSOLE_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"  # 控制台格式（简洁）
FILE_LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s"  # 文件日志格式（保留详细信息）
LOG_LEVEL_DEFAULT = logging.INFO
LOG_LEVEL_DEBUG = logging.DEBUG
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"  # 统一时间格式

# 配置文件默认值（[request]节）
DEFAULT_REQUEST_TIMEOUT = 15.0  # 默认超时时间（秒）
DEFAULT_REQUEST_RETRY = 0  # 默认重试次数
DEFAULT_REQUEST_RETRY_DELAY = 1.0  # 默认重试延迟（秒）

# 输出样式常量
SEPARATOR = "=" * 80  # 分隔线
SUB_SEPARATOR = "-" * 80  # 子分隔线

# ====================== 数据结构定义（统计结果）======================
@dataclass
class TaskStats:
    """任务统计结果数据类（简化，仅用于内存统计）"""
    start_time: str  # 启动时间（ISO格式）
    end_time: str  # 结束时间（ISO格式）
    total_tasks_target: Union[int, str]  # 目标任务数（总任务数模式）/ 运行模式（小时模式）
    total_success: int = 0  # 业务成功次数（error_id匹配）
    total_failure: int = 0  # 总失败次数（HTTP失败+业务失败）
    total_http_success: int = 0  # HTTP成功但业务失败的次数
    consecutive_fail_final: int = 0  # 最终连续失败次数
    area_usage: Dict[str, int] = None  # 区域使用统计
    total_duration: float = 0.0  # 总耗时（秒）
    per_hour_stats: List[Dict[str, Any]] = None  # 每小时统计（仅小时模式）

    def __post_init__(self):
        if self.area_usage is None:
            self.area_usage = {}
        if self.per_hour_stats is None:
            self.per_hour_stats = []

    def calculate_success_rate(self) -> float:
        """计算任务成功率（基于业务成功）"""
        total = self.total_success + self.total_failure
        return self.total_success / total if total > 0 else 0.0

# ====================== 日志配置（优化输出）======================
def setup_logger(debug: bool = False) -> logging.Logger:
    """初始化日志系统（优化控制台和文件输出格式）"""
    logger = logging.getLogger("lift_cargo_to_zone")
    logger.setLevel(LOG_LEVEL_DEBUG if debug else LOG_LEVEL_DEFAULT)
    logger.propagate = False

    # 清除已有处理器（避免重复输出）
    logger.handlers.clear()

    # 文件处理器（保留详细日志，用于问题排查）
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(file_handler)

    # 控制台处理器（简化格式，便于实时查看）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(CONSOLE_LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.addHandler(console_handler)

    return logger

# ====================== 配置加载与验证（强化必填校验）======================
def load_token_from_config(config: ConfigParser, logger: logging.Logger) -> str:
    """从config.ini[base]读取token（必填，缺失报错）"""
    if not config.has_section("base"):
        logger.error("❌ 配置文件缺失必填section：[base]")
        logger.error("  请在config.ini中添加[base]节，并配置token参数，示例：")
        logger.error("  [base]")
        logger.error("  token = 你的接口访问令牌")
        sys.exit(1)
    
    if not config.has_option("base", "token"):
        logger.error("❌ 配置文件[base]节缺失必填参数：token")
        logger.error("  请在[base]节中补充token配置，示例：")
        logger.error("  [base]")
        logger.error("  token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        sys.exit(1)
    
    token = config.get("base", "token").strip()
    if not token:
        logger.error("❌ 配置文件[base]节的token为空")
        logger.error("  请填写有效的接口访问令牌，示例：")
        logger.error("  [base]")
        logger.error("  token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        sys.exit(1)
    
    return token

def load_token(path: str, logger: logging.Logger) -> str:
    """加载Token（优先从config.ini[base]读取，必填校验）"""
    try:
        if not os.path.exists(path):
            logger.error(f"❌ 配置文件不存在：{path}")
            logger.error("  请在程序同目录下创建config.ini文件，并配置必填参数")
            sys.exit(1)
        
        config = ConfigParser()
        config.optionxform = str
        if not config.read(path, encoding="utf-8"):
            logger.error(f"❌ 配置文件读取失败：{path}")
            logger.error("  请检查文件是否损坏，或编码格式是否为UTF-8")
            sys.exit(1)
        
        # 优先从[base]节读取token（必填）
        return load_token_from_config(config, logger)
    
    except Exception as e:
        logger.error(f"❌ 读取Token失败：{str(e)}")
        sys.exit(1)

def validate_host(host: str, logger: logging.Logger) -> bool:
    """验证主机名/IP格式（允许合法主机名，包含字母、数字、连字符、下划线）"""
    if not host:
        return False
    
    # 合法规则：
    # 1. IPv4地址：xxx.xxx.xxx.xxx（每个段0-255）
    # 2. 主机名/域名：包含字母、数字、连字符(-)、下划线(_)，长度1-63字符，不能以连字符开头/结尾
    ipv4_pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    hostname_pattern = r"^[a-zA-Z0-9_][a-zA-Z0-9_-]{0,61}[a-zA-Z0-9_]$"
    
    # 先验证IPv4
    if re.match(ipv4_pattern, host):
        parts = list(map(int, host.split(".")))
        return all(0 <= part <= 255 for part in parts)
    # 再验证合法主机名
    elif re.match(hostname_pattern, host):
        return True
    # 最后验证域名（带后缀）
    elif re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", host):
        return True
    else:
        logger.warning(f"⚠️  主机格式可能不合法: {host}（支持IPv4、合法主机名或域名）")
        return True  # 不强制拦截，仅警告

def validate_port(port: int, logger: logging.Logger) -> bool:
    """验证端口合法性"""
    if PORT_RANGE[0] <= port <= PORT_RANGE[1]:
        return True
    logger.error(f"❌ 端口不合法: {port}（必须在{PORT_RANGE[0]}-{PORT_RANGE[1]}之间）")
    return False

def load_ini_config(path: str, logger: logging.Logger) -> dict:
    """加载并验证INI配置（强化必填项校验：[base]token、[service]host/port、[task]locations、[areas]areas）"""
    # 先检查配置文件是否存在
    if not os.path.exists(path):
        logger.error(f"❌ 配置文件不存在：{path}")
        logger.error("  请在程序同目录下创建config.ini文件，包含以下必填section：")
        logger.error("  [base]、[service]、[task]、[areas]")
        sys.exit(1)
    
    # 自定义ConfigParser：忽略重复选项（取最后一个）
    class IgnoreDuplicateConfigParser(ConfigParser):
        def __setitem__(self, key, value):
            if key in self._sections:
                self._sections[key].update(value)
            else:
                self._sections[key] = value
    
    config = IgnoreDuplicateConfigParser()
    config.optionxform = str  # 保留大小写
    try:
        if not config.read(path, encoding="utf-8"):
            logger.error(f"❌ 配置文件读取失败：{path}")
            logger.error("  请检查文件是否损坏，或编码格式是否为UTF-8")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 解析配置文件失败: {e}")
        sys.exit(1)
    
    res = {}
    # 1. 校验[service]节（必填：host、port）
    if not config.has_section("service"):
        logger.error("❌ 配置文件缺失必填section：[service]")
        logger.error("  请在config.ini中添加[service]节，并配置host和port参数，示例：")
        logger.error("  [service]")
        logger.error("  host = 服务主机名或IP（如：ubuntu-170）")
        logger.error("  port = 服务端口（如：9991）")
        sys.exit(1)
    
    # 主机校验（必填）
    if not config.has_option("service", "host"):
        logger.error("❌ 配置文件[service]节缺失必填参数：host")
        logger.error("  请在[service]节中补充host配置，示例：")
        logger.error("  [service]")
        logger.error("  host = ubuntu-170 或 10.51.140.12")
        sys.exit(1)
    host = config.get("service", "host").strip()
    if not host:
        logger.error("❌ 配置文件[service]节的host为空")
        logger.error("  请填写有效的服务主机名、IP或域名")
        sys.exit(1)
    if validate_host(host, logger):
        res["host"] = host
    else:
        logger.error("❌ 配置文件[service]节的host格式不合法")
        sys.exit(1)
    
    # 端口校验（必填）
    if not config.has_option("service", "port"):
        logger.error("❌ 配置文件[service]节缺失必填参数：port")
        logger.error("  请在[service]节中补充port配置，示例：")
        logger.error("  [service]")
        logger.error("  port = 9991")
        sys.exit(1)
    try:
        port = config.getint("service", "port")
        if validate_port(port, logger):
            res["port"] = port
        else:
            sys.exit(1)
    except ValueError:
        logger.error("❌ 配置文件[service]节的port必须是整数")
        logger.error("  请填写1-65535之间的有效端口号")
        sys.exit(1)
    
    # 2. 校验[task]节（必填：locations）
    if not config.has_section("task"):
        logger.error("❌ 配置文件缺失必填section：[task]")
        logger.error("  请在config.ini中添加[task]节，并配置locations参数，示例：")
        logger.error("  [task]")
        logger.error("  locations = LOC001, LOC002, LOC003（多个用逗号/空格分隔）")
        sys.exit(1)
    
    if not config.has_option("task", "locations"):
        logger.error("❌ 配置文件[task]节缺失必填参数：locations")
        logger.error("  请在[task]节中补充取货库位配置，示例：")
        logger.error("  [task]")
        logger.error("  locations = LOC001, LOC002, LOC003")
        sys.exit(1)
    loc_str = config.get("task", "locations").strip()
    if not loc_str:
        logger.error("❌ 配置文件[task]节的locations为空")
        logger.error("  请填写至少一个有效取货库位ID，多个用逗号或空格分隔")
        sys.exit(1)
    locations = re.split(r'[,\s]+', loc_str)
    locations = list(set([x.strip() for x in locations if x.strip()]))
    if not locations:
        logger.error("❌ 配置文件[task]节的locations解析后为空")
        logger.error("  请检查库位配置格式，示例：")
        logger.error("  locations = LOC001, LOC002, LOC003 或 locations = LOC001 LOC002 LOC003")
        sys.exit(1)
    res["locations"] = locations
    
    # 3. 校验[areas]节（必填：areas）
    if not config.has_section("areas"):
        logger.error("❌ 配置文件缺失必填section：[areas]")
        logger.error("  请在config.ini中添加[areas]节，并配置areas参数，示例：")
        logger.error("  [areas]")
        logger.error("  areas = AREA_A, AREA_B, AREA_C（多个用逗号/空格分隔）")
        sys.exit(1)
    
    if not config.has_option("areas", "areas"):
        logger.error("❌ 配置文件[areas]节缺失必填参数：areas")
        logger.error("  请在[areas]节中补充放货区域配置，示例：")
        logger.error("  [areas]")
        logger.error("  areas = AREA_A, AREA_B, AREA_C")
        sys.exit(1)
    area_str = config.get("areas", "areas").strip()
    if not area_str:
        logger.error("❌ 配置文件[areas]节的areas为空")
        logger.error("  请填写至少一个有效放货区域，多个用逗号或空格分隔")
        sys.exit(1)
    areas = re.split(r'[,\s]+', area_str)
    areas = list(set([x.strip() for x in areas if x.strip()]))
    if not areas:
        logger.error("❌ 配置文件[areas]节的areas解析后为空")
        logger.error("  请检查区域配置格式，示例：")
        logger.error("  areas = AREA_A, AREA_B, AREA_C 或 areas = AREA_A AREA_B AREA_C")
        sys.exit(1)
    res["areas"] = areas
    
    # 4. 读取[request]节（可选，带默认值）
    res["request"] = {
        "timeout": DEFAULT_REQUEST_TIMEOUT,
        "retry_count": DEFAULT_REQUEST_RETRY,
        "retry_delay": DEFAULT_REQUEST_RETRY_DELAY
    }
    if config.has_section("request"):
        # 超时时间（float，>0）
        if config.has_option("request", "timeout"):
            try:
                timeout = config.getfloat("request", "timeout")
                if timeout > 0:
                    res["request"]["timeout"] = timeout
                else:
                    logger.warning(f"⚠️  配置文件[request]节的timeout必须>0，使用默认值 {DEFAULT_REQUEST_TIMEOUT}")
            except ValueError:
                logger.warning(f"⚠️  配置文件[request]节的timeout必须是数字，使用默认值 {DEFAULT_REQUEST_TIMEOUT}")
        
        # 重试次数（int，≥0）
        if config.has_option("request", "retry_count"):
            try:
                retry_count = config.getint("request", "retry_count")
                if retry_count >= 0:
                    res["request"]["retry_count"] = retry_count
                else:
                    logger.warning(f"⚠️  配置文件[request]节的retry_count必须≥0，使用默认值 {DEFAULT_REQUEST_RETRY}")
            except ValueError:
                logger.warning(f"⚠️  配置文件[request]节的retry_count必须是整数，使用默认值 {DEFAULT_REQUEST_RETRY}")
        
        # 重试延迟（float，≥0）
        if config.has_option("request", "retry_delay"):
            try:
                retry_delay = config.getfloat("request", "retry_delay")
                if retry_delay >= 0:
                    res["request"]["retry_delay"] = retry_delay
                else:
                    logger.warning(f"⚠️  配置文件[request]节的retry_delay必须≥0，使用默认值 {DEFAULT_REQUEST_RETRY_DELAY}")
            except ValueError:
                logger.warning(f"⚠️  配置文件[request]节的retry_delay必须是数字，使用默认值 {DEFAULT_REQUEST_RETRY_DELAY}")
    
    # 输出配置读取成功日志
    logger.info(f"✅ 配置文件读取成功：{path}")
    logger.info(f"  - 服务地址：{res['host']}:{res['port']}")
    logger.info(f"  - 取货库位：{len(res['locations'])}个（{', '.join(res['locations'])}）")
    logger.info(f"  - 放货区域：{len(res['areas'])}个（{', '.join(res['areas'])}）")
    logger.info(f"  - 请求超时：{res['request']['timeout']}秒")
    logger.info(f"  - 重试次数：{res['request']['retry_count']}次")
    logger.info(f"  - 重试延迟：{res['request']['retry_delay']}秒")
    return res

# ====================== 区域选择器 ======================
class RandomAreaSelector:
    """随机区域选择器：确保所有区域均匀覆盖，同时保持随机性"""
    def __init__(self, areas: List[str]):
        self.areas = areas.copy()
        if not self.areas:
            raise ValueError("放货区域列表为空")
        self.use_count: Dict[str, int] = {area: 0 for area in self.areas}
    
    def select(self) -> str:
        """加权随机选择区域：优先选择使用次数较少的区域"""
        min_count = min(self.use_count.values())
        candidates = [area for area, count in self.use_count.items() if count == min_count]
        selected = random.choice(candidates)
        self.use_count[selected] += 1
        return selected
    
    def reset(self):
        """重置使用次数（每小时重置一次）"""
        self.use_count = {area: 0 for area in self.areas}
    
    def get_usage(self) -> Dict[str, int]:
        """获取区域使用统计"""
        return self.use_count.copy()

# ====================== 响应解析工具 ======================
def extract_msg_info(data: Any) -> Optional[Any]:
    """智能提取响应中的关键信息"""
    def is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and value.strip().lower() in ("", "info", "null", "error", "ok", "success"):
            return True
        if isinstance(value, (dict, list)) and not value:
            return True
        return False

    if not isinstance(data, dict):
        return None

    extract_paths = [
        ["data", "msg", "detail", "info"],
        ["data", "msg", "info"],
        ["msg", "detail", "info"],
        ["msg", "info"],
        ["info"],
        ["data", "detail"],
        ["detail"]
    ]

    for path in extract_paths:
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                break
            current = current[key]
        else:
            if not is_empty(current):
                return current

    msg = data.get("msg") or data.get("data", {}).get("msg")
    if isinstance(msg, dict):
        return msg.get("detail") or msg

    return None

def extract_error_info(data: Any) -> Tuple[Optional[int], Optional[str]]:
    """提取响应中的error_id和info信息（适配返回结构）"""
    error_id = None
    info = "未获取到具体错误信息"  # 默认错误提示
    
    if isinstance(data, dict):
        # 按用户提供的结构提取：msg -> detail -> error_id/info
        msg = data.get("msg", {})
        detail = msg.get("detail", {})
        
        if isinstance(detail, dict):
            # 提取error_id（确保是整数）
            error_id_val = detail.get("error_id")
            if isinstance(error_id_val, (int, str)):
                try:
                    error_id = int(error_id_val)
                except (ValueError, TypeError):
                    pass
            
            # 提取info（优先用detail中的info）
            info_val = detail.get("info")
            if isinstance(info_val, str) and info_val.strip():
                info = info_val.strip()
        
        # 兼容其他可能的结构（如果msg是字符串）
        if isinstance(msg, str) and msg.strip():
            info = msg.strip()
        
        # 兼容顶层error_id/info
        if error_id is None:
            error_id_val = data.get("error_id")
            if isinstance(error_id_val, (int, str)):
                try:
                    error_id = int(error_id_val)
                except (ValueError, TypeError):
                    pass
        if info == "未获取到具体错误信息":
            info_val = data.get("info")
            if isinstance(info_val, str) and info_val.strip():
                info = info_val.strip()
    
    return error_id, info

# ====================== 任务发送（带业务校验）======================
def send_task_with_retry(
    session: requests.Session,
    base_url: str,
    token: str,
    location_id: str,
    area: str,
    logger: logging.Logger,
    timeout: int = DEFAULT_REQUEST_TIMEOUT,
    retry_count: int = DEFAULT_REQUEST_RETRY,
    retry_delay: float = DEFAULT_REQUEST_RETRY_DELAY,
    debug: bool = False
) -> Tuple[bool, Any, Optional[Any], Optional[Any], Optional[int], Optional[str]]:
    """发送单个任务（支持重试+业务校验：仅error_id=50421021视为成功）"""
    url = f"{base_url}{ENDPOINT_PATH}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {"location_id": location_id, "area": area}

    for attempt in range(retry_count + 1):
        try:
            if debug:
                logger.debug(f"📤 发送任务（尝试{attempt+1}/{retry_count+1}）：库位={location_id} → 区域={area}，请求体：{json.dumps(payload, ensure_ascii=False)}")
            else:
                logger.info(f"📤 发送任务（尝试{attempt+1}/{retry_count+1}）：库位={location_id} → 区域={area}")
            
            resp = session.put(url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()

            # 解析响应数据
            data = resp.json() if resp.text.strip() else {}
            info = extract_msg_info(data)
            error_id, business_info = extract_error_info(data)

            # 业务校验：仅当error_id == TARGET_ERROR_ID时视为成功
            if error_id == TARGET_ERROR_ID:
                logger.info(f"✅ 任务业务成功：库位={location_id} → 区域={area}，error_id={error_id}，信息：{business_info}")
                if debug:
                    logger.debug(f"📋 成功响应详情：状态码={resp.status_code}，响应数据：{json.dumps(data, ensure_ascii=False)[:500]}")
                return True, resp, info, data, error_id, business_info
            else:
                # HTTP成功但业务失败（error_id不匹配）
                err_msg = f"error_id={error_id}（目标：{TARGET_ERROR_ID}），信息：{business_info}"
                if debug:
                    logger.debug(f"❌ 任务业务失败（尝试{attempt+1}）：{err_msg}，响应数据：{json.dumps(data, ensure_ascii=False)[:500]}")
                logger.warning(f"⚠️  任务业务失败（尝试{attempt+1}）：库位={location_id} → 区域={area}，{err_msg}")

                # 重试逻辑（如果还有重试次数）
                if attempt < retry_count:
                    logger.info(f"⏳ 将于{retry_delay:.1f}秒后重试该任务")
                    time.sleep(retry_delay)
                    continue
                # 重试耗尽，返回失败
                return False, resp, info, data, error_id, business_info

        except Exception as e:
            # HTTP请求失败（超时、4xx、5xx等）
            resp = getattr(e, "response", None)
            data = None
            if resp:
                try:
                    data = resp.json() if resp.text.strip() else {"status_code": resp.status_code, "text": resp.text[:500]}
                except Exception:
                    data = {"status_code": resp.status_code, "text": resp.text[:500]}
            
            info = extract_msg_info(data) if data else None
            error_id, business_info = extract_error_info(data) if data else (None, str(e)[:100])
            err_msg = str(e)[:100]

            # 最后一次尝试失败，返回失败
            if attempt == retry_count:
                if debug:
                    debug_msg = f"❌ 任务完全失败：错误={err_msg}，error_id={error_id}，信息={business_info}，响应：{json.dumps(data, ensure_ascii=False) if data else '无'}"
                    logger.debug(debug_msg)
                logger.error(f"❌ 任务失败（尝试{attempt+1}次）：库位={location_id} → 区域={area}，错误：{err_msg}，信息：{business_info}")
                return False, e, info, data, error_id, business_info
            
            # 重试前等待
            logger.warning(f"⚠️  任务尝试{attempt+1}失败：库位={location_id} → 区域={area}，错误：{err_msg}，信息：{business_info}")
            logger.info(f"⏳ 将于{retry_delay:.1f}秒后重试")
            time.sleep(retry_delay)

# ====================== 主函数 ======================
def main():
    print(SEPARATOR)
    print(f"📅 程序启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEPARATOR)

    # 读取config.ini获取默认请求参数（用于命令行参数默认值）
    ini_request_config = {
        "timeout": DEFAULT_REQUEST_TIMEOUT,
        "retry_count": DEFAULT_REQUEST_RETRY,
        "retry_delay": DEFAULT_REQUEST_RETRY_DELAY
    }
    if os.path.exists(DEFAULT_CONFIG):
        temp_config = ConfigParser()
        temp_config.optionxform = str
        try:
            if temp_config.read(DEFAULT_CONFIG, encoding="utf-8"):
                if temp_config.has_section("request"):
                    # 超时时间
                    if temp_config.has_option("request", "timeout"):
                        try:
                            timeout = temp_config.getfloat("request", "timeout")
                            if timeout > 0:
                                ini_request_config["timeout"] = timeout
                        except ValueError:
                            pass
                    # 重试次数
                    if temp_config.has_option("request", "retry_count"):
                        try:
                            retry_count = temp_config.getint("request", "retry_count")
                            if retry_count >= 0:
                                ini_request_config["retry_count"] = retry_count
                        except ValueError:
                            pass
                    # 重试延迟
                    if temp_config.has_option("request", "retry_delay"):
                        try:
                            retry_delay = temp_config.getfloat("request", "retry_delay")
                            if retry_delay >= 0:
                                ini_request_config["retry_delay"] = retry_delay
                        except ValueError:
                            pass
        except Exception as e:
            print(f"⚠️  警告：读取配置文件默认值失败，使用硬编码默认值：{e}", file=sys.stderr)

    # 命令行参数解析（默认优先使用config.ini，命令行参数可覆盖）
    parser = argparse.ArgumentParser(
        description=f"向dispatch接口发布任务（默认读取config.ini必填配置，业务成功条件：error_id={TARGET_ERROR_ID}）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
📋 核心说明：
  1. 程序默认读取config.ini配置，以下为必填项（缺失将直接报错）：
     - [base]token：接口访问令牌
     - [service]host/port：服务地址和端口
     - [task]locations：取货库位列表（多个用逗号/空格分隔）
     - [areas]areas：放货区域列表（多个用逗号/空格分隔）
  2. 命令行参数优先级高于config.ini，可临时覆盖配置
  3. 仅当接口返回 error_id={TARGET_ERROR_ID} 时视为业务成功
  4. 连续{MAX_CONSECUTIVE_FAIL}次失败后自动停止程序

🚀 使用示例：
  1. 基础使用（完全读取config.ini配置，推荐）
    python3 %(prog)s
    
  2. 指定总调用次数（覆盖小时模式）
    python3 %(prog)s --total-tasks 1000
    
  3. 自定义运行时长和重试次数
    python3 %(prog)s --hours 2.5 --retry 2
    
  4. 临时修改服务地址+调试模式
    python3 %(prog)s --host 10.51.140.12 --port 443 --debug
        """
    )
    # 基础配置参数（命令行可选，默认读config.ini）
    parser.add_argument("--protocol", choices=["http", "https"], default="http", help="协议类型（默认：http）")
    parser.add_argument("--host", help=f"服务主机名/IP（优先级高于config.ini[service]host）")
    parser.add_argument("--port", type=int, help=f"服务端口（优先级高于config.ini[service]port）")
    parser.add_argument("--token-file", default=TOKEN_FILE, help=f"配置文件路径（默认：{DEFAULT_CONFIG}，优先读取该文件[base]token）")
    parser.add_argument("--locations", nargs="+", default=None, help=f"取货库位ID列表（优先级高于config.ini[task]locations）")
    parser.add_argument("--areas", nargs="+", default=None, help=f"放货区域列表（优先级高于config.ini[areas]areas）")
    
    # 核心参数
    parser.add_argument("--total-tasks", type=int, default=None, help="总调用任务次数（优先级最高，需≥1，覆盖小时模式）")
    parser.add_argument("--tasks-per-location", type=int, default=40, help="每个库位每小时任务数（默认：40，需≥1）")
    parser.add_argument("--once", action="store_true", help="只运行1小时后退出（与--hours互斥）")
    parser.add_argument("--hours", type=float, default=None, help="运行时长（小时，需>0，优先级高于--once）")
    
    # 扩展参数（默认值从config.ini[request]读取）
    parser.add_argument("--debug", action="store_true", help="开启调试模式（输出详细日志）")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"配置文件路径（默认：{DEFAULT_CONFIG}）")
    parser.add_argument("--retry", type=int, default=ini_request_config["retry_count"], 
                        help=f"任务失败重试次数（默认：从config.ini[request]读取，当前为{ini_request_config['retry_count']}，需≥0）")
    parser.add_argument("--timeout", type=float, default=ini_request_config["timeout"],
                        help=f"请求超时时间（秒，默认：从config.ini[request]读取，当前为{ini_request_config['timeout']}，需>0）")
    parser.add_argument("--retry-delay", type=float, default=ini_request_config["retry_delay"],
                        help=f"重试延迟时间（秒，默认：从config.ini[request]读取，当前为{ini_request_config['retry_delay']}，需≥0）")

    args = parser.parse_args()

    # 初始化日志
    logger = setup_logger(args.debug)

    # 1. 参数合法性校验
    logger.info("🔍 开始参数合法性校验...")
    # 重试次数校验
    if args.retry < 0:
        logger.error(f"❌ 错误：--retry必须≥0（当前：{args.retry}）")
        sys.exit(1)
    # 超时时间校验
    if args.timeout <= 0:
        logger.error(f"❌ 错误：--timeout必须>0（当前：{args.timeout}）")
        sys.exit(1)
    # 重试延迟校验
    if args.retry_delay < 0:
        logger.error(f"❌ 错误：--retry-delay必须≥0（当前：{args.retry_delay}）")
        sys.exit(1)
    # 总任务数校验
    if args.total_tasks is not None:
        if args.total_tasks < 1:
            logger.error("❌ 错误：--total-tasks必须≥1")
            sys.exit(1)
        if args.hours is not None or args.once:
            logger.warning(f"⚠️  警告：已指定--total-tasks={args.total_tasks}，将忽略--hours/--once参数")
            args.hours = None
            args.once = False
    # 小时模式参数校验
    else:
        if args.hours is not None and args.hours <= 0:
            logger.error("❌ 错误：--hours必须是大于0的数字")
            sys.exit(1)
        if args.tasks_per_location < 1:
            logger.error("❌ 错误：--tasks-per-location必须≥1")
            sys.exit(1)
    logger.info("✅ 参数合法性校验通过")

    # 2. 加载config.ini配置（强制校验必填项）
    logger.info(f"📂 加载配置文件：{args.config}")
    ini_cfg = load_ini_config(args.config, logger)

    # 3. 确定最终配置（命令行参数优先级高于config.ini）
    final_host = args.host if args.host else ini_cfg["host"]
    final_port = args.port if args.port else ini_cfg["port"]
    final_locations = args.locations if args.locations else ini_cfg["locations"]
    final_areas = args.areas if args.areas else ini_cfg["areas"]
    
    # 验证最终host/port（冗余校验，确保万无一失）
    if not validate_host(final_host, logger) or not validate_port(final_port, logger):
        sys.exit(1)
    
    # 输出最终配置
    logger.info(SEPARATOR)
    logger.info("⚙️  最终运行配置：")
    logger.info(f"  - 服务地址：{args.protocol}://{final_host}:{final_port}")
    logger.info(f"  - 业务成功条件：接口返回 error_id = {TARGET_ERROR_ID}")
    logger.info(f"  - 取货库位：{len(final_locations)}个（{', '.join(final_locations)}）")
    logger.info(f"  - 放货区域：{len(final_areas)}个（{', '.join(final_areas)}）")
    logger.info(f"  - 请求超时：{args.timeout}秒")
    logger.info(f"  - 重试次数：{args.retry}次")
    logger.info(f"  - 重试延迟：{args.retry_delay}秒")
    logger.info(f"  - 连续失败阈值：{MAX_CONSECUTIVE_FAIL}次（达到后自动停止）")
    logger.info(SEPARATOR)

    # 4. 加载Token（从config.ini[base]读取，必填）
    token = load_token(args.token_file, logger)
    logger.info("✅ Token加载成功")
    logger.info(SEPARATOR)

    # 5. 初始化核心组件
    try:
        area_selector = RandomAreaSelector(final_areas)
    except ValueError as e:
        logger.error(f"❌ 区域初始化失败：{e}")
        sys.exit(1)
    
    base_url = f"{args.protocol}://{final_host}:{final_port}"
    tasks_per_location = args.tasks_per_location
    total_tasks_per_hour = tasks_per_location * len(final_locations)
    interval = 3600.0 / total_tasks_per_hour if total_tasks_per_hour > 0 else 0

    # 6. 初始化统计对象
    start_time_iso = datetime.now().isoformat()
    stats = TaskStats(
        start_time=start_time_iso,
        end_time="",
        total_tasks_target=args.total_tasks if args.total_tasks else (f"{args.hours}小时" if args.hours else "1小时（--once）"),
        area_usage=area_selector.get_usage()
    )

    # 7. 初始化请求会话
    session = requests.Session()
    # 增加重试适配器（连接超时重试）
    retry_adapter = requests.adapters.HTTPAdapter(max_retries=2)
    session.mount(f"{args.protocol}://", retry_adapter)

    # 核心统计变量
    total_success = 0  # 业务成功次数（error_id匹配）
    total_failure = 0  # 总失败次数（HTTP失败+业务失败）
    total_http_success = 0  # HTTP成功但业务失败的次数
    consecutive_fail_count = 0  # 连续失败计数器
    start_ts = time.time()

    # ====================== 总任务数模式 ======================
    if args.total_tasks is not None:
        logger.info(f"🚀 总任务数模式启动")
        logger.info(f"  目标：业务成功 {args.total_tasks} 次")
        logger.info(f"  重试：{args.retry} 次/任务")
        logger.info(f"  连续失败{MAX_CONSECUTIVE_FAIL}次将自动停止")
        logger.info(SEPARATOR)
        try:
            loc_index = 0  # 库位轮询索引
            while total_success < args.total_tasks:
                # 连续失败检查：达到阈值则停止
                if consecutive_fail_count >= MAX_CONSECUTIVE_FAIL:
                    logger.error(SUB_SEPARATOR)
                    logger.error(f"❌ 连续{MAX_CONSECUTIVE_FAIL}次任务失败，强制停止程序")
                    logger.error(f"  失败原因：最近{MAX_CONSECUTIVE_FAIL}次任务均未满足业务成功条件（error_id={TARGET_ERROR_ID}）")
                    logger.error(SUB_SEPARATOR)
                    break
                
                # 轮询库位（均匀覆盖）
                location = final_locations[loc_index % len(final_locations)]
                loc_index += 1
                
                # 随机选择区域
                area = area_selector.select()

                # 发送任务（带重试+业务校验）
                ok, resp_or_err, info, data, error_id, business_info = send_task_with_retry(
                    session, base_url, token, location, area, logger,
                    timeout=args.timeout, retry_count=args.retry, retry_delay=args.retry_delay,
                    debug=args.debug
                )

                # 更新统计和连续失败计数器
                if ok:
                    # 业务成功：重置连续失败计数器
                    total_success += 1
                    consecutive_fail_count = 0
                    logger.info(f"📊 累计业务成功：{total_success}/{args.total_tasks}")
                    logger.info(SUB_SEPARATOR)
                else:
                    # 任务失败：累计失败次数和连续失败计数器
                    total_failure += 1
                    consecutive_fail_count += 1
                    
                    # 判断是否是HTTP成功但业务失败
                    if isinstance(resp_or_err, requests.Response) and resp_or_err.status_code >= 200 and resp_or_err.status_code < 300:
                        total_http_success += 1
                        fail_type = "HTTP成功-业务失败"
                    else:
                        fail_type = "HTTP失败"
                    
                    logger.error(f"⚠️  累计失败：{total_failure}次 | 连续失败：{consecutive_fail_count}/{MAX_CONSECUTIVE_FAIL}")
                    logger.error(f"  失败类型：{fail_type} | error_id：{error_id} | 信息：{business_info}")
                    logger.error(SUB_SEPARATOR)

            # 模式结束处理
            if consecutive_fail_count >= MAX_CONSECUTIVE_FAIL:
                logger.info(SEPARATOR)
                logger.info("❌ 程序因连续失败终止")
            else:
                logger.info(SEPARATOR)
                logger.info(f"🎉 总任务数模式完成！")
                logger.info(f"  目标业务成功：{args.total_tasks}次")
                logger.info(f"  实际业务成功：{total_success}次")
                logger.info(SEPARATOR)

        except KeyboardInterrupt:
            logger.info(f"\n{SUB_SEPARATOR}")
            logger.info("⚠️  程序被用户中断（总任务数模式）")
            logger.info(f"  中断时统计：业务成功 {total_success} 次，总失败 {total_failure} 次，连续失败 {consecutive_fail_count} 次")
            logger.info(SUB_SEPARATOR)

    # ====================== 小时模式 ======================
    else:
        hour_count = 0
        end_ts = start_ts + args.hours * 3600 if args.hours else None

        logger.info(f"🚀 小时模式启动")
        if end_ts:
            logger.info(f"  计划运行：{args.hours}小时，预计结束时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_ts))}")
        elif args.once:
            logger.info(f"  运行模式：仅运行1小时后退出")
        else:
            logger.info(f"  运行模式：持续运行（按Ctrl+C中断）")
        logger.info(f"  每个库位每小时任务数：{tasks_per_location}")
        logger.info(f"  每小时总任务数：{total_tasks_per_hour}（{len(final_locations)}个库位 × {tasks_per_location}个/库位）")
        logger.info(f"  任务间隔：{interval:.1f}秒")
        logger.info(SEPARATOR)

        try:
            while True:
                # 初始化当前小时
                hour_count += 1
                current_hour_success = 0
                current_hour_failure = 0
                current_hour_http_success = 0
                area_selector.reset()
                
                logger.info(f"⏰ 第{hour_count}小时任务开始")
                logger.info(f"  开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(SUB_SEPARATOR)

                time_up = False
                # 循环发布任务
                for task_idx in range(tasks_per_location):
                    for loc_idx, location in enumerate(final_locations):
                        if end_ts and time.time() >= end_ts:
                            time_up = True
                            logger.info("⏳ 已到达指定运行时长，停止发布新任务")
                            break

                        # 检查连续失败：达到阈值则停止
                        if consecutive_fail_count >= MAX_CONSECUTIVE_FAIL:
                            logger.error(SUB_SEPARATOR)
                            logger.error(f"❌ 连续{MAX_CONSECUTIVE_FAIL}次任务失败，强制停止程序")
                            logger.error(f"  失败原因：最近{MAX_CONSECUTIVE_FAIL}次任务均未满足业务成功条件（error_id={TARGET_ERROR_ID}）")
                            logger.error(SUB_SEPARATOR)
                            time_up = True
                            break

                        area = area_selector.select()

                        # 发送任务（带重试+业务校验）
                        ok, resp_or_err, info, data, error_id, business_info = send_task_with_retry(
                            session, base_url, token, location, area, logger,
                            timeout=args.timeout, retry_count=args.retry, retry_delay=args.retry_delay,
                            debug=args.debug
                        )

                        # 更新统计
                        if ok:
                            # 业务成功
                            current_hour_success += 1
                            total_success += 1
                            consecutive_fail_count = 0
                            logger.info(f"📊 第{hour_count}小时累计成功：{current_hour_success}个 | 全局累计成功：{total_success}个")
                            logger.info(SUB_SEPARATOR)
                        else:
                            # 任务失败
                            current_hour_failure += 1
                            total_failure += 1
                            consecutive_fail_count += 1
                            
                            # 判断失败类型
                            if isinstance(resp_or_err, requests.Response) and resp_or_err.status_code >= 200 and resp_or_err.status_code < 300:
                                current_hour_http_success += 1
                                total_http_success += 1
                                fail_type = "HTTP成功-业务失败"
                            else:
                                fail_type = "HTTP失败"
                            
                            logger.error(f"⚠️  第{hour_count}小时累计失败：{current_hour_failure}个 | 连续失败：{consecutive_fail_count}/{MAX_CONSECUTIVE_FAIL}")
                            logger.error(f"  失败类型：{fail_type} | error_id：{error_id} | 信息：{business_info}")
                            logger.error(SUB_SEPARATOR)

                        # 任务间隔
                        if (task_idx != tasks_per_location - 1) or (loc_idx != len(final_locations) - 1):
                            expected_next_time = start_ts + ((hour_count - 1) * total_tasks_per_hour + task_idx * len(final_locations) + loc_idx + 1) * interval
                            sleep_time = expected_next_time - time.time()
                            if sleep_time > 0:
                                time.sleep(sleep_time)
                            else:
                                logger.warning(f"⌛ 任务发布延迟，跳过休眠（延迟：{abs(sleep_time):.1f}秒）")

                    if time_up:
                        break

                # 记录当前小时统计
                hour_stats = {
                    "hour": hour_count,
                    "business_success": current_hour_success,
                    "http_success_business_fail": current_hour_http_success,
                    "total_failure": current_hour_failure,
                    "total": current_hour_success + current_hour_failure
                }
                stats.per_hour_stats.append(hour_stats)
                
                # 输出当前小时统计
                logger.info(f"⏰ 第{hour_count}小时任务结束")
                logger.info(f"  结束时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"  业务成功：{current_hour_success}个 | HTTP成功业务失败：{current_hour_http_success}个 | 总失败：{current_hour_failure}个")
                logger.info(f"  本小时任务总数：{current_hour_success + current_hour_failure}个")
                logger.info(SEPARATOR)

                # 退出条件
                if consecutive_fail_count >= MAX_CONSECUTIVE_FAIL:
                    break
                if end_ts and time.time() >= end_ts:
                    logger.info(f"🎉 运行时长已达{args.hours}小时，退出程序")
                    break
                elif args.once:
                    logger.info("🎉 已运行1小时（--once模式），退出程序")
                    break

                # 等待到下一小时
                next_hour_start = start_ts + (hour_count * 3600)
                current_time = time.time()
                if next_hour_start > current_time:
                    wait_time = next_hour_start - current_time
                    logger.info(f"⌛ 等待到下一小时开始，剩余{wait_time:.1f}秒")
                    time.sleep(wait_time)

        except KeyboardInterrupt:
            logger.info(f"\n{SUB_SEPARATOR}")
            logger.info("⚠️  程序被用户中断（小时模式）")
            # 补充记录当前小时统计（中文描述）
            if current_hour_success + current_hour_failure > 0:
                logger.info(f"  第{hour_count}小时统计（中断）：")
                logger.info(f"    - 小时数：{hour_count}")
                logger.info(f"    - 业务成功：{current_hour_success}个")
                logger.info(f"    - HTTP成功业务失败：{current_hour_http_success}个")
                logger.info(f"    - 总失败：{current_hour_failure}个")
                logger.info(f"    - 任务总数：{current_hour_success + current_hour_failure}个")
                logger.info(f"    - 状态：已中断")
            logger.info(SUB_SEPARATOR)

    # ====================== 最终统计输出（优化格式）======================
    # 更新统计结果
    stats.end_time = datetime.now().isoformat()
    stats.total_duration = time.time() - start_ts
    stats.consecutive_fail_final = consecutive_fail_count
    stats.area_usage = area_selector.get_usage()
    stats.total_success = total_success
    stats.total_failure = total_failure
    stats.total_http_success = total_http_success

    # 输出最终统计（优化排版，便于阅读）
    print("\n" + "="*80)
    print("📊 最终统计汇总")
    print("="*80)
    print(f"📅 业务成功条件：error_id = {TARGET_ERROR_ID}")
    print(f"📅 启动时间：{stats.start_time.split('T')[0]} {stats.start_time.split('T')[1].split('.')[0]}")
    print(f"📅 结束时间：{stats.end_time.split('T')[0]} {stats.end_time.split('T')[1].split('.')[0]}")
    print(f"🔧 运行模式：{'总任务数模式' if args.total_tasks else '小时模式'}")
    print(f"🎯 运行目标：{stats.total_tasks_target}")
    print("-"*80)
    print(f"✅ 业务成功次数：{stats.total_success}")
    print(f"❌ 总失败次数：{stats.total_failure}")
    print(f"⚠️  HTTP成功但业务失败次数：{stats.total_http_success}")
    print(f"📈 任务成功率：{stats.calculate_success_rate():.2%}")
    print(f"🔄 最后连续失败次数：{stats.consecutive_fail_final}")
    print("-"*80)
    print(f"⏱️  总耗时：{stats.total_duration:.2f}秒（{stats.total_duration/3600:.2f}小时）")
    print("-"*80)
    print(f"⚙️  运行参数：")
    print(f"  - 服务地址：{args.protocol}://{final_host}:{final_port}")
    print(f"  - 请求超时：{args.timeout}秒")
    print(f"  - 重试次数：{args.retry}次")
    print(f"  - 重试延迟：{args.retry_delay}秒")
    print("-"*80)
    print(f"🏢 区域使用情况：")
    for area, count in sorted(stats.area_usage.items()):
        print(f"  - {area}：{count}次")
    print("="*80)

    if args.total_tasks is None and stats.per_hour_stats:
        print("\n📋 每小时任务明细：")
        print("-"*80)
        print(f"{'小时':<6} {'业务成功':<10} {'HTTP成功业务失败':<15} {'总失败':<10} {'总计':<10} {'状态':<10}")
        print("-"*80)
        for h in stats.per_hour_stats:
            status = h.get("status", "已完成")
            print(f"{h['hour']:<6} {h['business_success']:<10} {h['http_success_business_fail']:<15} {h['total_failure']:<10} {h['total']:<10} {status:<10}")
        print("="*80)

if __name__ == "__main__":
    main()