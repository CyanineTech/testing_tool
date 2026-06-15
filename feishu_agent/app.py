import json
import logging
import os
import re
from typing import Any, Dict, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from feishu_agent.diagnostics import extract_target, infer_target_role
from feishu_agent.observability.logger import setup_logging

setup_logging()

app = FastAPI(title="AMR/RCS Feishu Agent", version="0.1.0")


MENTION_PLACEHOLDER_RE = re.compile(r"<at[^>]*>(.*?)</at>|@_user_\d+")


def normalize_message_text(text: str) -> str:
    cleaned = re.sub(r"<at[^>]*>.*?</at>", "", text)
    cleaned = re.sub(r"@_user_\d+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_message(payload: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    event = payload.get("event") or {}
    message = event.get("message") or {}
    raw_content = message.get("content")
    content: Dict[str, Any]

    if isinstance(raw_content, str):
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError:
            content = {"text": raw_content}
    elif isinstance(raw_content, dict):
        content = raw_content
    else:
        content = {}

    raw_text = str(content.get("text") or content.get("content") or "").strip()
    text = normalize_message_text(raw_text)
    return text, payload


def classify_text(text: str, target: str = "") -> str:
    lowered = text.lower()
    combined = f"{text} {target}".strip()
    target_role = infer_target_role(target)
    explicit_rcs_text = any(keyword in text for keyword in ["RCS", "主机", "调度", "派发", "后台"])
    rcs_hint = target_role == "rcs" or explicit_rcs_text or any(keyword in combined for keyword in ["数据库", "任务"])
    if any(keyword in lowered for keyword in ["knowledge", "文档", "目录", "总结文档", "读取文档", "读取 knowledge", "知识库", "readme"]):
        return "knowledge"
    if any(keyword in lowered for keyword in ["timeout", "超时", "无返回", "不通", "拒绝连接", "响应慢", "请求慢", "连接失败", "卡住"]):
        if rcs_hint:
            return "rcs"
    if any(keyword in lowered for keyword in ["cpu", "占用", "负载", "高负载", "过高", "吃满", "卡顿", "卡住", "变慢", "超慢"]):
        if rcs_hint:
            return "rcs"
        return "amr"
    if rcs_hint and any(keyword in lowered for keyword in ["ros call", "ros service", "service call", "request_states", "limited_zone", "接口", "后端", "backend", "服务"]):
        return "rcs"
    if rcs_hint:
        return "rcs"
    if any(keyword in text for keyword in ["bag", "取货", "放货", "叉货", "定位", "相机", "usb", "can", "雷达", "激光", "雷射", "lidar", "laser", "scan", "扫描", "amr", "从机", "机器人", "AGV"]):
        return "amr"
    if any(keyword in lowered for keyword in ["wifi", "dns", "ping", "tailscale", "掉线", "网络", "连不上"]):
        return "network"
    return "unknown"


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/feishu/events")
async def feishu_events(request: Request) -> JSONResponse:
    payload = await request.json()

    if "challenge" in payload:
        return JSONResponse({"challenge": payload["challenge"]})

    text, raw_payload = parse_message(payload)
    route = classify_text(text, extract_target(text) or "")

    logging.info("feishu event received route=%s text=%s payload=%s", route, text, raw_payload)

    return JSONResponse(
        {
            "ok": True,
            "route": route,
            "text": text,
            "hint": "先把飞书事件接入跑通，再把 route 对应到排障脚本。",
        }
    )
