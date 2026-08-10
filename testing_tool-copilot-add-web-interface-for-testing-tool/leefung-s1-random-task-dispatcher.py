import requests
import mysql.connector
import time
import logging
from logging.handlers import RotatingFileHandler
import json
import random
import configparser
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGIN_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "login.py")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.ini")

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'task_dispatcher.log',
            maxBytes=50 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)

class TaskDispatcher:
    def __init__(self):
        self.host = 'devel-105'
        self.port = 9990
        self.db_config = {
            'host': self.host,
            'port': 13306,
            'user': 'root',
            'password': 'wudier**//',
            'database': 'map_server'
        }
        self.api_url = f"http://{self.host}:{self.port}/dispatch_server/dispatch/start/location_call/task/"
        self.auth_headers = {}
        
        # 定义区域类型规则
        self.area_rules = {
            'cutting': {  # 切纸区
                'areas': ['C50_copy', 'C60_copy', 'C90_copy', 'C100_copy'],
                'can_pickup': True,    # 可以取货
                'can_store': False,    # 不能放货
                'pickup_weight': 0.6   # 60%概率选择切纸区取货
            },
            'buffer': {   # 暂存区
                'areas': [],  # A和B开头的区域，动态判断
                'can_pickup': True,    # 可以取货
                'can_store': True,     # 可以放货
                'pickup_weight': 0.4   # 40%概率选择暂存区取货
            },
            'printing': { # 印刷区
                'areas': [],  # 其他区域
                'can_pickup': False,   # 不能取货
                'can_store': True      # 可以放货
            }
        }
        
        # 统计信息
        self.task_stats = {
            'total_tasks': 0,
            'cutting_pickup': 0,
            'buffer_pickup': 0
        }

    def _load_token(self):
        config = configparser.ConfigParser(
            interpolation=None,
            inline_comment_prefixes=(';', '#')
        )
        try:
            if not config.read(CONFIG_PATH, encoding='utf-8'):
                logging.error(f"❌ 无法读取配置文件: {CONFIG_PATH}")
                return None
            token = config.get('base', 'token', fallback='').strip()
            if token.lower().startswith('bearer '):
                token = token[7:].strip()
            return token or None
        except (configparser.Error, OSError) as e:
            logging.error(f"❌ 读取登录 token 失败: {e}")
            return None

    def login_before_run(self):
        if not os.path.isfile(LOGIN_SCRIPT_PATH):
            logging.error(f"❌ 未找到登录脚本: {LOGIN_SCRIPT_PATH}")
            return False

        logging.info(f"🔐 开始登录服务: {self.host}:{self.port}")
        try:
            result = subprocess.run(
                [
                    sys.executable, '-u', LOGIN_SCRIPT_PATH,
                    '--config', CONFIG_PATH,
                    '--host', self.host,
                    '--port', str(self.port),
                ],
                cwd=SCRIPT_DIR,
                check=False,
            )
        except OSError as e:
            logging.error(f"❌ 调用 login.py 失败: {e}")
            return False

        if result.returncode != 0:
            logging.error(f"❌ 登录失败，返回码: {result.returncode}")
            return False

        token = self._load_token()
        if not token:
            logging.error("❌ 登录完成，但 config.ini 中没有有效 token")
            return False

        self.auth_headers = {'Authorization': f'Bearer {token}'}
        logging.info("✅ 登录成功，已加载最新 token")
        return True
    
    def get_area_type(self, area):
        """根据区域名称判断区域类型"""
        if area in self.area_rules['cutting']['areas']:
            return 'cutting'
        elif area.startswith(('A', 'B')):
            return 'buffer'
        else:
            return 'printing'
    
    def get_db_connection(self):
        """获取数据库连接"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            return conn
        except mysql.connector.Error as e:
            logging.error(f"数据库连接失败: {e}")
            return None
    
    def get_pickup_location_by_type(self, area_type):
        """根据区域类型获取取货库位"""
        conn = self.get_db_connection()
        if not conn:
            return None
            
        try:
            cursor = conn.cursor(dictionary=True)
            
            if area_type == 'cutting':
                # 切纸区：C5, C6, C9, C10
                query = """
                    SELECT id, area 
                    FROM pallet_pos 
                    WHERE scene_id = 9
                    AND area IS NOT NULL 
                    AND area != ''
                    AND area IN (%s, %s, %s, %s)
                    ORDER BY RAND() 
                    LIMIT 1
                """
                cursor.execute(query, ('C50_copy', 'C60_copy', 'C90_copy', 'C100_copy'))
                
            elif area_type == 'buffer':
                # 暂存区：A开头、B开头的区域
                query = """
                    SELECT id, area 
                    FROM pallet_pos 
                    WHERE scene_id = 9 
                    AND area IS NOT NULL 
                    AND area != ''
                    AND (area LIKE 'A%%' OR area LIKE 'B%%')
                    AND area NOT IN (%s, %s, %s, %s)
                    ORDER BY RAND() 
                    LIMIT 1
                """
                cursor.execute(query, ('C50_copy', 'C60_copy', 'C90_copy', 'C100_copy'))
            
            result = cursor.fetchone()
            return result
        except mysql.connector.Error as e:
            logging.error(f"查询{area_type}区取货库位失败: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def get_weighted_pickup_location(self):
        """根据权重获取取货库位（60%切纸区，40%暂存区）"""
        # 生成随机数决定选择哪个区域类型
        rand_val = random.random()
        
        if rand_val < self.area_rules['cutting']['pickup_weight']:
            # 60%概率选择切纸区
            area_type = 'cutting'
            logging.info("🎲 随机选择: 切纸区取货 (60%概率)")
        else:
            # 40%概率选择暂存区
            area_type = 'buffer'
            logging.info("🎲 随机选择: 暂存区取货 (40%概率)")
        
        # 根据选择的区域类型获取库位
        pickup_data = self.get_pickup_location_by_type(area_type)
        
        if pickup_data:
            # 更新统计信息
            if area_type == 'cutting':
                self.task_stats['cutting_pickup'] += 1
            else:
                self.task_stats['buffer_pickup'] += 1
            self.task_stats['total_tasks'] += 1
        
        return pickup_data, area_type
    
    def get_storage_location(self, pickup_area, pickup_area_type):
        """根据取货区域类型获取合适的放货库位"""
        conn = self.get_db_connection()
        if not conn:
            return None
            
        try:
            cursor = conn.cursor(dictionary=True)
            
            if pickup_area_type == 'cutting':
                # 切纸区取货 -> 可以送往暂存区或印刷区
                query = """
                    SELECT id, area 
                    FROM pallet_pos 
                    WHERE scene_id = 9
                    AND area IS NOT NULL 
                    AND area != ''
                    AND (area LIKE 'A%%' OR area LIKE 'B%%' OR 
                         (area NOT IN (%s, %s, %s, %s) AND area NOT LIKE 'A%%' AND area NOT LIKE 'B%%'))
                    AND area != %s
                    ORDER BY RAND() 
                    LIMIT 1
                """
                cursor.execute(query, ('C50_copy', 'C60_copy', 'C90_copy', 'C100_copy', pickup_area))
                
            elif pickup_area_type == 'buffer':
                # 暂存区取货 -> 只能送往印刷区
                query = """
                    SELECT id, area 
                    FROM pallet_pos 
                    WHERE scene_id = 9
                    AND area IS NOT NULL 
                    AND area != ''
                    AND area NOT IN (%s, %s, %s, %s)
                    AND area NOT LIKE 'A%%' 
                    AND area NOT LIKE 'B%%'
                    AND area != %s
                    ORDER BY RAND() 
                    LIMIT 1
                """
                cursor.execute(query, ('C50_copy', 'C60_copy', 'C90_copy', 'C100_copy', pickup_area))
            
            result = cursor.fetchone()
            return result
        except mysql.connector.Error as e:
            logging.error(f"查询放货库位失败: {e}")
            return None
        finally:
            cursor.close()
            conn.close()
    
    def send_task_put(self, area, location_id, store_location_id):
        """使用PUT方法发送任务"""
        payload = {
            "area": area,
            "location_id": location_id,
            "store_location_id": store_location_id
        }
        
        logging.info(f"📤 PUT请求参数: {json.dumps(payload, ensure_ascii=False)}")
        
        try:
            response = requests.put(
                self.api_url,
                json=payload,
                headers=self.auth_headers,
                timeout=10,
            )
            logging.info(f"📥 响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    response_data = response.json()
                except ValueError:
                    logging.error(f"❌ 接口返回非JSON响应: {response.text[:500]}")
                    return False

                if not isinstance(response_data, dict):
                    logging.error(f"❌ 接口返回格式异常: {response_data!r}")
                    return False

                if response_data.get('success') is not True:
                    msg = response_data.get('msg') or {}
                    detail = msg.get('detail') if isinstance(msg, dict) else {}
                    detail = detail if isinstance(detail, dict) else {}
                    error_info = detail.get('info') or detail.get('detail') or '未知业务错误'
                    error_id = detail.get('error_id', '未知')
                    logging.error(f"❌ 任务失败原因: {error_info} (error_id={error_id})")
                    logging.error(
                        f"❌ 任务业务失败: {json.dumps(response_data, ensure_ascii=False)}"
                    )
                    return False

                response_payload = response_data.get('data')
                if not isinstance(response_payload, dict):
                    logging.error(
                        f"❌ 任务响应缺少有效data: {json.dumps(response_data, ensure_ascii=False)}"
                    )
                    return False

                task_id = response_payload.get('running_id', '未知')
                
                # 获取区域类型信息用于日志
                pickup_location_area = self.get_location_area(location_id)
                pickup_area_type = self.get_area_type(pickup_location_area)
                storage_area_type = self.get_area_type(area)
                
                logging.info(f"✅ 任务发送成功! 任务ID: {task_id}")
                logging.info(f"📋 任务流向: {pickup_area_type}区({pickup_location_area}) → {storage_area_type}区({area})")
                return True
            else:
                logging.error(f"❌ 任务发送失败: {response.status_code} - {response.text}")
                return False
        except (requests.exceptions.RequestException, TypeError, AttributeError) as e:
            logging.error(f"❌ 请求异常: {e}")
            return False
    
    def get_location_area(self, location_id):
        """获取库位区域"""
        conn = self.get_db_connection()
        if not conn:
            return "未知"
            
        try:
            cursor = conn.cursor(dictionary=True)
            query = "SELECT area FROM pallet_pos WHERE id = %s"
            cursor.execute(query, (location_id,))
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
            cutting_percent = (self.task_stats['cutting_pickup'] / self.task_stats['total_tasks']) * 100
            buffer_percent = (self.task_stats['buffer_pickup'] / self.task_stats['total_tasks']) * 100
            
            logging.info("📊 任务统计信息:")
            logging.info(f"   总任务数: {self.task_stats['total_tasks']}")
            logging.info(f"   切纸区取货: {self.task_stats['cutting_pickup']} ({cutting_percent:.1f}%)")
            logging.info(f"   暂存区取货: {self.task_stats['buffer_pickup']} ({buffer_percent:.1f}%)")
    
    def validate_area_rules(self):
        """验证区域规则配置"""
        logging.info("🔍 区域规则配置:")
        logging.info(f"  切纸区(只能取货): {self.area_rules['cutting']['areas']} - 权重: 60%")
        logging.info(f"  暂存区(可以取货和放货): A开头、B开头的区域 - 权重: 40%")
        logging.info(f"  印刷区(只能放货): 其他区域")
        logging.info("📋 任务流向规则:")
        logging.info("  切纸区取货 → 暂存区或印刷区放货")
        logging.info("  暂存区取货 → 印刷区放货")
    
    def run(self):
        """主循环"""
        logging.info("🚀 任务调度器启动...")
        logging.info("🎯 使用PUT方法发送任务")
        
        # 验证区域规则
        self.validate_area_rules()
        
        task_count = 0
        
        while True:
            try:
                task_count += 1
                logging.info(f"\n📦 准备发送第 {task_count} 个任务...")
                
                # 1. 根据权重获取取货库位（60%切纸区，40%暂存区）
                pickup_data, pickup_area_type = self.get_weighted_pickup_location()
                if not pickup_data:
                    logging.warning(f"⚠️ 没有找到可用的{pickup_area_type}区取货库位")
                    time.sleep(1)
                    continue
                
                pickup_id = pickup_data['id']
                pickup_area = pickup_data['area']
                logging.info(f"📍 取货库位: ID={pickup_id}, 区域={pickup_area}({pickup_area_type}区)")
                
                # 2. 根据取货区域类型获取合适的放货库位
                storage_data = self.get_storage_location(pickup_area, pickup_area_type)
                if not storage_data:
                    logging.warning(f"⚠️ 没有找到合适的放货库位")
                    time.sleep(1)
                    continue
                
                storage_id = storage_data['id']
                storage_area = storage_data['area']
                storage_area_type = self.get_area_type(storage_area)
                logging.info(f"🏠 放货库位: ID={storage_id}, 区域={storage_area}({storage_area_type}区)")
                
                # 3. 验证业务规则
                if not self.area_rules[pickup_area_type]['can_pickup']:
                    logging.error(f"❌ 规则验证失败: {pickup_area_type}区不能作为取货区域")
                    continue
                
                if not self.area_rules[storage_area_type]['can_store']:
                    logging.error(f"❌ 规则验证失败: {storage_area_type}区不能作为放货区域")
                    continue
                
                # 特殊规则：暂存区取货只能送往印刷区
                if pickup_area_type == 'buffer' and storage_area_type != 'printing':
                    logging.error(f"❌ 规则验证失败: 暂存区取货只能送往印刷区")
                    continue
                
                # 4. 使用PUT方法发送任务
                success = self.send_task_put(storage_area, pickup_id, storage_id)
                
                if not success:
                    logging.error("❌ 任务发送失败，等待重试")
                else:
                    # 每10个任务打印一次统计信息
                    if task_count % 10 == 0:
                        self.print_statistics()
                
            except Exception as e:
                logging.error(f"💥 执行过程中发生异常: {e}")
            
            # 5. 等待1秒
            logging.info("⏳ 等待1秒后发送下一个任务...")
            time.sleep(1)

if __name__ == "__main__":
    dispatcher = TaskDispatcher()
    if not dispatcher.login_before_run():
        raise SystemExit(1)
    dispatcher.run()
