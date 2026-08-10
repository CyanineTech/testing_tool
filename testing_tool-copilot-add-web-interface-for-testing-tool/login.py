import argparse
import os
import sys
import re
from configparser import ConfigParser, ExtendedInterpolation, DuplicateOptionError
from typing import Optional, List, Tuple

import requests

# 全局配置
URL_PATH = "/user_backend/users/login/"
HEADERS = {"Content-Type": "application/json"}
DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.ini")

# 匹配 token 配置项的正则（支持大小写、前后空格、等号前后空格）
TOKEN_PATTERN = re.compile(r'^\s*token\s*=\s*.*', re.IGNORECASE)


def find_token(obj) -> Optional[str]:
    """递归查找明确的 token 字段或 JWT 字符串。"""
    placeholders = {"", "null", "none"}
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in ("token", "access_token", "jwt", "auth_token", "data"):
                if isinstance(value, str) and value.strip().lower() not in placeholders:
                    return value.strip()
        for value in obj.values():
            if isinstance(value, (dict, list)):
                t = find_token(value)
                if t:
                    return t
    elif isinstance(obj, list):
        for item in obj:
            t = find_token(item)
            if t:
                return t
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("eyJ") and len(s) > 20:
            return s
    return None


def load_config(path: str) -> Tuple[ConfigParser, List[str]]:
    """加载 INI 配置文件，同时返回原始文件内容（用于保留注释）"""
    config = ConfigParser(
        interpolation=ExtendedInterpolation(),
        comment_prefixes=(';', '#'),  # 支持两种注释
        allow_no_value=True,
        empty_lines_in_values=False
    )
    config.optionxform = str  # 保留字段大小写

    original_lines: List[str] = []
    if not os.path.exists(path):
        print(f"❌ 错误：未找到配置文件 '{path}'", file=sys.stderr)
        print("📋 请按以下格式创建配置文件：", file=sys.stderr)
        print("[base]", file=sys.stderr)
        print("# 登录账号", file=sys.stderr)
        print("account = 你的登录账号", file=sys.stderr)
        print("# 登录密码", file=sys.stderr)
        print("password = 你的登录密码", file=sys.stderr)
        print("", file=sys.stderr)
        print("[service]", file=sys.stderr)
        print("# 服务主机/IP地址", file=sys.stderr)
        print("host = 服务地址（如：192.168.1.100 或 localhost）", file=sys.stderr)
        print("# 服务端口号", file=sys.stderr)
        print("port = 服务端口（如：9990，必须是整数）", file=sys.stderr)
        sys.exit(1)

    try:
        # 读取原始文件内容（保留注释和格式）
        with open(path, "r", encoding="utf-8") as f:
            original_lines = f.readlines()
        # 加载配置到 ConfigParser（用于读取值）
        config.read_file(open(path, "r", encoding="utf-8"))
        print(f"✅ 成功加载配置文件：{path}")
    except PermissionError:
        print(f"❌ 错误：没有读取配置文件 '{path}' 的权限，请检查文件权限设置", file=sys.stderr)
        sys.exit(1)
    except UnicodeDecodeError:
        print(f"❌ 错误：配置文件 '{path}' 编码格式错误，请使用 UTF-8 编码", file=sys.stderr)
        sys.exit(1)
    except DuplicateOptionError as e:
        # 专门处理重复配置项错误（如重复的 token=）
        print(f"❌ 错误：配置文件格式错误", file=sys.stderr)
        print(f"📝 具体原因：在 [{e.section}] 配置段中，'{e.option}' 配置项重复出现（第 {e.lineno} 行）", file=sys.stderr)
        print(f"💡 修复建议：删除重复的 '{e.option}=' 配置项，确保每个配置项在同一 section 中只出现一次", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_msg = str(e)
        # 针对常见的 INI 格式错误进行更精准的提示
        if "option" in error_msg and "already exists" in error_msg:
            print(f"❌ 错误：配置文件格式错误 - 存在重复的配置项", file=sys.stderr)
            print(f"📝 错误详情：{error_msg}", file=sys.stderr)
            print(f"💡 修复建议：检查配置文件，确保每个配置项在同一 section 中只出现一次", file=sys.stderr)
        else:
            print(f"❌ 错误：读取配置文件失败 - {error_msg}", file=sys.stderr)
            print("💡 可能原因：文件格式损坏、配置项格式错误（如等号前后有特殊字符）", file=sys.stderr)
        sys.exit(1)

    return config, original_lines


def save_token_to_config(path: str, token: str, original_lines: List[str]) -> None:
    """手动修改原始文件内容，精准更新 token（不新增重复项），保留注释和格式"""
    try:
        # 标记是否找到并更新了 token
        token_updated = False
        # 标记是否找到 [base] section
        base_section_found = False
        # 新的文件内容
        new_lines: List[str] = []

        for line in original_lines:
            stripped_line = line.strip()
            
            # 检查是否是 [base] section
            if stripped_line.startswith("[base]"):
                base_section_found = True
                new_lines.append(line)
                continue
            
            # 如果在 [base] section 内
            if base_section_found:
                # 匹配 token 配置项（支持大小写、前后空格）
                if TOKEN_PATTERN.match(line):
                    if not token_updated:
                        # 第一次找到 token：更新值，保留原有注释
                        comment_index = line.find(';')
                        if comment_index != -1:
                            # 保留注释部分
                            prefix = line[:comment_index].split('=', 1)[0].strip()  # 保留原始的字段名大小写（如 Token/TOKEN）
                            new_line = f"{prefix} = {token} {line[comment_index:]}"
                        else:
                            # 无注释：保持字段名大小写，只更新值
                            prefix = line.split('=', 1)[0].strip()
                            new_line = f"{prefix} = {token}\n"
                        new_lines.append(new_line)
                        token_updated = True
                        print(f"📝 已更新 [base] 段中的 token 配置")
                    else:
                        # 后续重复的 token 配置：跳过（避免重复）
                        print(f"⚠️  跳过重复的 token 配置项：{line.strip()}", file=sys.stderr)
                    continue
            
            # 非 token 行直接保留
            new_lines.append(line)

        # 如果 [base] section 存在但没有 token，在 [base] 内添加 token
        if base_section_found and not token_updated:
            print(f"📝 [base] 段中未找到现有 token，将新增配置")
            # 找到 [base] 后的第一个合适位置插入 token
            inserted = False
            for i in range(len(new_lines)):
                line = new_lines[i]
                stripped_line = line.strip()
                if stripped_line.startswith("[base]"):
                    # 从下一行开始查找插入位置（空行、注释或其他 section 前）
                    for j in range(i + 1, len(new_lines)):
                        next_line = new_lines[j]
                        next_stripped = next_line.strip()
                        if (not next_stripped) or next_stripped.startswith((';', '#', '[')):
                            # 插入到当前位置，保持格式一致
                            new_lines.insert(j, f"token = {token}  ; 自动生成的登录令牌\n")
                            inserted = True
                            break
                    # 如果 [base] 后没有其他内容，直接添加到末尾
                    if not inserted:
                        new_lines.append(f"\ntoken = {token}  ; 自动生成的登录令牌\n")
                    inserted = True
                    break

        # 如果没有 [base] section（理论上不会走到这里，因为前面已校验）
        if not base_section_found:
            new_lines.append("\n[base]\n")
            new_lines.append(f"token = {token}  ; 自动生成的登录令牌\n")

        # 写入文件（保留原始格式和注释）
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        
        print(f"✅ token 已成功保存到 {path}（原有注释和格式已保留）")
    except PermissionError:
        print(f"❌ 错误：没有写入配置文件 '{path}' 的权限，请检查文件权限设置", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误：写入 token 到配置文件失败 - {str(e)}", file=sys.stderr)
        sys.exit(1)


def do_login(host: str, port: int, account: str, password: str, timeout: int = 10) -> str:
    """执行登录请求"""
    url = f"http://{host}:{port}{URL_PATH}"
    payload = {"account": account, "password": password}
    try:
        print(f"📡 正在向 {url} 发送登录请求...")
        resp = requests.put(url, json=payload, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"❌ 错误：无法连接到服务 {host}:{port}", file=sys.stderr)
        print("💡 请检查：", file=sys.stderr)
        print("  1. 服务主机地址是否正确", file=sys.stderr)
        print("  2. 服务端口是否开放", file=sys.stderr)
        print("  3. 网络是否通畅", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.Timeout:
        print(f"❌ 错误：登录请求超时（{timeout} 秒）", file=sys.stderr)
        print("💡 建议：检查服务是否正常运行，或增加超时时间", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ 错误：登录请求失败 - {str(e)}", file=sys.stderr)
        sys.exit(1)

    try:
        data = resp.json()
    except ValueError:
        print(f"❌ 错误：服务响应不是有效的 JSON 格式", file=sys.stderr)
        print(f"📝 状态码：{resp.status_code}", file=sys.stderr)
        print(f"📝 响应内容预览：{resp.text[:100]}...", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict) and data.get("success") is False:
        print(f"❌ 登录业务失败：{data}", file=sys.stderr)
        sys.exit(1)

    token = find_token(data)
    if not token:
        print(f"❌ 错误：登录成功，但未从响应中找到有效的 token", file=sys.stderr)
        print(f"📝 服务响应内容：{data}", file=sys.stderr)
        sys.exit(1)
    return token


def main() -> None:
    """主函数：读取配置并执行登录"""
    parser = argparse.ArgumentParser(description="登录服务并将 token 写入配置文件（支持中文错误提示）")
    parser.add_argument("--host", default=None, help="服务主机/IP（覆盖配置文件中的 service.host）")
    parser.add_argument("--port", default=None, type=int, help="服务端口（覆盖配置文件中的 service.port）")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help=f"配置文件路径（默认: {DEFAULT_CONFIG_PATH}）")
    parser.add_argument("--account", default=None, help="登录账号（覆盖配置文件中的 base.account）")
    parser.add_argument("--password", default=None, help="登录密码（覆盖配置文件中的 base.password）")
    args = parser.parse_args()

    # 1. 加载配置文件和原始内容
    config, original_lines = load_config(args.config)

    # 2. 校验 [service] section
    if not config.has_section("service"):
        print(f"❌ 错误：配置文件中缺少 '[service]' 配置段", file=sys.stderr)
        print("💡 请在配置文件中添加：", file=sys.stderr)
        print("[service]", file=sys.stderr)
        print("host = 服务地址（如：192.168.1.100）", file=sys.stderr)
        print("port = 服务端口（如：9990）", file=sys.stderr)
        sys.exit(1)

    # 3. 获取服务主机
    host: str
    if args.host is not None:
        host = args.host.strip()
        if not host:
            print(f"❌ 错误：命令行参数 --host 不能为空", file=sys.stderr)
            sys.exit(1)
        print(f"📌 服务主机：{host}（来自命令行参数）")
    else:
        if not config.has_option("service", "host"):
            print(f"❌ 错误：配置文件的 [service] 段中缺少 'host' 配置项", file=sys.stderr)
            print("💡 请在 [service] 段中添加：host = 服务地址（如：192.168.1.100）", file=sys.stderr)
            sys.exit(1)
        
        host = config.get("service", "host").strip()
        if not host:
            print(f"❌ 错误：配置文件 [service] 段中的 'host' 配置为空", file=sys.stderr)
            print("💡 请设置有效的服务主机地址（如：192.168.1.100 或 localhost）", file=sys.stderr)
            sys.exit(1)
        print(f"📌 服务主机：{host}（来自配置文件）")

    # 4. 获取服务端口（优化后的友好提示）
    port: int
    if args.port is not None:
        if args.port <= 0 or args.port > 65535:
            print(f"❌ 错误：命令行参数 --port 无效（{args.port}）", file=sys.stderr)
            print("💡 端口号必须是 1-65535 之间的整数", file=sys.stderr)
            sys.exit(1)
        port = args.port
        print(f"📌 服务端口：{port}（来自命令行参数）")
    else:
        # 分三种情况：1. 没有 port 配置项 2. port 配置为空 3. port 格式错误
        if not config.has_option("service", "port"):
            print(f"❌ 错误：配置文件的 [service] 段中缺少 'port' 配置项", file=sys.stderr)
            print("📋 示例配置：", file=sys.stderr)
            print("[service]", file=sys.stderr)
            print("  host = 192.168.1.100", file=sys.stderr)
            print("  port = 9990  ; 请设置 1-65535 之间的整数", file=sys.stderr)
            print("💡 修复建议：在 [service] 段中添加 port 配置，值为服务的端口号", file=sys.stderr)
            sys.exit(1)
        
        port_str = config.get("service", "port").strip()
        if not port_str:
            print(f"❌ 错误：配置文件 [service] 段中的 'port' 配置为空", file=sys.stderr)
            print("📝 当前配置：port = （为空）", file=sys.stderr)
            print("💡 修复建议：将 port 配置改为有效的端口号（如：port = 9990）", file=sys.stderr)
            sys.exit(1)
        
        try:
            port = int(port_str)
            if port <= 0 or port > 65535:
                print(f"❌ 错误：配置文件 [service] 段中的 'port' 配置无效（{port}）", file=sys.stderr)
                print("💡 端口号必须是 1-65535 之间的整数（有效端口范围）", file=sys.stderr)
                print("📋 正确示例：port = 9990 或 port = 8080", file=sys.stderr)
                sys.exit(1)
            print(f"📌 服务端口：{port}（来自配置文件）")
        except ValueError:
            print(f"❌ 错误：配置文件 [service] 段中的 'port' 格式错误", file=sys.stderr)
            print(f"📝 当前配置：port = {port_str}", file=sys.stderr)
            print("💡 修复建议：port 必须是整数（如：9990），不能包含字母、符号或空格", file=sys.stderr)
            sys.exit(1)

    # 5. 校验 [base] section
    if not config.has_section("base"):
        print(f"❌ 错误：配置文件中缺少 '[base]' 配置段", file=sys.stderr)
        print("💡 请在配置文件中添加：", file=sys.stderr)
        print("[base]", file=sys.stderr)
        print("account = 你的登录账号", file=sys.stderr)
        print("password = 你的登录密码", file=sys.stderr)
        sys.exit(1)

    # 6. 获取账号密码
    account: str
    if args.account is not None:
        account = args.account.strip()
        if not account:
            print(f"❌ 错误：命令行参数 --account 不能为空", file=sys.stderr)
            sys.exit(1)
        account_source = "命令行参数"
    else:
        if not config.has_option("base", "account"):
            print(f"❌ 错误：配置文件的 [base] 段中缺少 'account' 配置项", file=sys.stderr)
            print("💡 请在 [base] 段中添加：account = 你的登录账号", file=sys.stderr)
            sys.exit(1)
        
        account = config.get("base", "account").strip()
        if not account:
            print(f"❌ 错误：配置文件 [base] 段中的 'account' 配置为空", file=sys.stderr)
            print("💡 请设置有效的登录账号", file=sys.stderr)
            sys.exit(1)
        account_source = "配置文件"

    password: str
    if args.password is not None:
        password = args.password.strip()
        if not password:
            print(f"❌ 错误：命令行参数 --password 不能为空", file=sys.stderr)
            sys.exit(1)
        password_source = "命令行参数"
    else:
        if not config.has_option("base", "password"):
            print(f"❌ 错误：配置文件的 [base] 段中缺少 'password' 配置项", file=sys.stderr)
            print("💡 请在 [base] 段中添加：password = 你的登录密码", file=sys.stderr)
            sys.exit(1)
        
        password = config.get("base", "password").strip()
        if not password:
            print(f"❌ 错误：配置文件 [base] 段中的 'password' 配置为空", file=sys.stderr)
            print("💡 请设置有效的登录密码", file=sys.stderr)
            sys.exit(1)
        password_source = "配置文件"

    print(f"📌 登录账号：{account}（来自{account_source}）")
    print(f"📌 登录密码：{'*' * len(password)}（来自{password_source}）")

    # 7. 执行登录并保存 token
    token = do_login(host, port, account, password)
    print(f"📌 token 预览：{token[:20]}...")
    save_token_to_config(args.config, token, original_lines)

    # 最终成功提示
    print("\n🎉 登录成功！token 已成功更新到配置文件，原有注释和格式完全保留")


if __name__ == "__main__":
    main()
