| 文件/脚本                | 核心功能                                                                 |
|-------------------------|--------------------------------------------------------------------------|
| `Download.py`              | 日志打包下载工具        |
## 一、任务自动发布脚本工具集概述
本工具集是面向仓储物流场景的自动化任务调用工具，核心实现两类核心任务：
1. **货物库位至放货区域位移任务（lift_cargo_to_zone.py）**：向dispatch接口批量提交“库位→放货区域”货物位移任务
2. **区域取货到提升机任务（region_pickup_to_lift_task.py）**：按指定规则执行“区域取货→提升机”任务
配套提供登录认证（login.py）、区域信息获取（get_area.py）、库位信息获取（get_Location_info.py）等辅助能力，所有模块依赖统一的config.ini配置文件，需按固定流程执行前置步骤后再运行核心脚本。

### 核心文件功能映射
| 文件/脚本                | 核心功能                                                                 |
|-------------------------|--------------------------------------------------------------------------|
| `login.py`              | 登录认证模块，加载配置文件、校验配置合法性，获取/更新接口访问Token        |
| `get_area.py`           | 区域信息获取模块，调用地图接口解析区域信息，自动更新config.ini的区域配置  |
| `get_Location_info.py`  | 库位信息获取模块，专用于区域取货任务，解析并验证目标库位的有效性          |
| `lift_cargo_to_zone.py` | 货物位移任务模块，向dispatch接口批量提交“库位→放货区域”货物位移任务       |
| `region_pickup_to_lift_task.py` | 区域取货任务模块，按指定规则（顺序/随机）执行“区域取货→提升机”任务      |
| `config.ini`            | 核心配置文件，存储所有模块的认证、服务、业务、日志等配置项（所有模块共用）|

## 二、环境准备（通用）
### 1. 环境要求
Python 3.7及以上版本

### 2. 依赖安装
打开命令行，进入工具集目录，执行以下命令安装通用依赖：
```bash
pip install requests openpyxl urllib3 configparser
```

### 3. 前置文件准备
| 文件类型       | 要求                                                                 |
|----------------|----------------------------------------------------------------------|
| 配置文件       | 必须创建`config.ini`，按要求填写基础认证/服务配置（见下文配置说明）     |
| Excel数据文件  | （仅region_pickup_to_lift_task.py需准备）包含库位信息（必填列：`id`（库位ID）、`alias_kept`（区域信息）），格式为.xlsx/.xlsm |

## 三、核心配置文件（config.ini）完整说明
配置文件为所有模块共用，需与脚本放在同一目录，以下为全量配置项（必填项标注★，选填项标注○）：

```ini
[base]
account = 你的账号          ★ 所有模块通用，登录认证用
password = 你的密码        ★ 所有模块通用，登录认证用
token = 认证令牌           ★ 所有模块通用，接口访问令牌（login.py自动更新）

[service]
host = 接口主机地址        ★ 所有模块通用，如：192.168.1.100
port = 接口端口            ★ 所有模块通用，如：8080

[map]
scene_id = 场景ID          ★ get_area/get_Location_info/区域取货任务专用，系统分配的数字

[business]
rule = 执行规则            ★ 区域取货任务专用，1=单个区域顺序；2=多个区域随机
areas = 目标区域           ★ 区域取货任务专用，多个用逗号分隔（规则1仅填1个）
fixed_store = 固定目标store ○ 区域取货任务专用，不填则随机选择

[task]
locations = 可选store列表  ★ 通用，多个用逗号分隔（如：pp_6c88f5f6,pp_6e0dff0c）
tasks-per-location = 40    ○ 货物位移任务专用，每个库位每小时任务数（默认40）

[excel]
xlsx_path = Excel文件路径  ★ 区域取货任务专用，如：./data.xlsx
sheet_name = 工作表名称    ○ 区域取货任务专用，默认最后一个工作表

[request]
timeout = 30               ○ 货物位移任务专用，请求超时时间（秒，默认30）
retry_count = 2            ○ 货物位移任务专用，失败重试次数（默认2）
retry_delay = 1            ○ 货物位移任务专用，重试延迟时间（秒，默认1）

[log]
debug = true/false         ★ 通用，是否开启调试模式（输出详细日志）
log_file = ./task_log.log  ★ 通用，日志文件存储路径
```

## 四、核心脚本执行流程（关键修正）
### 流程总览
| 核心脚本                     | 前置执行步骤                                                                 |
|------------------------------|------------------------------------------------------------------------------|
| lift_cargo_to_zone.py        | 1. 修改config.ini基础配置 → 2. 执行login.py → 3. 执行get_area.py → 4. 执行本脚本 |
| region_pickup_to_lift_task.py| 1. 修改config.ini基础配置 → 2. 执行login.py → 3. 执行get_Location_info.py → 4. 执行本脚本 |

### 通用前置步骤：修改config.ini基础配置
打开config.ini文件，填写以下核心必填项（所有流程第一步）：
```ini
[base]
account = 你的实际登录账号
password = 你的实际登录密码

[service]
host = 实际接口主机地址（如192.168.1.100）
port = 实际接口端口（如8080）

[map]
scene_id = 系统分配的场景ID（数字）

[log]
debug = true （调试阶段建议开启）
log_file = ./task_log.log
```

### 流程1：执行货物位移任务（lift_cargo_to_zone.py）
#### 步骤1：执行登录认证（login.py）
功能：校验账号密码、自动获取并更新config.ini中的token字段（核心前置，无有效token后续接口调用失败）
```bash
# 基础运行（自动读取同目录config.ini）
python login.py

# 若配置文件不在同目录，指定路径
python login.py --config ./my_config.ini
```
✅ 成功标志：控制台输出“✅ token 已成功保存到 config.ini”，且config.ini的[base]段token字段已填充。

#### 步骤2：执行区域信息获取（get_area.py）
功能：调用地图接口获取有效区域列表，自动更新config.ini的[business]段areas配置（为位移任务提供合法区域）
```bash
# 基础运行（使用config.ini的scene_id）
python get_area.py

# 若需临时指定scene_id（优先级更高）
python get_area.py --scene_id 你的场景ID
```
✅ 成功标志：控制台输出“✅ 成功提取X个不重复区域”+“✅ 成功写入配置文件”。

#### 步骤3：执行货物位移任务（lift_cargo_to_zone.py）
功能：批量提交“库位→放货区域”位移任务，支持总任务数/时长两种运行模式
```bash
# 基础运行（读取config.ini全配置）
python lift_cargo_to_zone.py

# 常用自定义参数示例
python lift_cargo_to_zone.py --total-tasks 1000  # 指定总任务数
python lift_cargo_to_zone.py --hours 2.5         # 指定运行时长（2.5小时）
python lift_cargo_to_zone.py --debug             # 开启调试日志
```

### 流程2：执行区域取货到提升机任务（region_pickup_to_lift_task.py）
#### 步骤1：执行登录认证（login.py）
同“流程1-步骤1”，确保token有效：
```bash
python login.py
```

#### 步骤2：执行库位信息获取（get_Location_info.py）
功能：专用于区域取货任务，验证目标库位有效性，生成合法的store列表并更新config.ini的[task]段locations配置
```bash
# 基础运行
python get_Location_info.py

# 调试模式运行
python get_Location_info.py --debug
```
✅ 成功标志：控制台输出“✅ 已获取有效库位列表：xxx”，且config.ini的[task]段locations字段已填充。

#### 步骤3：补充区域取货任务专属配置（可选）
若需自定义执行规则，修改config.ini的[business]段：
```ini
[business]
rule = 2 （1=单个区域顺序，2=多个区域随机）
areas = area1,area2 （多个区域用逗号分隔，规则1仅填1个）
fixed_store = pp_6c88f5f6 （可选，固定目标store）
```
同时补充Excel文件配置（若使用）：
```ini
[excel]
xlsx_path = ./data.xlsx （你的库位Excel文件路径）
sheet_name = Sheet1 （可选，默认最后一个工作表）
```

#### 步骤4：执行区域取货任务（region_pickup_to_lift_task.py）
```bash
# 基础运行（读取config.ini配置）
python region_pickup_to_lift_task.py

# 命令行覆盖配置示例（优先级高于config.ini）
python region_pickup_to_lift_task.py --rule 2 --areas area1 area2 --debug
python region_pickup_to_lift_task.py --fixed-store pp_6c88f5f6
```

## 五、核心功能详细说明
### 1. 登录认证模块（login.py）
#### 核心逻辑
- 加载config.ini的[base]段账号密码，调用登录接口获取token
- 自动将token写入config.ini的[base]段（保留原有注释和格式）
- 校验token有效性，若过期则重新获取并更新

#### 异常处理
- 配置文件不存在：控制台提示创建模板格式
- 账号密码错误：输出“登录失败”并提示检查账号密码
- 无写入权限：提示“没有写入配置文件的权限”，需检查文件权限

### 2. 区域信息获取模块（get_area.py）
#### 核心逻辑
- 读取config.ini的host/port/token/scene_id，调用地图接口获取区域数据
- 解析接口返回的区域别名，去重后更新config.ini的[business]段areas字段
- 保留config.ini原有注释和格式，仅更新目标配置项

#### 异常处理
- scene_id缺失：提示“通过--scene_id参数或[map]段配置scene_id”
- 接口调用失败：提示“检查host/port是否正确、网络是否通畅、token是否有效”

### 3. 库位信息获取模块（get_Location_info.py）
#### 核心逻辑
- 基于scene_id和token调用库位接口，获取所有有效store（库位）列表
- 验证store格式合法性，过滤无效库位
- 自动更新config.ini的[task]段locations字段（多个用逗号分隔）

#### 异常处理
- 库位列表为空：提示“该场景ID下无有效库位，请检查scene_id或接口配置”
- 接口返回格式错误：提示“接口返回非JSON格式，检查服务状态”

### 4. 货物位移任务模块（lift_cargo_to_zone.py）
#### 运行策略（二选一）
- 总任务数模式：`--total-tasks 1000`，完成1000个任务后退出
- 时长模式：`--hours 2.5`，持续运行2.5小时后退出（默认1小时）

#### 失败保护
- 单请求超时重试：默认超时30秒，失败重试2次，每次延迟1秒
- 连续失败保护：连续5次接口调用失败后自动停止，避免无效请求

### 5. 区域取货任务模块（region_pickup_to_lift_task.py）
#### 执行规则（核心）
| 规则编号 | 适用场景                | 执行逻辑                                                                 |
|----------|-------------------------|--------------------------------------------------------------------------|
| 1        | 单个区域顺序执行        | 仅填1个区域，按Excel中该区域库位编号升序执行；Store可选固定/随机          |
| 2        | 多个区域随机执行        | 填2+个区域，随机选区域后按顺序取未执行库位；Store可选固定/随机（避免区域拥堵） |

#### 成功/失败判定
- 成功：接口返回`success=true` 或 `error_id=50421021`
- 失败：HTTP请求错误、接口返回其他error_id、超时等
- 连续5次失败：程序自动停止，控制台输出失败原因统计

## 六、常见问题解决
### 1. 登录相关问题
- 报错“无法连接到服务host:port”：检查host/port是否正确、服务是否启动、网络是否互通
- 报错“token更新失败”：检查账号密码是否正确，或联系管理员重置账号

### 2. 区域/库位获取相关问题
- 报错“scene_id缺失”：在config.ini的[map]段填写scene_id，或执行时加--scene_id参数
- 报错“未提取到有效区域/库位”：检查scene_id是否正确，或该场景下是否有配置区域/库位

### 3. 核心任务执行问题
- 报错“配置文件缺少必填项”：按config.ini模板补全[base][service][map]等段的必填项
- 连续5次失败停止：检查token是否过期、库位ID是否有效、接口服务是否正常
- Excel相关报错：检查xlsx_path路径是否正确，Excel是否包含id和alias_kept列
- 日志无输出：检查log_file路径是否有写入权限，debug是否设为true

### 4. 中断任务处理
运行中按`Ctrl+C`可优雅中断任务，程序会输出：
- 任务执行总时长
- 成功/失败次数及成功率
- 最终连续失败次数
- 区域/库位使用统计

## 七、注意事项
1. 配置文件优先级：命令行参数 > config.ini配置 > 硬编码默认值，需注意参数覆盖逻辑
2. 压力测试建议：先使用少量任务数（如--total-tasks 10）验证配置正确性，再批量运行
3. Token有效期：token存在过期机制，若频繁认证失败，重新执行login.py更新token
4. 日志管理：日志文件会持续追加，定期清理（如log_file指定的task_log.log）避免文件过大
5. 权限要求：运行脚本的用户需有config.ini和日志文件的读写权限，Excel文件的读取权限
