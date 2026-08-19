#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CCTV Mock Server
独立摄像头模拟服务，端口 8002
通过 gateway (5000) 代理访问
"""

import os
import sys
import threading
import time
from pathlib import Path
from fastapi import FastAPI
from starlette.middleware.wsgi import WSGIMiddleware

try:
    from flask import Flask
except ModuleNotFoundError as e:
    print(f"缺少依赖: {e}", file=sys.stderr)
    raise

BASE_DIR = Path(__file__).resolve().parent

# Ensure the camera mock package is importable.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from camera_mock import cycctv_bp
from camera_mock.models import init_list as cycctv_init_list, save_list, the_list

app = Flask(__name__)
asgi = FastAPI(title="Testing Tool Camera Simulator", version="1.0.0")
asgi.mount("/", WSGIMiddleware(app))
app.register_blueprint(cycctv_bp)


@app.route('/health')
def health():
    return {"status": "ok", "service": "tool-camera-sim"}

WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
try:
    WEB_PORT = int(os.getenv("CCTV_SERVICE_PORT", "8002"))
except ValueError:
    WEB_PORT = 8002


def main():
    print("=" * 60)
    print("CCTV Mock Server")
    print("=" * 60)
    print(f"服务地址: http://127.0.0.1:{WEB_PORT}")
    print(f"API 接口: /api/v1/camera/list-all")
    print(f"管理页面: /api/v1/camera/list-mock")
    print("=" * 60)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, threaded=True)


# Uvicorn imports this module, so initialize persisted mock data on import.
cycctv_init_list()


def auto_timestamp_worker() -> None:
    persist_after = time.monotonic()
    while True:
        changed = the_list.update_auto_timestamps()
        if changed:
            the_list.publish_change("timestamp", changed)
        now = time.monotonic()
        if now >= persist_after:
            save_list(publish=False)
            persist_after = now + 15
        time.sleep(1)


threading.Thread(
    target=auto_timestamp_worker,
    daemon=True,
    name="camera-auto-timestamp",
).start()

if __name__ == "__main__":
    main()
