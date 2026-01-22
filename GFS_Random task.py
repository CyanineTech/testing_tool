import requests
import mysql.connector
import time
import logging
import json
import random
import argparse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('warehouse_task_dispatcher.log'),
        logging.StreamHandler()
    ]
)

class WarehouseTaskDispatcher:
    def __init__(self, weights=None):
        self.db_config = {
            'host': 'ubuntu-180',  # 改为ubuntu-180
            'port': 13306,
            'user': 'root',
            'password': 'wudier**//',
            'database': 'map_server'
        }
        self.api_url = "http://ubuntu-180:9990/dispatch_server/dispatch/start/location_call/task/"
        self.scene_id = 67  # 改为scene_id=67
        
        # 仓库权重配置（默认均匀分布）
        self.warehouse_weights = weights or {'103': 0.333, '102': 0.333, '101': 0.334}
        
        # 定义三大仓库的放货区域
        self.warehouse_rules = {
            '103': {
                'storage_areas': [
                    '1003/2002', '1006/1016', '1018', '1023', '1028', '1029', 
                    '1038/1033', '1040', '1045', '1049', '1054', '1055', '1060', 
                    '1061', '1062', '1064', '1067', '1070', '1072', '1074', 
                    '1078/1075', '1080/1079'
                ],
                'pickup_area': '103'  # 103仓库的取货区域
            },
            '102': {
                'storage_areas': [
                    '5004', '5002', '3001', '1015', '1017', '7001', '1020', 
                    '1026', '1032', '1034', '1035', '1037', '1041', '1042', 
                    '1044', '1048', '1050', '1053', '1065', '1069', '1071', 
                    '1073', '1076', '3002', '1083'
                ],
                'pickup_area': '102'  # 102仓库的取货区域
            },
            '101': {
                'storage_areas': [
                    '3004', '3003', '1001', '1009', '1010', '1011', '1013', 
                    '1014', '1021', '1022', '1024', '1025', '1027', '1030', 
                    '1036', '1039', '1043', '1046', '1056', '1057', '1058', 
                    '1059', '1063', '1066', '1068', '1081', '1086', '1084', '1087'
                ],
                'pickup_area': '101'  # 101仓库的取货区域
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
                ORDER BY RAND() 
                LIMIT 1
            """
            pickup_area = self.warehouse_rules[warehouse_id]['pickup_area']
            cursor.execute(query, (self.scene_id, pickup_area))
            result = cursor.fetchone()
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
        return random.choice(storage_areas)
    
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
            response = requests.put(self.api_url, json=payload, timeout=10)
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
                """
                cursor.execute(query, (self.scene_id, pickup_area))
                result = cursor.fetchone()
                count = result['count'] if result else 0
                logging.info(f"  {warehouse_id}仓库取货区域({pickup_area})库位数量: {count}")
                
                if count == 0:
                    logging.warning(f"⚠️ {warehouse_id}仓库取货区域({pickup_area})没有库位数据!")
            
            # 测试接口连接
            logging.info("🔍 测试接口连接...")
            test_payload = {
                "1": 1,
                "location_id": "pp_69f8d7d8",  # 使用已知的库位ID
                "area": "1023"  # 使用已知的放货区域
            }
            
            try:
                response = requests.put(self.api_url, json=test_payload, timeout=5)
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
            return
        
        task_count = 0
        
        while True:
            try:
                task_count += 1
                logging.info(f"\n📦 准备发送第 {task_count} 个任务...")
                
                # 1. 根据权重选择一个仓库
                warehouse_id = self.get_weighted_warehouse()
                logging.info(f"🏭 选中仓库: {warehouse_id} (权重:{self.warehouse_weights[warehouse_id]*100:.1f}%)")
                
                # 2. 获取该仓库的取货库位
                pickup_data = self.get_pickup_location_for_warehouse(warehouse_id)
                if not pickup_data:
                    logging.warning(f"⚠️ 没有找到{warehouse_id}仓库的取货库位")
                    time.sleep(30)
                    continue
                
                pickup_id = pickup_data['id']
                pickup_area = pickup_data['area']
                logging.info(f"📍 取货库位: ID={pickup_id}, 区域={pickup_area}")
                
                # 3. 随机获取该仓库的一个放货区域
                storage_area = self.get_random_storage_area(warehouse_id)
                if not storage_area:
                    logging.warning(f"⚠️ 没有找到{warehouse_id}仓库的放货区域")
                    time.sleep(30)
                    continue
                
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
            time.sleep(30)

def main():
    """主函数，支持命令行参数"""
    parser = argparse.ArgumentParser(description='仓库任务调度器')
    parser.add_argument('--weights', type=str, help='仓库权重配置，格式：103:0.4,102:0.3,101:0.3')
    
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
            return
    
    # 创建调度器并运行
    dispatcher = WarehouseTaskDispatcher(weights=weights)
    dispatcher.run()

if __name__ == "__main__":
    main()