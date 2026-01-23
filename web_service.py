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
from datetime import datetime
from pathlib import Path
from configparser import ConfigParser
from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
import queue

app = Flask(__name__)
CORS(app)

# 全局配置
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
SCRIPTS_DIR = BASE_DIR
LOGS_DIR = BASE_DIR
DESCRIPTIONS_FILE = BASE_DIR / "script_descriptions.json"

# 全局变量，用于存储运行中的进程
running_processes = {}
process_lock = threading.Lock()

# 脚本描述数据
script_descriptions = {}


def load_script_descriptions():
    """加载脚本描述"""
    global script_descriptions
    if DESCRIPTIONS_FILE.exists():
        with open(DESCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
            script_descriptions = json.load(f)
    else:
        # 初始化默认描述
        script_descriptions = discover_scripts()
        save_script_descriptions()


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
        except:
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
    return jsonify(script_descriptions)


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
    
    script_path = script_descriptions[script_name]['path']
    
    # 生成唯一的进程ID
    process_id = f"{script_name}_{int(time.time())}"
    
    try:
        # 构建命令
        cmd = [sys.executable, script_path] + args
        
        # 启动进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
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
                'output_queue': queue.Queue()
            }
        
        # 启动线程读取输出
        def read_output(proc, output_queue):
            try:
                for line in proc.stdout:
                    output_queue.put(line)
            except:
                pass
            finally:
                proc.wait()
                output_queue.put(None)  # 标记结束
        
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
            # 尝试优雅终止
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 强制终止
                process.kill()
                process.wait()
            
            del running_processes[process_id]
            return jsonify({"status": "success", "message": "进程已停止"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/processes')
def list_processes():
    """列出所有运行中的进程"""
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
    logs = []
    for log_file in LOGS_DIR.glob("*.log"):
        logs.append({
            'name': log_file.name,
            'path': str(log_file),
            'size': log_file.stat().st_size,
            'modified': datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
        })
    return jsonify(logs)


@app.route('/api/logs/<log_name>')
def get_log_content(log_name):
    """获取日志内容"""
    log_path = LOGS_DIR / log_name
    if not log_path.exists() or not log_path.is_file():
        return jsonify({"status": "error", "message": "日志文件不存在"}), 404
    
    try:
        # 读取最后1000行
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-1000:] if len(lines) > 1000 else lines
        
        return jsonify({
            "content": ''.join(last_lines),
            "total_lines": len(lines),
            "shown_lines": len(last_lines)
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/download/<script_name>')
def download_script(script_name):
    """下载脚本"""
    if script_name not in script_descriptions:
        return jsonify({"status": "error", "message": "脚本不存在"}), 404
    
    script_path = script_descriptions[script_name]['path']
    return send_file(script_path, as_attachment=True, download_name=script_name)


def cleanup_processes():
    """清理所有运行中的进程"""
    with process_lock:
        for process_info in running_processes.values():
            try:
                process_info['process'].terminate()
                process_info['process'].wait(timeout=3)
            except:
                try:
                    process_info['process'].kill()
                except:
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
