from __future__ import annotations  # 兼容 Python 3.7+ 类型注解
import configparser
import argparse
import requests
import os
from typing import Optional, Set, Tuple

def read_config_with_comments(config_path: str) -> Tuple[str, configparser.ConfigParser]:
    """
    读取配置文件，同时保留原始内容（含注释）
    返回：(原始文本内容, 解析后的ConfigParser对象)
    """
    # 读取原始文本（保留注释）
    with open(config_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    
    # 解析配置（用于获取配置值）
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    
    return raw_content, config

def get_scene_id(config: configparser.ConfigParser, cli_scene_id: Optional[str]) -> Optional[str]:
    """
    获取scene_id：命令行参数优先级高于配置文件，都没有则返回None
    """
    # 命令行参数存在则优先使用
    if cli_scene_id is not None and cli_scene_id.strip():
        return cli_scene_id.strip()
    
    # 从配置文件[map]段读取
    try:
        config_scene_id = config.get("map", "scene_id", fallback="").strip()
        return config_scene_id if config_scene_id else None
    except configparser.NoSectionError:
        # 不存在[map]段
        return None

def extract_area_prefixes(data_list: list) -> Set[str]:
    """
    从接口返回的data列表中提取alias第一个"-"前的字符（去重）
    """
    area_set = set()
    for item in data_list:
        alias = item.get("alias")
        # 确保alias存在且是有效字符串
        if isinstance(alias, str) and alias.strip():
            # 按第一个"-"分割，取第一部分
            if "-" in alias:
                area_prefix = alias.split("-", 1)[0].strip()
            else:
                area_prefix = alias.strip()
            
            # 过滤空前缀
            if area_prefix:
                area_set.add(area_prefix)
    return area_set

def update_config_with_comments(raw_content: str, areas_str: str) -> str:
    """
    更新配置文件内容（保留原有注释）
    1. 若存在[areas]段，更新areas配置项
    2. 若不存在[areas]段，在文件末尾添加
    """
    lines = raw_content.splitlines()
    section_start_idx = -1
    area_line_idx = -1
    in_areas_section = False
    
    # 遍历查找[areas]段和areas配置项
    for idx, line in enumerate(lines):
        stripped_line = line.strip()
        
        # 检测[areas]段开始
        if stripped_line.startswith("[areas]"):
            section_start_idx = idx
            in_areas_section = True
            continue
        
        # 检测其他段开始（结束当前[areas]段查找）
        if in_areas_section and stripped_line.startswith("[") and stripped_line.endswith("]"):
            in_areas_section = False
            continue
        
        # 在[areas]段内查找areas配置项
        if in_areas_section and stripped_line.lower().startswith("areas"):
            # 匹配 "areas = xxx" 格式（忽略大小写和空格）
            key_part = stripped_line.split("=", 1)[0].strip().lower()
            if key_part == "areas":
                area_line_idx = idx
                break
    
    # 处理更新逻辑
    if section_start_idx != -1:
        # 存在[areas]段
        if area_line_idx != -1:
            # 存在areas配置项，直接替换值
            lines[area_line_idx] = f"areas = {areas_str}"
        else:
            # 不存在areas配置项，在[areas]段末尾添加
            # 找到[areas]段后的第一个非空行（或段结束）
            insert_idx = section_start_idx + 1
            while insert_idx < len(lines):
                if lines[insert_idx].strip().startswith("["):
                    break
                insert_idx += 1
            lines.insert(insert_idx, f"areas = {areas_str}")
    else:
        # 不存在[areas]段，在文件末尾添加
        if lines and not lines[-1].strip():
            # 最后一行是空行，直接添加
            lines.append("[areas]")
            lines.append(f"areas = {areas_str}")
        else:
            # 最后一行非空，先加空行再添加
            lines.append("")
            lines.append("[areas]")
            lines.append(f"areas = {areas_str}")
    
    # 重组文本（保留原有换行格式）
    return "\n".join(lines)

def main():
    # 1. 解析命令行参数（--scene_id可选，优先级高于配置文件）
    parser = argparse.ArgumentParser(description="调用地图接口获取区域别名并写入配置文件（保留注释）")
    parser.add_argument("--scene_id", help="场景ID（优先级高于config.ini的[map]scene_id）")
    args = parser.parse_args()

    # 2. 读取配置文件（保留注释）
    config_path = os.path.join(os.path.dirname(__file__), "config.ini")
    if not os.path.exists(config_path):
        print(f"❌ 错误：配置文件不存在 -> {config_path}")
        return

    try:
        raw_content, config = read_config_with_comments(config_path)
    except Exception as e:
        print(f"❌ 错误：读取配置文件失败 -> {str(e)}")
        return

    # 3. 获取scene_id（命令行>配置文件，都没有则报错）
    scene_id = get_scene_id(config, args.scene_id)
    if not scene_id:
        print("❌ 错误：scene_id缺失！")
        print("  请通过以下两种方式之一提供：")
        print("  1. 命令行参数：--scene_id 场景ID")
        print("  2. 配置文件：在[map]段添加 scene_id = 场景ID")
        return

    # 4. 提取配置项（host、port、token）
    try:
        host = config.get("service", "host").strip()
        port = config.get("service", "port").strip()
        token = config.get("base", "token").strip()
        
        # 校验配置项有效性
        if not host:
            print("❌ 错误：[service]段的host配置不能为空")
            return
        if not port or not port.isdigit():
            print("❌ 错误：[service]段的port配置必须是有效的数字")
            return
        if not token:
            print("❌ 错误：[base]段的token配置不能为空")
            return
    except configparser.NoSectionError as e:
        print(f"❌ 错误：配置文件缺少[{e.section}]配置段")
        return
    except configparser.NoOptionError as e:
        print(f"❌ 错误：[{e.section}]配置段缺少{e.option}配置项")
        return

    # 5. 构建接口请求
    api_url = f"http://{host}:{port}/map_server/locations/?scene_id={scene_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    print(f"🔄 正在调用接口 -> {api_url}")

    # 6. 调用接口
    try:
        response = requests.get(
            url=api_url,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()  # 抛出HTTP错误
    except requests.exceptions.RequestException as e:
        print(f"❌ 错误：接口调用失败 -> {str(e)}")
        return

    # 7. 解析接口返回
    try:
        response_json = response.json()
    except ValueError:
        print(f"❌ 错误：接口返回非JSON格式数据")
        return

    if "data" not in response_json:
        print(f"❌ 错误：接口返回数据缺少'data'字段")
        return

    data_list = response_json["data"]
    if not isinstance(data_list, list):
        print(f"❌ 错误：接口返回'data'字段不是列表类型")
        return

    # 8. 提取区域前缀（去重）
    area_set = extract_area_prefixes(data_list)
    if not area_set:
        print(f"⚠️  警告：未从接口数据中提取到有效区域别名")
        areas_str = ""
    else:
        areas_str = ",".join(sorted(area_set))
        print(f"✅ 成功提取{len(area_set)}个不重复区域：{areas_str}")

    # 9. 更新配置文件（保留注释）
    try:
        updated_content = update_config_with_comments(raw_content, areas_str)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f"✅ 成功写入配置文件 -> {config_path}")
        print(f"📝 [areas]配置：areas = {areas_str}")
    except Exception as e:
        print(f"❌ 错误：写入配置文件失败 -> {str(e)}")
        return

if __name__ == "__main__":
    main()