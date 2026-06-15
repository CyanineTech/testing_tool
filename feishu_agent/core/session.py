import json
import os
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional
import time


@dataclass
class SessionState:
    route: str = ""
    target: str = ""
    time_key: str = ""
    step_index: int = 0
    evidence: List[str] = field(default_factory=list)
    last_report: str = ""
    last_doc_candidates: List[str] = field(default_factory=list)
    last_read_docs: List[str] = field(default_factory=list)
    last_docs: List[str] = field(default_factory=list)
    last_reply_kind: str = ""
    last_payload: Dict[str, Any] = field(default_factory=dict)
    last_active_at: float = 0.0


class SessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: Dict[str, SessionState] = {}
        self._state_file = os.getenv(
            "FEISHU_SESSION_STATE_FILE",
            "/home/robot/amr-rcs-troubleshoot/logs/feishu_session_state.json",
        )
        self._last_loaded_mtime: float = 0.0
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            mtime = os.path.getmtime(self._state_file)
        except FileNotFoundError:
            self._last_loaded_mtime = 0.0
            return
        except Exception:
            return

        if mtime <= self._last_loaded_mtime and self._sessions:
            return

        try:
            with open(self._state_file, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except FileNotFoundError:
            self._last_loaded_mtime = 0.0
            return
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        sessions: Dict[str, SessionState] = {}
        for session_key, state_payload in payload.items():
            if not isinstance(state_payload, dict):
                continue
            try:
                sessions[session_key] = SessionState(**state_payload)
            except TypeError:
                continue
        self._sessions = sessions
        self._last_loaded_mtime = mtime

    def _persist_to_disk(self) -> None:
        directory = os.path.dirname(self._state_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        serialized = {key: asdict(value) for key, value in self._sessions.items()}
        tmp_path = f"{self._state_file}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(serialized, fh, ensure_ascii=False)
        os.replace(tmp_path, self._state_file)
        try:
            self._last_loaded_mtime = os.path.getmtime(self._state_file)
        except Exception:
            pass

    def get(self, session_key: str) -> SessionState:
        with self._lock:
            self._load_from_disk()
            return self._sessions.get(session_key, SessionState())

    def update(self, session_key: str, **kwargs: Any) -> SessionState:
        with self._lock:
            state = self._sessions.get(session_key, SessionState())
            for key, value in kwargs.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            state.last_active_at = time.monotonic()
            self._sessions[session_key] = state
            self._persist_to_disk()
            return state

    def clear(self, session_key: str) -> None:
        with self._lock:
            self._sessions.pop(session_key, None)
            self._persist_to_disk()

    def prune_expired(self, ttl_seconds: int, now: Optional[float] = None) -> None:
        if ttl_seconds <= 0:
            return

        current_time = now if now is not None else time.monotonic()
        expired_keys = []

        with self._lock:
            for session_key, state in self._sessions.items():
                if state.last_active_at and current_time - state.last_active_at > ttl_seconds:
                    expired_keys.append(session_key)
            for session_key in expired_keys:
                self._sessions.pop(session_key, None)
            if expired_keys:
                self._persist_to_disk()
