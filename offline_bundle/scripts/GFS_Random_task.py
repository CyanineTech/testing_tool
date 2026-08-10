import argparse
import configparser
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import random
import requests
import signal
import subprocess
import sys
import threading
import time
try:
    import mysql.connector
except ModuleNotFoundError as e:
    # 常见原因：未使用本项目的.venv解释器运行（系统python3缺少依赖）
    if str(e).strip() == "No module named 'mysql'":
        raise SystemExit(
            "缺少依赖：mysql-connector-python（import mysql.connector失败）。\n"
            "请用虚拟环境解释器运行：\n"
            "  ./.venv/bin/python GFS_Random_task.py\n"
            "或先激活虚拟环境后再运行：\n"
            "  source .venv/bin/activate && python GFS_Random_task.py\n"
            "如果必须用系统python3运行，则安装到系统环境：\n"
            "  pip3 install mysql-connector-python\n"
        )
    raise
from typing import Dict, List, Optional, Set

# 用于响应web_service.py的停止请求（SIGTERM）
STOP_EVENT = threading.Event()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "login.py")
DEFAULT_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")


def _handle_stop_signal(sig, frame):
    """收到停止信号后设置退出标志，让主循环尽快结束。"""
    try:
        logging.info(f"🛑 收到停止信号({sig})，准备退出...")
    except Exception:
        pass
    STOP_EVENT.set()


def _load_token_from_config(config_path: str) -> Optional[str]:
    """从 config.ini 的 [base] 段读取 Bearer Token。"""
    if not os.path.exists(config_path):
        logging.error(f"❌ 配置文件不存在：{config_path}")
        return None

    config = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=(";", "#"),
    )

    try:
        if not config.read(config_path, encoding="utf-8"):
            logging.error(f"❌ 读取配置文件失败：{config_path}")
            return None
    except Exception as e:
        logging.error(f"❌ 解析配置文件失败：{e}")
        return None

    if not config.has_section("base"):
        logging.error("❌ 配置文件缺少 [base] 段")
        return None

    if not config.has_option("base", "token"):
        logging.error("❌ 配置文件 [base] 段缺少 token")
        return None

    token = config.get("base", "token", fallback="").strip()
    if not token:
        logging.error("❌ 配置文件 [base] 段的 token 为空")
        return None

    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    return token


def _run_startup_login(config_path: str) -> Optional[str]:
    """程序启动时执行同目录下的 login.py，并返回 config.ini 里的 token。"""
    if not os.path.exists(LOGIN_SCRIPT_PATH):
        logging.error(f"❌ 未找到登录脚本：{LOGIN_SCRIPT_PATH}")
        return None

    try:
        logging.info(f"🔐 启动登录脚本：{LOGIN_SCRIPT_PATH}")
        result = subprocess.run(
            [sys.executable, "-u", LOGIN_SCRIPT_PATH, "--config", config_path],
            check=False,
        )
    except Exception as e:
        logging.error(f"❌ 执行登录脚本失败：{e}")
        return None

    if result.returncode != 0:
        logging.error(f"❌ 登录脚本执行失败，返回码：{result.returncode}")
        return None

    token = _load_token_from_config(config_path)
    if not token:
        logging.error("❌ 登录完成后未能从 config.ini 的 [base] 段读取到 token")
        return None

    return token

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'warehouse_task_dispatcher.log',
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)

class WarehouseTaskDispatcher:
    def __init__(self, weights=None, host: Optional[str] = None, scene_id: Optional[int] = None,
                 release_locations: bool = False, release_is_all: bool = False,
                 release_interval_seconds: int = 30 * 60,
                 bearer_token: Optional[str] = None):
        base_host = (host or 'ubuntu-180').strip()
        base_scene_id = scene_id if scene_id is not None else 68
        self.db_config = {
            'host': base_host,  # 可由命令行--host覆盖
            'port': 13306,
            'user': 'root',
            'password': 'wudier**//',
            'database': 'map_server',
            # 避免网络/DB异常时长时间卡住导致“无响应”
            'connection_timeout': 5
        }
        self.api_url = f"http://{base_host}:9990/dispatch_server/dispatch/start/location_call/task/"
        self.release_location_url = f"http://{base_host}:9990/location_manage_server/locations/release_location/all/"
        self.scene_id = base_scene_id
        self.release_locations = release_locations
        self.release_is_all = release_is_all
        self.release_interval_seconds = int(release_interval_seconds)
        self._last_release_ts: Optional[float] = None
        self.bearer_token = (bearer_token or "").strip()
        self.release_headers = {}
        if self.bearer_token:
            self.release_headers = {"Authorization": f"Bearer {self.bearer_token}"}

        # ===== storage_area 状态监控（按area_index最大记录的use_status） =====
        # 说明：每次发布任务前会批量查询一次DB（脚本本身每轮sleep 30s，因此天然是30s频率）
        self.area_status_table = "pallet_pos"
        self.area_status_area_col = "area"
        self.area_status_index_col = "area_index"
        self.area_status_use_status_col = "use_status"
        self.area_status_scene_col = "scene_id"
        self.area_status_poll_seconds = 30
        self._blocked_storage_areas: Set[str] = set()
        self._last_area_status_refresh_ts: float = 0.0
        
        # 仓库权重配置（默认均匀分布）
        self.warehouse_weights = weights or {'103': 0.333, '102': 0.333, '101': 0.334}
        
        # 定义三大仓库的放货区域
        self.warehouse_rules = {
            '103': {
                'storage_areas': [
                    '1003', '1006','1016', '1018', '1023', '1028', '1029', 
                    '1038', '1033', '1040', '1045', '1049', '1054', '1055', '1060', 
                    '1061', '1062', '1064', '1067', '1070', '1072', '1074', 
                    '1078', '1075', '1080', '1079'
                ],
                'pickup_area': '1103'  # 103仓库的取货区域
            },
            '102': {
                'storage_areas': [
                    '1015', '1020', '1041', '1042',
                    '1026', '1032', '1034', '1035', '1037', 
                    '1044', '1048', '1050', '1053', '1065', '1069', '1071', 
                    '1073', '1076', '1083'
                ],
                'pickup_area': '1103'  # 102仓库的取货区域
            },
            '101': {
                'storage_areas': [
                    '1001', '1009', '1010/1011', '1013', 
                    '1014', '1021', '1022', '1024', '1025', '1027', '1030', 
                    '1036', '1039', '1043', '1046', '1056', '1057', '1058', 
                    '1059/1063', '1066/1068', '1081', '1086', '1084', '1087'
                ],
                'pickup_area': '101Q'  # 101仓库的取货区域
            }
        }
        
        # 统计信息
        self.task_stats = {
            'total_tasks': 0,
            'warehouse_103': 0,
            'warehouse_102': 0,
            'warehouse_101': 0
        }
    
    def get_db_connection(self):
        """获取数据库连接"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            return conn
        except mysql.connector.Error as e:
            logging.error(f"数据库连接失败: {e}")
            return None

    def _get_all_storage_areas(self) -> List[str]:
        """获取当前脚本配置的所有storage_areas（去重）"""
        all_areas: Set[str] = set()
        for rules in self.warehouse_rules.values():
            for a in rules.get('storage_areas', []) or []:
                if a and str(a).strip():
                    all_areas.add(str(a).strip())
        return sorted(all_areas)

    def _fetch_latest_use_status_for_areas(self, areas: List[str]) -> Dict[str, str]:
        """批量查询：每个area取area_index最大的一条记录，并返回其use_status。

        返回：{area: use_status}
        """
        if not areas:
            return {}

        conn = self.get_db_connection()
        if not conn:
            return {}

        # 生成 IN (%s, %s, ...) 占位符
        placeholders = ",".join(["%s"] * len(areas))
        t = self.area_status_table
        area_col = self.area_status_area_col
        idx_col = self.area_status_index_col
        status_col = self.area_status_use_status_col
        scene_col = self.area_status_scene_col

        query = f"""
            SELECT x.{area_col} AS area, x.{status_col} AS use_status
            FROM {t} x
            JOIN (
                SELECT {area_col} AS area, MAX({idx_col}) AS max_idx
                FROM {t}
                WHERE {scene_col} = %s
                  AND {area_col} IN ({placeholders})
                GROUP BY {area_col}
            ) m
              ON x.{area_col} = m.area AND x.{idx_col} = m.max_idx
            WHERE x.{scene_col} = %s
        """

        # params：子查询(scene_id + areas...) + 外层(scene_id)
        params: List[object] = [self.scene_id] + areas + [self.scene_id]

        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params)
            rows = cursor.fetchall() or []
            result: Dict[str, str] = {}
            for row in rows:
                area = str(row.get('area', '')).strip()
                if not area:
                    continue
                use_status = str(row.get('use_status', '')).strip()
                result[area] = use_status
            return result
        except mysql.connector.Error as e:
            logging.error(f"查询storage_area状态失败: {e}")
            return {}
        finally:
            try:
                cursor.close()
            except Exception:
                pass
            conn.close()

    def refresh_blocked_storage_areas(self, force: bool = False) -> None:
        """刷新被阻塞的storage_areas集合。

        规则：每个area取最大area_index的use_status，若use_status != 'free' 则阻塞。
        """
        now = time.time()
        if not force and (now - self._last_area_status_refresh_ts) < float(self.area_status_poll_seconds):
            return

        areas = self._get_all_storage_areas()
        statuses = self._fetch_latest_use_status_for_areas(areas)
        if not statuses:
            # 查询失败或无数据：不更新阻塞集合（保留上一次结果），避免抖动
            self._last_area_status_refresh_ts = now
            return

        blocked_now: Set[str] = set()
        for area, status in statuses.items():
            if str(status).strip().lower() != 'free':
                blocked_now.add(area)

        newly_blocked = sorted(list(blocked_now - self._blocked_storage_areas))
        newly_unblocked = sorted(list(self._blocked_storage_areas - blocked_now))

        self._blocked_storage_areas = blocked_now
        self._last_area_status_refresh_ts = now

        if newly_blocked:
            logging.warning(f"⛔ storage_area被阻塞（use_status != free）：{', '.join(newly_blocked)}")
        if newly_unblocked:
            logging.info(f"✅ storage_area恢复可用（use_status == free）：{', '.join(newly_unblocked)}")
    
    def get_pickup_location_for_warehouse(self, warehouse_id):
        """获取指定仓库的取货库位"""
        conn = self.get_db_connection()
        if not conn:
            return None
            
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT id, area 
                FROM pallet_pos 
                WHERE scene_id = %s  # 使用self.scene_id
                AND area = %s
                AND area IS NOT NULL 
                AND area != ''
                AND COALESCE(LOWER(task_use_status), '') != 'to_be_picked_up'
                ORDER BY RAND() 
                LIMIT 1
            """
            pickup_area = self.warehouse_rules[warehouse_id]['pickup_area']
            cursor.execute(query, (self.scene_id, pickup_area))
            result = cursor.fetchone()
            if not result:
                logging.warning(
                    f"⚠️ {warehouse_id}仓库取货区域({pickup_area})暂无可用库位，"
                    "已排除 task_use_status = to_be_picked_up 的记录"
                )
            return result
        except mysql.connector.Error as e:
            logging.error(f"查询{warehouse_id}仓库取货库位失败: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def get_random_storage_area(self, warehouse_id):
        """随机获取指定仓库的一个放货区域"""
        storage_areas = self.warehouse_rules[warehouse_id]['storage_areas']
        if not storage_areas:
            return None

        # 确保阻塞列表是最新的（默认30s刷新一次）
        self.refresh_blocked_storage_areas()

        available = [a for a in storage_areas if a not in self._blocked_storage_areas]
        if not available:
            logging.warning(f"⚠️ {warehouse_id}仓库所有放货区域当前均不可用（use_status != free），将跳过本轮发布")
            return None
        return random.choice(available)
    
    def get_weighted_warehouse(self):
        """根据权重选择一个仓库"""
        warehouses = list(self.warehouse_weights.keys())
        weights = list(self.warehouse_weights.values())
        return random.choices(warehouses, weights=weights, k=1)[0]
    
    def send_warehouse_task(self, warehouse_id, location_id, storage_area):
        """发送仓库任务 - 使用PUT方法"""
        payload = {
            "1": 1,  # 固定值
            "location_id": location_id,
            "area": storage_area
        }
        
        logging.info(f"📤 PUT请求URL: {self.api_url}")
        logging.info(f"📤 PUT请求参数: {json.dumps(payload, ensure_ascii=False)}")
        
        try:
            response = requests.put(
                self.api_url,
                json=payload,
                headers=self.release_headers,
                timeout=10,
            )
            logging.info(f"📥 响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                    task_id = response_data.get('data', {}).get('running_id', '未知')
                    logging.info(f"✅ 任务发送成功! 任务ID: {task_id}")
                except:
                    logging.info(f"✅ 任务发送成功! 响应: {response.text[:200]}")
                
                logging.info(f"📋 任务详情: 取货库位={location_id}(区域:{self.get_location_area(location_id)}) → 放货区域={storage_area}")
                
                # 更新统计信息
                self.task_stats[f'warehouse_{warehouse_id}'] += 1
                self.task_stats['total_tasks'] += 1
                
                return True
            else:
                logging.error(f"❌ 任务发送失败: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ 请求异常: {e}")
            return False

    def release_location_status(self) -> bool:
        """释放库位占用状态。

        is_all=False: 仅释放库位使用状态
        is_all=True : 释放手动占用库位
        """
        payload = {"is_all": bool(self.release_is_all)}
        logging.info(f"🔁 释放库位请求URL: {self.release_location_url}")
        logging.info(f"🔁 释放库位参数: {json.dumps(payload, ensure_ascii=False)}")

        if not self.release_headers.get("Authorization"):
            logging.error("❌ 缺少 Bearer Token，无法调用释放库位接口")
            return False

        try:
            response = requests.delete(
                self.release_location_url,
                json=payload,
                headers=self.release_headers,
                timeout=10,
            )
            logging.info(f"🔁 释放库位响应状态码: {response.status_code}")
            if response.status_code == 200:
                return True
            logging.warning(f"⚠️ 释放库位失败: {response.status_code} - {response.text}")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ 释放库位请求异常: {e}")
            return False
    
    def get_location_area(self, location_id):
        """获取库位区域"""
        conn = self.get_db_connection()
        if not conn:
            return "未知"
            
        try:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT area FROM pallet_pos WHERE id = %s AND scene_id = %s"
            cursor.execute(query, (location_id, self.scene_id))
            result = cursor.fetchone()
            return result['area'] if result else "未知"
        except mysql.connector.Error:
            return "未知"
        finally:
            cursor.close()
            conn.close()
    
    def print_statistics(self):
        """打印统计信息"""
        if self.task_stats['total_tasks'] > 0:
            warehouse_103_percent = (self.task_stats['warehouse_103'] / self.task_stats['total_tasks']) * 100
            warehouse_102_percent = (self.task_stats['warehouse_102'] / self.task_stats['total_tasks']) * 100
            warehouse_101_percent = (self.task_stats['warehouse_101'] / self.task_stats['total_tasks']) * 100
            
            logging.info("📊 仓库任务统计信息:")
            logging.info(f"   总任务数: {self.task_stats['total_tasks']}")
            logging.info(f"   103仓库任务: {self.task_stats['warehouse_103']} ({warehouse_103_percent:.1f}%)")
            logging.info(f"   102仓库任务: {self.task_stats['warehouse_102']} ({warehouse_102_percent:.1f}%)")
            logging.info(f"   101仓库任务: {self.task_stats['warehouse_101']} ({warehouse_101_percent:.1f}%)")
            
            # 显示预期权重 vs 实际分布
            logging.info("🎯 权重分布对比:")
            logging.info(f"   预期权重: 103={self.warehouse_weights['103']*100:.1f}%, "
                        f"102={self.warehouse_weights['102']*100:.1f}%, "
                        f"101={self.warehouse_weights['101']*100:.1f}%")
    
    def validate_warehouse_rules(self):
        """验证仓库规则配置"""
        logging.info("🔍 仓库规则配置:")
        
        for warehouse_id, rules in self.warehouse_rules.items():
            logging.info(f"\n  {warehouse_id}仓库:")
            logging.info(f"    取货区域: {rules['pickup_area']}")
            logging.info(f"    放货区域数量: {len(rules['storage_areas'])}个")
            logging.info(f"    放货区域示例: {rules['storage_areas'][:5]}...")
        
        logging.info(f"\n🎲 仓库选择权重:")
        for warehouse_id, weight in self.warehouse_weights.items():
            logging.info(f"  {warehouse_id}仓库: {weight*100:.1f}%")
    
    def test_connection(self):
        """测试数据库和接口连接"""
        logging.info("🔍 测试连接...")
        
        # 测试数据库连接
        conn = self.get_db_connection()
        if not conn:
            logging.error("❌ 数据库连接失败")
            return False
        
        try:
            cursor = conn.cursor(dictionary=True)
            
            # 检查三大仓库的取货区域是否有数据
            for warehouse_id in ['103', '102', '101']:
                pickup_area = self.warehouse_rules[warehouse_id]['pickup_area']
                query = """
                    SELECT COUNT(*) as count 
                    FROM pallet_pos 
                    WHERE scene_id = %s 
                    AND area = %s
                    AND COALESCE(LOWER(task_use_status), '') != 'to_be_picked_up'
                """
                cursor.execute(query, (self.scene_id, pickup_area))
                result = cursor.fetchone()
                count = result['count'] if result else 0
                logging.info(f"  {warehouse_id}仓库取货区域({pickup_area})可用库位数量: {count}")
                
                if count == 0:
                    logging.warning(
                        f"⚠️ {warehouse_id}仓库取货区域({pickup_area})没有可用库位数据!"
                    )
            
            # 测试接口连接
            logging.info("🔍 测试接口连接...")
            test_payload = {
                "1": 1,
                "location_id": "pp_69f8d7d8",  # 使用已知的库位ID
                "area": "1023"  # 使用已知的放货区域
            }
            
            try:
                response = requests.put(
                    self.api_url,
                    json=test_payload,
                    headers=self.release_headers,
                    timeout=5,
                )
                logging.info(f"📥 接口测试响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    logging.info("✅ 接口连接测试成功!")
                else:
                    logging.warning(f"⚠️ 接口返回非200状态码: {response.status_code}")
                    logging.info(f"📄 响应内容: {response.text[:200]}")
            
            except requests.exceptions.RequestException as e:
                logging.error(f"❌ 接口连接失败: {e}")
                return False
            
            return True
            
        except mysql.connector.Error as e:
            logging.error(f"❌ 数据库查询失败: {e}")
            return False
        finally:
            if conn:
                conn.close()
    
    def run(self):
        """主循环"""
        logging.info("🚀 仓库任务调度器启动...")
        logging.info(f"🎯 数据库服务器: {self.db_config['host']}:{self.db_config['port']}")
        logging.info(f"🎯 接口服务器: {self.api_url}")
        logging.info(f"🎯 Scene ID: {self.scene_id}")
        
        # 验证仓库规则
        self.validate_warehouse_rules()
        
        # 测试连接
        if not self.test_connection():
            logging.error("❌ 连接测试失败，退出程序")
            return False

        if self.release_locations:
            self.release_location_status()
            self._last_release_ts = time.time()
            logging.info(f"🕒 已启用库位释放，每 {self.release_interval_seconds} 秒执行一次")
        else:
            logging.info("ℹ️ 未启用库位释放接口（如需启用请加 --release-locations）")
        
        task_count = 0
        
        while not STOP_EVENT.is_set():
            try:
                task_count += 1
                logging.info(f"\n📦 准备发送第 {task_count} 个任务...")

                if self.release_locations and self._last_release_ts is not None:
                    now = time.time()
                    if (now - self._last_release_ts) >= self.release_interval_seconds:
                        self.release_location_status()
                        self._last_release_ts = now

                # 0. 发布前校验一次数据库：刷新所有storage_areas的阻塞状态
                self.refresh_blocked_storage_areas(force=True)
                
                # 1-3. 选择仓库 + 取货库位 + 放货区域
                # 若某个仓库当前全部放货区域被阻塞，则尝试切换其他仓库（避免整轮跳过）
                warehouse_id = None
                pickup_data = None
                storage_area = None
                attempted: Set[str] = set()
                for _ in range(len(self.warehouse_weights)):
                    # 根据权重选择一个仓库（尽量不重复）
                    candidate = self.get_weighted_warehouse()
                    if candidate in attempted and len(attempted) < len(self.warehouse_weights):
                        # 轻量避免重复抽中同一个仓库
                        continue
                    attempted.add(candidate)

                    logging.info(f"🏭 选中仓库: {candidate} (权重:{self.warehouse_weights[candidate]*100:.1f}%)")

                    candidate_pickup = self.get_pickup_location_for_warehouse(candidate)
                    if not candidate_pickup:
                        logging.warning(f"⚠️ 没有找到{candidate}仓库的取货库位，尝试其他仓库")
                        continue

                    candidate_storage = self.get_random_storage_area(candidate)
                    if not candidate_storage:
                        logging.warning(f"⚠️ {candidate}仓库当前无可用放货区域（可能全部use_status!=free），尝试其他仓库")
                        continue

                    warehouse_id = candidate
                    pickup_data = candidate_pickup
                    storage_area = candidate_storage
                    break

                if not warehouse_id or not pickup_data or not storage_area:
                    logging.warning("⚠️ 本轮未找到可发布的任务组合（取货库位/放货区域不可用），等待30秒后重试")
                    STOP_EVENT.wait(30)
                    continue

                pickup_id = pickup_data['id']
                pickup_area = pickup_data['area']
                logging.info(f"📍 取货库位: ID={pickup_id}, 区域={pickup_area}")
                logging.info(f"🏠 放货区域: {storage_area}")
                
                # 4. 验证规则：取货区域必须匹配仓库
                if pickup_area != self.warehouse_rules[warehouse_id]['pickup_area']:
                    logging.error(f"❌ 规则验证失败: 取货区域{pickup_area}不属于{warehouse_id}仓库")
                    continue
                
                # 5. 发送任务
                success = self.send_warehouse_task(warehouse_id, pickup_id, storage_area)
                
                if not success:
                    logging.error("❌ 任务发送失败，等待重试")
                
                # 6. 每10个任务打印一次统计信息
                if task_count % 10 == 0:
                    self.print_statistics()
                
            except Exception as e:
                logging.error(f"💥 执行过程中发生异常: {e}")
                import traceback
                logging.error(traceback.format_exc())
            
            # 7. 等待30秒
            logging.info("⏳ 等待30秒后发送下一个任务...")
            STOP_EVENT.wait(30)

        logging.info("🛑 已停止任务调度器")
        return True

def main():
    """主函数，支持命令行参数"""
    # 注册停止信号（web_service.py的terminate()在Linux下会发送SIGTERM）
    signal.signal(signal.SIGTERM, _handle_stop_signal)
    signal.signal(signal.SIGINT, _handle_stop_signal)

    parser = argparse.ArgumentParser(description='仓库任务调度器')
    parser.add_argument('--host', type=str, default='ubuntu-180', help='主机名/IP（同时覆盖数据库host与接口URL中的主机名）')
    parser.add_argument('--scene-id', '--scene_id', dest='scene_id', type=int, default=68, help='scene_id（覆盖默认值；兼容--scene_id写法）')
    parser.add_argument('--weights', type=str, help='仓库权重配置，格式：103:0.4,102:0.3,101:0.3')
    parser.add_argument('--release-locations', action='store_true', help='每次启动先调用释放库位接口，并按间隔重复执行')
    parser.add_argument('--release-all', action='store_true', help='释放手动占用库位（is_all=true）')
    parser.add_argument('--release-interval', type=int, default=1800, help='释放库位接口调用间隔（秒，默认1800=30分钟）')
    
    args = parser.parse_args()
    
    # 解析权重参数
    weights = None
    if args.weights:
        try:
            weights = {}
            for item in args.weights.split(','):
                warehouse, weight = item.split(':')
                weights[warehouse.strip()] = float(weight.strip())
            
            # 验证权重总和为1
            total = sum(weights.values())
            if abs(total - 1.0) > 0.001:
                logging.warning(f"权重总和({total:.3f})不为1，将自动归一化")
                for key in weights:
                    weights[key] /= total
                    
            logging.info(f"使用自定义权重: {weights}")
        except Exception as e:
            logging.error(f"权重参数解析失败: {e}")
            return False

    # 程序启动时先执行登录脚本，成功后继续；失败则直接停止
    bearer_token = _run_startup_login(DEFAULT_CONFIG_PATH)
    if not bearer_token:
        logging.error("调用失败")
        return False

    # 创建调度器并运行
    release_locations = True if not args.release_locations else True

    dispatcher = WarehouseTaskDispatcher(
        weights=weights,
        host=args.host,
        scene_id=args.scene_id,
        release_locations=release_locations,
        release_is_all=args.release_all,
        release_interval_seconds=args.release_interval,
        bearer_token=bearer_token,
    )
    return dispatcher.run()

if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
