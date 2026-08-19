import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional


class StorItem:
    __slots__ = ('s', 't', 'r', 'rs', 'l', 'M')

    def __init__(
        self,
        s: str = "unknown",
        t: str = "",
        r: str = "0,0",
        rs: int = 0,
        l: str = "",
        M: str = ""
    ):
        self.s = s
        self.t = t
        self.r = r
        self.rs = rs
        self.l = l
        self.M = M

    def to_dict(self) -> dict:
        return {
            "s": self.s,
            "t": self.t,
            "r": self.r,
            "rs": self.rs,
            "l": self.l,
            "M": self.M,
        }

    @staticmethod
    def from_dict(d: dict) -> "StorItem":
        return StorItem(
            s=d.get("s", "unknown"),
            t=d.get("t", ""),
            r=d.get("r", "0,0"),
            rs=d.get("rs", 0),
            l=d.get("l", ""),
            M=d.get("M", ""),
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def hour_ago_iso() -> str:
        dt = datetime.now(timezone.utc) - timedelta(hours=1)
        return dt.isoformat().replace("+00:00", "Z")


class StorList:
    def __init__(self):
        self._list: Dict[str, StorItem] = {}
        self._auto_update_disabled = set()
        self._lock = threading.Lock()
        self._event_condition = threading.Condition(self._lock)
        self._revision = 0
        self._events = deque(maxlen=1024)

    def get_all(self) -> dict:
        with self._lock:
            return {name: item.to_dict() for name, item in self._list.items()}

    def get_filtered(self, client_ip: str) -> dict:
        with self._lock:
            result = {}
            for name, item in self._list.items():
                if "@" in name:
                    base, ip = name.rsplit("@", 1)
                    if ip == client_ip:
                        result[base] = item.to_dict()
                else:
                    result[name] = item.to_dict()
            return result

    def add(self, name: str) -> bool:
        with self._lock:
            ip = ""
            base_name = name
            if "@" in name:
                parts = name.rsplit("@", 1)
                base_name = parts[0]
                ip = parts[1]
            if base_name in self._list:
                return False
            self._list[base_name] = StorItem(
                s="unknown",
                t=StorItem.now_iso(),
                M=ip,
            )
            return True

    def remove(self, name: str) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            del self._list[name]
            self._auto_update_disabled.discard(name)
            return True

    def set_status(self, name: str, status: str) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            self._list[name].s = status
            self._list[name].t = StorItem.now_iso()
            return True

    def set_time_now(self, name: str) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            self._list[name].t = StorItem.now_iso()
            return True

    def set_time_hour_ago(self, name: str) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            self._list[name].t = StorItem.hour_ago_iso()
            return True

    def update_item(self, name: str, data: dict) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            item = self._list[name]
            if "s" in data:
                item.s = data["s"]
            if "r" in data:
                item.r = data["r"]
            if "rs" in data:
                item.rs = data["rs"]
            if "l" in data:
                item.l = data["l"]
            if "M" in data:
                item.M = data["M"]
            if "t" in data:
                item.t = data["t"]
            return True

    def set_auto_update(self, name: str, enabled: bool) -> bool:
        with self._lock:
            if name not in self._list:
                return False
            if enabled:
                self._auto_update_disabled.discard(name)
            else:
                self._auto_update_disabled.add(name)
            return True

    def get_auto_update_settings(self) -> dict:
        with self._lock:
            return {"disabled_auto_update": sorted(self._auto_update_disabled)}

    def update_auto_timestamps(self) -> list:
        now = StorItem.now_iso()
        with self._lock:
            changed = []
            for name, item in self._list.items():
                if name not in self._auto_update_disabled:
                    item.t = now
                    changed.append(name)
            return changed

    def publish_change(self, change_type: str, names: Optional[list] = None) -> int:
        with self._event_condition:
            self._revision += 1
            event = {
                "revision": self._revision,
                "type": change_type,
                "names": names or [],
            }
            self._events.append(event)
            self._event_condition.notify_all()
            return self._revision

    def wait_for_events(self, after_revision: int, timeout: float = 15.0) -> list:
        deadline = time.monotonic() + timeout
        with self._event_condition:
            while self._revision <= after_revision:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._event_condition.wait(remaining)
            return [event.copy() for event in self._events if event["revision"] > after_revision]

    def to_json(self) -> dict:
        with self._lock:
            return {"list": {name: item.to_dict() for name, item in self._list.items()}}

    def load(self, filepath: str):
        with self._lock:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                raw_list = data.get("list", {})
                self._list = {
                    name: StorItem.from_dict(item)
                    for name, item in raw_list.items()
                }
            except (FileNotFoundError, json.JSONDecodeError):
                self._list = {}

    def load_settings(self, filepath: str):
        with self._lock:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                disabled = data.get("disabled_auto_update", [])
                self._auto_update_disabled = {
                    str(name) for name in disabled if str(name) in self._list
                }
            except (FileNotFoundError, json.JSONDecodeError):
                self._auto_update_disabled = set()

    def save(self, filepath: str):
        with self._lock:
            data = {"list": {name: item.to_dict() for name, item in self._list.items()}}
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def save_settings(self, filepath: str):
        with self._lock:
            data = {"disabled_auto_update": sorted(self._auto_update_disabled)}
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)


_DATA_FILE = str(
    Path(os.getenv("CAMERA_STATE_FILE", "/app/runtime/cycctv_stors.json"))
)
_SETTINGS_FILE = str(
    Path(os.getenv("CAMERA_SETTINGS_FILE", "/app/runtime/camera_settings.json"))
)

the_list = StorList()


def init_list(data_file: Optional[str] = None):
    global _DATA_FILE, _SETTINGS_FILE
    if data_file:
        _DATA_FILE = data_file
        _SETTINGS_FILE = str(Path(data_file).with_name("camera_settings.json"))
    the_list.load(_DATA_FILE)
    the_list.load_settings(_SETTINGS_FILE)
    the_list.save(_DATA_FILE)
    the_list.save_settings(_SETTINGS_FILE)


def save_list(change_type: str = "update", names: Optional[list] = None, publish: bool = True):
    the_list.save(_DATA_FILE)
    the_list.save_settings(_SETTINGS_FILE)
    if publish:
        the_list.publish_change(change_type, names)


def get_data_file() -> str:
    return _DATA_FILE
