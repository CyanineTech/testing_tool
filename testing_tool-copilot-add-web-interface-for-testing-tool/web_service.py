#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web Service for Testing Tool
提供Web界面来管理和执行testing_tool中的Python脚本
"""

import os
import sys
import json
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from collections import deque
from configparser import ConfigParser


def _print_missing_dependency_help(missing_module: str) -> None:
    msg = (
        "\n缺少Python依赖: {missing}\n"
        "请在项目根目录执行（确保用的是同一个 python3）：\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  python3 -m pip install -U pip\n"
        "  python3 -m pip install -r requirements.txt\n\n"
        "如果你不想用venv，也至少执行：\n"
        "  python3 -m pip install -r requirements.txt\n"
    ).format(missing=missing_module)
    print(msg, file=sys.stderr)


try:
    from flask import Flask, render_template, request, jsonify, send_file, Response
except ModuleNotFoundError as e:
    _print_missing_dependency_help(getattr(e, "name", "flask"))
    raise

try:
    from flask_cors import CORS
except ModuleNotFoundError as e:
    _print_missing_dependency_help(getattr(e, "name", "flask_cors"))
    raise
import queue

app = Flask(__name__)
CORS(app)

# 全局配置
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
SCRIPTS_DIR = BASE_DIR
LOGS_DIR = BASE_DIR
LOG_SOURCE_DIRS = (LOGS_DIR, SCRIPTS_DIR)
DESCRIPTIONS_FILE = BASE_DIR / "script_descriptions.json"

# 全局变量，用于存储运行中的进程
running_processes = {}
process_lock = threading.Lock()
MAX_OUTPUT_BUFFER_LINES = 2000
MAX_OUTPUT_QUEUE_LINES = 2000
PROCESS_RETENTION_SECONDS = 10 * 60


def cleanup_finished_processes() -> None:
    cutoff = time.time() - PROCESS_RETENTION_SECONDS
    with process_lock:
        stale_ids = [
            process_id for process_id, info in running_processes.items()
            if info.get('finished_at')
            and info['finished_at'] < cutoff
            and info['process'].poll() is not None
        ]
        for process_id in stale_ids:
            running_processes.pop(process_id, None)


def process_reaper() -> None:
    while True:
        time.sleep(60)
        cleanup_finished_processes()

# 脚本描述数据
script_descriptions = {}


def prune_missing_scripts(save: bool = True) -> dict:
    """从 script_descriptions 中移除磁盘上已不存在的脚本。

    说明：以前版本会“保留已删除脚本（前端仍可见）”。现在默认改为不展示也不保留，
    避免误点运行造成困扰。

    返回：{"removed": int, "total": int}
    """
    global script_descriptions

    removed = 0
    changed = False

    for script_name, meta in list(script_descriptions.items()):
        stored_path = meta.get("path") if isinstance(meta, dict) else None
        resolved = resolve_script_path(script_name, stored_path)
        if resolved is None:
            script_descriptions.pop(script_name, None)
            removed += 1
            changed = True

    if changed and save:
        save_script_descriptions()

    return {"removed": removed, "total": len(script_descriptions)}


def scan_and_merge_scripts(save: bool = True) -> dict:
    """扫描脚本目录并合并到script_descriptions。

    - 新脚本：自动加入（避免必须删script_descriptions.json或重启服务）
    - 已有脚本：保留description/workflow，仅更新path/name
    - 被删除的脚本：默认清理（不再展示）

    返回：{"added": int, "total": int}
    """
    global script_descriptions

    discovered = discover_scripts()
    added = 0
    changed = False

    for script_name, meta in discovered.items():
        if script_name not in script_descriptions:
            script_descriptions[script_name] = meta
            added += 1
            changed = True
            continue

        existing = script_descriptions.get(script_name)
        if not isinstance(existing, dict):
            script_descriptions[script_name] = meta
            changed = True
            continue

        resolved = resolve_script_path(script_name, existing.get("path"))
        if resolved is not None:
            normalized = str(resolved)
            if existing.get("path") != normalized:
                existing["path"] = normalized
                changed = True

        if existing.get("name") != script_name:
            existing["name"] = script_name
            changed = True

    if changed and save:
        save_script_descriptions()

    prune_result = prune_missing_scripts(save=save)
    return {"added": added, "removed": prune_result["removed"], "total": len(script_descriptions)}


def resolve_script_path(script_name: str, stored_path: Optional[str] = None) -> Optional[Path]:
    """Resolve a script path in a portable and safe way.

    Preference order:
    1) Use stored_path if it exists.
    2) Fall back to a file with the same name under SCRIPTS_DIR.
    """
    candidates: List[Path] = []
    if stored_path:
        candidates.append(Path(stored_path))

    candidates.append(SCRIPTS_DIR / script_name)

    for candidate in candidates:
        try:
            candidate_resolved = candidate.expanduser().resolve()
        except Exception:
            continue

        # Only allow files, and avoid accidental directory traversal.
        if candidate_resolved.is_file() and candidate_resolved.name == script_name:
            return candidate_resolved

    return None


def load_script_descriptions():
    """加载脚本描述"""
    global script_descriptions
    if DESCRIPTIONS_FILE.exists():
        try:
            with open(DESCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                script_descriptions = json.load(f)
        except Exception:
            script_descriptions = {}

    if not script_descriptions:
        script_descriptions = discover_scripts()
        save_script_descriptions()
        return

    # 修正旧环境中写死的绝对路径（例如 /home/office/...）
    changed = False
    for script_name, meta in list(script_descriptions.items()):
        if not isinstance(meta, dict):
            script_descriptions[script_name] = {
                "name": script_name,
                "description": str(meta),
                "workflow": "",
                "path": str(SCRIPTS_DIR / script_name),
            }
            changed = True
            continue

        stored_path = meta.get('path')
        resolved = resolve_script_path(script_name, stored_path)
        if resolved is None:
            # 如果磁盘上没有该脚本，则保持原样（前端仍可显示，但执行时会报错）
            continue

        normalized = str(resolved)
        if meta.get('path') != normalized:
            meta['path'] = normalized
            changed = True

        if meta.get('name') != script_name:
            meta['name'] = script_name
            changed = True

    if changed:
        save_script_descriptions()

    # 关键：即使script_descriptions.json存在，也需要把目录中新增脚本合并进来
    scan_and_merge_scripts(save=True)
    prune_missing_scripts(save=True)


def save_script_descriptions():
    """保存脚本描述"""
    with open(DESCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(script_descriptions, f, ensure_ascii=False, indent=2)


def discover_scripts():
    """扫描目录中的Python脚本并生成描述"""
    scripts = {}
    for file in SCRIPTS_DIR.glob("*.py"):
        if file.name == "web_service.py":
            continue
        
        script_name = file.name
        # 尝试从文件中提取描述
        description = ""
        workflow = ""
        
        try:
            with open(file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # 查找文档字符串
                in_docstring = False
                docstring_lines = []
                for line in lines[:50]:  # 只读前50行
                    if '"""' in line or "'''" in line:
                        if in_docstring:
                            break
                        in_docstring = True
                        docstring_lines.append(line)
                    elif in_docstring:
                        docstring_lines.append(line)
                
                if docstring_lines:
                    description = ''.join(docstring_lines).strip('"\' \n')
                else:
                    description = f"Python脚本: {script_name}"
        except Exception:
            description = f"Python脚本: {script_name}"
        
        scripts[script_name] = {
            "name": script_name,
            "description": description,
            "workflow": workflow,
            "path": str(file)
        }
    
    return scripts


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/scripts')
def get_scripts():
    """获取所有脚本列表"""
    refresh = str(request.args.get("refresh", "0")).strip().lower() in ("1", "true", "yes", "on")
    include_missing = str(request.args.get("include_missing", "0")).strip().lower() in ("1", "true", "yes", "on")
    if refresh:
        scan_and_merge_scripts(save=True)
    if include_missing:
        # 兼容调试：返回原始记录（不保证存在）
        return jsonify(script_descriptions)

    # 默认：仅返回磁盘存在的脚本
    filtered = {}
    for script_name, meta in script_descriptions.items():
        stored_path = meta.get("path") if isinstance(meta, dict) else None
        if resolve_script_path(script_name, stored_path) is not None:
            filtered[script_name] = meta
    return jsonify(filtered)


@app.route('/api/scripts/refresh', methods=['POST'])
def refresh_scripts():
    """强制重新扫描目录并刷新脚本列表"""
    result = scan_and_merge_scripts(save=True)
    return jsonify({"status": "success", "message": "脚本列表已刷新", **result})


@app.route('/api/scripts/<script_name>', methods=['GET', 'PUT'])
def manage_script(script_name):
    """获取或更新脚本信息"""
    if request.method == 'GET':
        script = script_descriptions.get(script_name, {})
        return jsonify(script)
    
    elif request.method == 'PUT':
        data = request.json
        if script_name in script_descriptions:
            script_descriptions[script_name]['description'] = data.get('description', '')
            script_descriptions[script_name]['workflow'] = data.get('workflow', '')
            save_script_descriptions()
            return jsonify({"status": "success", "message": "脚本信息已更新"})
        return jsonify({"status": "error", "message": "脚本不存在"}), 404


@app.route('/api/config', methods=['GET', 'PUT'])
def manage_config():
    """获取或更新配置文件"""
    if request.method == 'GET':
        try:
            config = ConfigParser()
            config.read(CONFIG_FILE, encoding='utf-8')
            
            # 将配置转换为字典
            config_dict = {}
            for section in config.sections():
                config_dict[section] = dict(config.items(section))
            
            return jsonify(config_dict)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    
    elif request.method == 'PUT':
        try:
            data = request.json
            config = ConfigParser()
            
            # 构建新配置
            for section, options in data.items():
                config.add_section(section)
                for key, value in options.items():
                    config.set(section, key, str(value))
            
            # 保存配置
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            
            return jsonify({"status": "success", "message": "配置已保存"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/execute/<script_name>', methods=['POST'])
def execute_script(script_name):
    """执行脚本"""
    if script_name not in script_descriptions:
        return jsonify({"status": "error", "message": "脚本不存在"}), 404
    
    data = request.json or {}
    args = data.get('args', [])
    
    stored_path = script_descriptions.get(script_name, {}).get('path')
    resolved = resolve_script_path(script_name, stored_path)
    if resolved is None:
        return jsonify({
            "status": "error",
            "message": f"脚本文件不存在: {script_name}（当前脚本目录: {SCRIPTS_DIR}）"
        }), 404

    script_path = str(resolved)
    
    # 生成唯一的进程ID
    cleanup_finished_processes()
    process_id = f"{script_name}_{uuid.uuid4().hex}"
    
    try:
        # 构建命令
        cmd = [sys.executable, script_path] + args
        
        # 启动进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=str(SCRIPTS_DIR)
        )
        
        # 保存进程信息
        with process_lock:
            running_processes[process_id] = {
                'process': process,
                'script_name': script_name,
                'start_time': datetime.now(),
                'output_queue': queue.Queue(maxsize=MAX_OUTPUT_QUEUE_LINES),
                'output_buffer': deque(maxlen=MAX_OUTPUT_BUFFER_LINES)
            }
        
        # 启动线程读取输出
        def read_output(proc, output_queue):
            try:
                for line in proc.stdout:
                    try:
                        output_queue.put_nowait(line)
                    except queue.Full:
                        try:
                            output_queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            output_queue.put_nowait(line)
                        except queue.Full:
                            pass
            except Exception:
                pass
            finally:
                proc.wait()
                with process_lock:
                    for info in running_processes.values():
                        if info['process'] is proc:
                            info['finished_at'] = time.time()
                            break
                try:
                    output_queue.put_nowait(None)
                except queue.Full:
                    try:
                        output_queue.get_nowait()
                        output_queue.put_nowait(None)
                    except queue.Empty:
                        pass
        
        output_thread = threading.Thread(
            target=read_output,
            args=(process, running_processes[process_id]['output_queue'])
        )
        output_thread.daemon = True
        output_thread.start()
        
        return jsonify({
            "status": "success",
            "message": "脚本已启动",
            "process_id": process_id
        })
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/process/<process_id>/output')
def get_process_output(process_id):
    """获取进程输出（流式）"""
    def generate():
        cleanup_finished_processes()
        if process_id not in running_processes:
            yield f"data: {json.dumps({'type': 'error', 'message': '进程不存在'})}\n\n"
            return
        
        output_queue = running_processes[process_id]['output_queue']
        
        while True:
            try:
                line = output_queue.get(timeout=1)
                if line is None:
                    # 进程结束
                    yield f"data: {json.dumps({'type': 'end', 'message': '进程已结束'})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'output', 'data': line})}\n\n"
            except queue.Empty:
                # 发送心跳
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/process/<process_id>/stop', methods=['POST'])
def stop_process(process_id):
    """停止进程"""
    with process_lock:
        if process_id not in running_processes:
            return jsonify({"status": "error", "message": "进程不存在"}), 404
        
        process_info = running_processes[process_id]
        process = process_info['process']
        
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        with process_lock:
            running_processes.pop(process_id, None)
        return jsonify({"status": "success", "message": "进程已停止"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/processes')
def list_processes():
    """列出所有运行中的进程"""
    cleanup_finished_processes()
    processes = []
    with process_lock:
        for pid, info in running_processes.items():
            processes.append({
                'process_id': pid,
                'script_name': info['script_name'],
                'start_time': info['start_time'].isoformat(),
                'running': info['process'].poll() is None
            })
    return jsonify(processes)


@app.route('/api/logs')
def get_logs():
    """获取日志文件列表"""
    log_files = {}
    for log_dir in LOG_SOURCE_DIRS:
        for log_file in log_dir.glob("*.log"):
            log_files.setdefault(log_file.name, log_file)

    logs = []
    for log_file in log_files.values():
        logs.append({
            'name': log_file.name,
            'path': str(log_file),
            'size': log_file.stat().st_size,
            'modified': datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
        })
    logs.sort(key=lambda item: item['modified'], reverse=True)
    return jsonify(logs)


@app.route('/api/logs/<log_name>')
def get_log_content(log_name):
    """获取日志内容"""
    if Path(log_name).name != log_name:
        return jsonify({"status": "error", "message": "日志文件名无效"}), 400

    log_path = next(
        (directory / log_name for directory in LOG_SOURCE_DIRS
         if (directory / log_name).is_file()),
        None,
    )
    if log_path is None:
        return jsonify({"status": "error", "message": "日志文件不存在"}), 404
    
    try:
        # 读取最后1000行 (对于大文件更高效的方式)
        max_lines = 1000
        lines = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            tail = deque(maxlen=max_lines)
            for line in f:
                tail.append(line)
                total_lines += 1
            last_lines = list(tail)
        
        return jsonify({
            "content": ''.join(last_lines),
            "total_lines": total_lines,
            "shown_lines": len(last_lines)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/download/<script_name>')
def download_script(script_name):
    """下载脚本"""
    if script_name not in script_descriptions:
        return jsonify({"status": "error", "message": "脚本不存在"}), 404

    stored_path = script_descriptions.get(script_name, {}).get('path')
    resolved = resolve_script_path(script_name, stored_path)
    if resolved is None:
        return jsonify({"status": "error", "message": "脚本文件不存在"}), 404

    return send_file(str(resolved), as_attachment=True, download_name=script_name)


def cleanup_processes():
    """清理所有运行中的进程"""
    with process_lock:
        processes = [info['process'] for info in running_processes.values()]
    for process in processes:
        try:
            process.terminate()
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def signal_handler(sig, frame):
    """信号处理器"""
    print("\n正在关闭服务...")
    cleanup_processes()
    sys.exit(0)


def main():
    """主函数"""
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 加载脚本描述
    load_script_descriptions()
    
    # 创建模板目录
    templates_dir = BASE_DIR / "templates"
    templates_dir.mkdir(exist_ok=True)
    
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)

    threading.Thread(target=process_reaper, daemon=True, name="process-reaper").start()
    
    print("=" * 60)
    print("Testing Tool Web Service")
    print("=" * 60)
    print(f"服务地址: http://localhost:5000")
    print(f"脚本目录: {SCRIPTS_DIR}")
    print(f"配置文件: {CONFIG_FILE}")
    print(f"发现脚本: {len(script_descriptions)} 个")
    print("=" * 60)
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    
    # 启动Flask应用
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)


if __name__ == '__main__':
    main()
