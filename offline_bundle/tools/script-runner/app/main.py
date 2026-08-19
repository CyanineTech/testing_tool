#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script Service for Testing Tool
独立脚本执行服务，端口 8000
提供脚本管理、执行、配置、日志等功能
通过 gateway (5000) 代理访问
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
from configparser import ConfigParser
from collections import deque


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
    from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
except ModuleNotFoundError as e:
    _print_missing_dependency_help(getattr(e, "name", "flask"))
    raise

import queue
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

app = Flask(__name__)
asgi = FastAPI(title="Testing Tool Script Runner", version="1.0.0")
asgi.mount("/", WSGIMiddleware(app))

# 全局配置
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
CONFIG_FILE = Path(os.getenv("CONFIG_FILE", str(PROJECT_ROOT / "runtime" / "config.ini"))).expanduser().resolve()
SCRIPTS_DIR = Path(os.getenv("SCRIPTS_DIR", str(PROJECT_ROOT / "scripts"))).expanduser().resolve()
LOGS_DIR = Path(os.getenv("LOGS_DIR", str(PROJECT_ROOT / "runtime" / "logs"))).expanduser().resolve()
LOG_SOURCE_DIRS = (LOGS_DIR, SCRIPTS_DIR)
DESCRIPTIONS_FILE = Path(os.getenv("DESCRIPTIONS_FILE", str(PROJECT_ROOT / "runtime" / "script_descriptions.json"))).expanduser().resolve()
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
try:
    WEB_PORT = int(os.getenv("SCRIPT_SERVICE_PORT", "8000"))
except ValueError:
    WEB_PORT = 8000

# 全局变量，用于存储运行中的进程
running_processes = {}
process_lock = threading.Lock()
launching_scripts = set()
MAX_OUTPUT_BUFFER_LINES = 2000
MAX_OUTPUT_QUEUE_LINES = 2000
PROCESS_RETENTION_SECONDS = 10 * 60
MAX_RUNNING_PROCESSES = 8
SENSITIVE_CONFIG_KEYS = {"password", "token", "access_token", "secret"}

# 脚本描述数据
script_descriptions = {}

_SERVICE_SCRIPTS = set()


def prune_missing_scripts(save: bool = True) -> dict:
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
    candidates: List[Path] = []
    if stored_path:
        candidates.append(Path(stored_path))
    candidates.append(SCRIPTS_DIR / script_name)
    for candidate in candidates:
        try:
            candidate_resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        if candidate_resolved.is_file() and candidate_resolved.name == script_name:
            return candidate_resolved
    return None


def load_script_descriptions():
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
    scan_and_merge_scripts(save=True)
    prune_missing_scripts(save=True)


def save_script_descriptions():
    DESCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DESCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
        json.dump(script_descriptions, f, ensure_ascii=False, indent=2)


def public_config(config: ConfigParser) -> dict:
    result = {}
    for section in config.sections():
        result[section] = {
            key: ("" if key.lower() in SENSITIVE_CONFIG_KEYS else value)
            for key, value in config.items(section)
        }
    return result


def cleanup_finished_processes() -> None:
    cutoff = time.time() - PROCESS_RETENTION_SECONDS
    with process_lock:
        stale_ids = []
        for process_id, info in running_processes.items():
            finished_at = info.get('finished_at')
            process = info.get('process')
            if finished_at and finished_at < cutoff and process.poll() is not None:
                stale_ids.append(process_id)
        for process_id in stale_ids:
            running_processes.pop(process_id, None)


def process_reaper() -> None:
    while True:
        time.sleep(60)
        cleanup_finished_processes()


def discover_scripts():
    scripts = {}
    for file in SCRIPTS_DIR.glob("*.py"):
        if file.name in _SERVICE_SCRIPTS:
            continue
        script_name = file.name
        description = ""
        workflow = ""
        try:
            with open(file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                in_docstring = False
                docstring_lines = []
                for line in lines[:50]:
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
    return jsonify({"status": "ok", "service": "tool-script-runner"})


@app.route('/health')
def health():
    return jsonify({"status": "ok", "service": "tool-script-runner"})


@app.route('/api/v1/scripts')
def get_scripts():
    refresh = str(request.args.get("refresh", "0")).strip().lower() in ("1", "true", "yes", "on")
    include_missing = str(request.args.get("include_missing", "0")).strip().lower() in ("1", "true", "yes", "on")
    if refresh:
        scan_and_merge_scripts(save=True)
    if include_missing:
        return jsonify(script_descriptions)
    filtered = {}
    for script_name, meta in script_descriptions.items():
        stored_path = meta.get("path") if isinstance(meta, dict) else None
        if resolve_script_path(script_name, stored_path) is not None:
            filtered[script_name] = meta
    return jsonify(filtered)


@app.route('/api/v1/scripts/refresh', methods=['POST'])
def refresh_scripts():
    result = scan_and_merge_scripts(save=True)
    return jsonify({"status": "success", "message": "脚本列表已刷新", **result})


@app.route('/api/v1/scripts/<script_name>', methods=['GET', 'PUT'])
def manage_script(script_name):
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


@app.route('/api/v1/scripts/config', methods=['GET', 'PUT'])
def manage_config():
    if request.method == 'GET':
        try:
            config = ConfigParser()
            config.read(CONFIG_FILE, encoding='utf-8')
            return jsonify(public_config(config))
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    elif request.method == 'PUT':
        try:
            data = request.json
            if not isinstance(data, dict):
                return jsonify({"status": "error", "message": "配置必须是对象"}), 400
            config = ConfigParser()
            config.read(CONFIG_FILE, encoding='utf-8')
            for section, options in data.items():
                if not isinstance(section, str) or not isinstance(options, dict):
                    return jsonify({"status": "error", "message": "配置段格式无效"}), 400
                config.add_section(section)
                for key, value in options.items():
                    if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
                        return jsonify({"status": "error", "message": "配置项格式无效"}), 400
                    if key.lower() in SENSITIVE_CONFIG_KEYS and str(value) == "":
                        continue
                    config.set(section, key, str(value))
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                config.write(f)
            return jsonify({"status": "success", "message": "配置已保存"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/v1/scripts/execute/<script_name>', methods=['POST'])
def execute_script(script_name):
    if script_name not in script_descriptions:
        return jsonify({"status": "error", "message": "脚本不存在"}), 404
    data = request.json or {}
    args = data.get('args', [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        return jsonify({"status": "error", "message": "args 必须是字符串数组"}), 400
    if len(args) > 64 or any(len(arg) > 4096 for arg in args):
        return jsonify({"status": "error", "message": "脚本参数数量或长度超限"}), 400
    stored_path = script_descriptions.get(script_name, {}).get('path')
    resolved = resolve_script_path(script_name, stored_path)
    if resolved is None:
        return jsonify({
            "status": "error",
            "message": f"脚本文件不存在: {script_name}（当前脚本目录: {SCRIPTS_DIR}）"
        }), 404
    script_path = str(resolved)
    cleanup_finished_processes()
    with process_lock:
        if script_name in launching_scripts:
            return jsonify({
                "status": "error",
                "message": f"脚本正在启动中，请稍候: {script_name}"
            }), 409
        launching_scripts.add(script_name)
        active_for_script = sum(
            1 for info in running_processes.values()
            if info.get('script_name') == script_name and info['process'].poll() is None
        )
        active_total = sum(
            1 for info in running_processes.values()
            if info['process'].poll() is None
        )
    if active_for_script >= 1:
        with process_lock:
            launching_scripts.discard(script_name)
        return jsonify({
            "status": "error",
            "message": f"脚本正在运行中，请先停止现有进程: {script_name}"
        }), 409
    if active_total >= MAX_RUNNING_PROCESSES:
        with process_lock:
            launching_scripts.discard(script_name)
        return jsonify({
            "status": "error",
            "message": f"运行中的脚本已达到上限({MAX_RUNNING_PROCESSES})，请先停止不需要的进程"
        }), 429
    process_id = f"{script_name}_{uuid.uuid4().hex}"
    try:
        cmd = [sys.executable, '-u', script_path] + args
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=str(SCRIPTS_DIR),
            start_new_session=True,
        )
        with process_lock:
            running_processes[process_id] = {
                'process': process,
                'script_name': script_name,
                'start_time': datetime.now(),
                'output_queue': queue.Queue(maxsize=MAX_OUTPUT_QUEUE_LINES),
                'output_buffer': deque(maxlen=MAX_OUTPUT_BUFFER_LINES),
                'stream_generation': 0
            }
            launching_scripts.discard(script_name)

        def read_output(proc, output_queue, pid):
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
                    with process_lock:
                        info = running_processes.get(pid)
                        if info is not None:
                            buf = info.setdefault('output_buffer', deque(maxlen=MAX_OUTPUT_BUFFER_LINES))
                            buf.append(line)
            except Exception:
                pass
            finally:
                proc.wait()
                with process_lock:
                    info = running_processes.get(pid)
                    if info is not None:
                        info['finished_at'] = time.time()
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
            args=(process, running_processes[process_id]['output_queue'], process_id)
        )
        output_thread.daemon = True
        output_thread.start()
        return jsonify({
            "status": "success",
            "message": "脚本已启动",
            "process_id": process_id
        })
    except Exception as e:
        with process_lock:
            launching_scripts.discard(script_name)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/v1/scripts/process/<process_id>/output')
def get_process_output(process_id):
    with process_lock:
        process_info = running_processes.get(process_id)
        if process_info is not None:
            process_info['stream_generation'] = process_info.get('stream_generation', 0) + 1
            stream_generation = process_info['stream_generation']
            output_queue = process_info['output_queue']
        else:
            stream_generation = None
            output_queue = None

    @stream_with_context
    def generate():
        cleanup_finished_processes()
        if output_queue is None:
            yield f"data: {json.dumps({'type': 'error', 'message': '进程不存在'})}\n\n"
            return
        while True:
            with process_lock:
                current = running_processes.get(process_id)
                if current is None or current.get('stream_generation') != stream_generation:
                    return
            try:
                line = output_queue.get(timeout=1)
                if line is None:
                    yield f"data: {json.dumps({'type': 'end', 'message': '进程已结束'})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'output', 'data': line})}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })


@app.route('/api/v1/scripts/process/<process_id>/recent')
def get_process_recent_output(process_id):
    try:
        lines = int(request.args.get('lines', 300))
    except Exception:
        lines = 300
    if lines <= 0:
        lines = 300
    if lines > MAX_OUTPUT_BUFFER_LINES:
        lines = MAX_OUTPUT_BUFFER_LINES
    cleanup_finished_processes()
    with process_lock:
        info = running_processes.get(process_id)
        if info is None:
            return jsonify({"status": "error", "message": "进程不存在"}), 404
        output_buffer = info.get('output_buffer') or []
        tail = output_buffer[-lines:]
        return jsonify({
            "status": "success",
            "process_id": process_id,
            "script_name": info.get('script_name', ''),
            "start_time": info.get('start_time').isoformat() if info.get('start_time') else '',
            "running": info.get('process').poll() is None,
            "content": ''.join(tail),
            "lines": len(tail)
        })


@app.route('/api/v1/scripts/process/<process_id>/stop', methods=['POST'])
def stop_process(process_id):
    with process_lock:
        if process_id not in running_processes:
            return jsonify({"status": "error", "message": "进程不存在"}), 404
        process_info = running_processes[process_id]
        process = process_info['process']
    try:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            process.wait()
        with process_lock:
            running_processes.pop(process_id, None)
        return jsonify({"status": "success", "message": "进程已停止"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/v1/scripts/processes')
def list_processes():
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


@app.route('/api/v1/scripts/logs')
def get_logs():
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


@app.route('/api/v1/scripts/logs/<log_name>')
def get_log_content(log_name):
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
        max_lines = 1000
        chunk_size = 64 * 1024
        chunks = []
        newline_count = 0
        with open(log_path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            while position > 0 and newline_count <= max_lines:
                read_size = min(chunk_size, position)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size)
                chunks.append(chunk)
                newline_count += chunk.count(b'\n')
        raw_tail = b''.join(reversed(chunks))
        last_lines = raw_tail.decode('utf-8', errors='ignore').splitlines(keepends=True)[-max_lines:]
        shown_lines = len(last_lines)
        truncated = position > 0
        return jsonify({
            "content": ''.join(last_lines),
            "total_lines": None,
            "shown_lines": shown_lines,
            "truncated": truncated
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/v1/scripts/download/<script_name>')
def download_script(script_name):
    if script_name not in script_descriptions:
        return jsonify({"status": "error", "message": "脚本不存在"}), 404
    stored_path = script_descriptions.get(script_name, {}).get('path')
    resolved = resolve_script_path(script_name, stored_path)
    if resolved is None:
        return jsonify({"status": "error", "message": "脚本文件不存在"}), 404
    return send_file(str(resolved), as_attachment=True, download_name=script_name)


def cleanup_processes():
    with process_lock:
        processes = [info['process'] for info in running_processes.values()]
    for process in processes:
        try:
            if process.poll() is None:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=3)
        except Exception:
            try:
                if process.poll() is None:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass


def signal_handler(sig, frame):
    print("\n[script_service] 正在关闭...")
    cleanup_processes()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    load_script_descriptions()
    templates_dir = BASE_DIR / "templates"
    templates_dir.mkdir(exist_ok=True)
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=process_reaper, daemon=True, name="process-reaper").start()
    print("=" * 60)
    print("Script Service")
    print("=" * 60)
    print(f"服务地址: http://127.0.0.1:{WEB_PORT}")
    print(f"脚本目录: {SCRIPTS_DIR}")
    print(f"配置文件: {CONFIG_FILE}")
    print(f"发现脚本: {len(script_descriptions)} 个")
    print("=" * 60)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, threaded=True)


# Uvicorn imports this module instead of executing it as __main__. Initialize
# the registry for both launch modes so the API never starts with an empty list.
load_script_descriptions()
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
DESCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

if __name__ == '__main__':
    main()
