import logging
import os
from pathlib import Path
from typing import Iterable, Optional


logger = logging.getLogger("feishu_agent")


def _resolve_log_file_path(log_file_path: Optional[str] = None) -> Path:
    if log_file_path:
        return Path(log_file_path).expanduser().resolve()

    default_path = Path(__file__).resolve().parents[2] / "logs" / "feishu_agent.log"
    return default_path


def setup_logging(log_file_path: Optional[str] = None, force: bool = False) -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    resolved_log_file = _resolve_log_file_path(log_file_path)
    resolved_log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    already_configured = bool(getattr(root_logger, "_feishu_logging_configured", False))
    configured_log_file = getattr(root_logger, "_feishu_log_file", "")
    if already_configured and not force:
        if configured_log_file != str(resolved_log_file):
            file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            root_logger.addHandler(file_handler)
            root_logger._feishu_log_file = str(resolved_log_file)
        root_logger.setLevel(level)
        return root_logger

    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(resolved_log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger.setLevel(level)
    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)
    root_logger._feishu_logging_configured = True
    root_logger._feishu_log_file = str(resolved_log_file)
    return root_logger


def log_case_start(route: str, target: str, message_id: str) -> None:
    logger.info("case start route=%s target=%s message_id=%s", route, target, message_id)


def log_step(route: str, step_index: int, detail: str) -> None:
    logger.info("case step route=%s step=%s detail=%s", route, step_index, detail)


def log_provider_call(provider_name: str, route: str) -> None:
    logger.info("provider call provider=%s route=%s", provider_name, route)


def log_case_end(route: str, target: str, evidence: Iterable[str]) -> None:
    logger.info("case end route=%s target=%s evidence_count=%s", route, target, len(list(evidence)))
