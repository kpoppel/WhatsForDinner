from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "selected_keyword_ids": [],
    "meal_plan_rules": {"no_repeat_days": 30},
    "user_settings": {
        "default_diners": 2,
        "default_notification_time": "08:00",
    },
    "meal_plans": {},
    "next_meal_plan_id": 1,
    "next_entry_id": 1,
    "shopping_status_overrides": {},
    "shopping_item_metadata": {},
    "local_shopping_entries": {},
    "next_local_shopping_entry_id": -1,
    "shopping_sync_events": [],
    "next_sync_event_id": 1,
}
DEFAULT_STATE_FILENAME = "state.json"


class Stage2State:
    def __init__(self, data_dir: str) -> None:
        self.state_file = Path(data_dir) / DEFAULT_STATE_FILENAME
        self._lock = Lock()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save(DEFAULT_STATE)

    def _load(self) -> dict[str, Any]:
        with self.state_file.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        merged = deepcopy(DEFAULT_STATE)
        merged.update(data)
        if not isinstance(merged.get("meal_plans"), dict):
            merged["meal_plans"] = {}
        if not isinstance(merged.get("shopping_status_overrides"), dict):
            merged["shopping_status_overrides"] = {}
        if not isinstance(merged.get("shopping_item_metadata"), dict):
            merged["shopping_item_metadata"] = {}
        if not isinstance(merged.get("local_shopping_entries"), dict):
            merged["local_shopping_entries"] = {}
        local_next_id = merged.get("next_local_shopping_entry_id")
        if not isinstance(local_next_id, int) or local_next_id >= 0:
            merged["next_local_shopping_entry_id"] = -1
        if not isinstance(merged.get("shopping_sync_events"), list):
            merged["shopping_sync_events"] = []
        rules = merged.get("meal_plan_rules")
        if not isinstance(rules, dict):
            merged["meal_plan_rules"] = {"no_repeat_days": 30}
        elif not isinstance(rules.get("no_repeat_days"), int):
            merged["meal_plan_rules"]["no_repeat_days"] = 30
        settings = merged.get("user_settings")
        if not isinstance(settings, dict):
            merged["user_settings"] = {
                "default_diners": 2,
                "default_notification_time": "08:00",
            }
        else:
            if not isinstance(settings.get("default_diners"), int):
                settings["default_diners"] = 2
            if not isinstance(settings.get("default_notification_time"), str):
                settings["default_notification_time"] = "08:00"
            elif len(settings["default_notification_time"].strip()) == 0:
                settings["default_notification_time"] = "08:00"
        return merged

    def _save(self, data: dict[str, Any]) -> None:
        with self.state_file.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=True)

    def selected_keywords(self) -> list[int]:
        with self._lock:
            data = self._load()
            return [int(v) for v in data.get("selected_keyword_ids", [])]

    def set_selected_keywords(self, keyword_ids: list[int]) -> list[int]:
        with self._lock:
            data = self._load()
            data["selected_keyword_ids"] = keyword_ids
            self._save(data)
        return keyword_ids

    def meal_plan_rules(self) -> dict[str, int]:
        with self._lock:
            data = self._load()
            rules = data.get("meal_plan_rules")
            if not isinstance(rules, dict):
                return {"no_repeat_days": 30}
            value = rules.get("no_repeat_days")
            if not isinstance(value, int):
                value = 30
            return {"no_repeat_days": value}

    def set_meal_plan_rules(self, no_repeat_days: int) -> dict[str, int]:
        with self._lock:
            data = self._load()
            data["meal_plan_rules"] = {"no_repeat_days": no_repeat_days}
            self._save(data)
        return {"no_repeat_days": no_repeat_days}

    def user_settings(self) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            raw = data.get("user_settings")
            if not isinstance(raw, dict):
                return {
                    "default_diners": 2,
                    "default_notification_time": "08:00",
                }

            default_diners = raw.get("default_diners")
            if not isinstance(default_diners, int):
                default_diners = 2

            default_notification_time = raw.get("default_notification_time")
            if not isinstance(default_notification_time, str):
                default_notification_time = "08:00"
            else:
                default_notification_time = default_notification_time.strip()
                if len(default_notification_time) == 0:
                    default_notification_time = "08:00"

            return {
                "default_diners": default_diners,
                "default_notification_time": default_notification_time,
            }

    def set_user_settings(self, default_diners: int, default_notification_time: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            data["user_settings"] = {
                "default_diners": default_diners,
                "default_notification_time": default_notification_time,
            }
            self._save(data)

        return {
            "default_diners": default_diners,
            "default_notification_time": default_notification_time,
        }

    def create_meal_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            plan_id = int(data.get("next_meal_plan_id", 1))
            data["next_meal_plan_id"] = plan_id + 1
            payload["plan_id"] = plan_id
            data["meal_plans"][str(plan_id)] = payload
            self._save(data)
        return payload

    def get_meal_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            plan = data["meal_plans"].get(str(plan_id))
            return deepcopy(plan) if isinstance(plan, dict) else None

    def list_meal_plans(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            values: list[dict[str, Any]] = []
            for _, plan in data.get("meal_plans", {}).items():
                if isinstance(plan, dict):
                    values.append(deepcopy(plan))

            values.sort(key=lambda row: int(row.get("plan_id", 0)), reverse=True)
            return values

    def update_meal_plan(self, plan_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            key = str(plan_id)
            current = data["meal_plans"].get(key)
            if not isinstance(current, dict):
                return None
            current.update(payload)
            data["meal_plans"][key] = current
            self._save(data)
            return deepcopy(current)

    def delete_meal_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            removed = data["meal_plans"].pop(str(plan_id), None)
            if not isinstance(removed, dict):
                return None
            self._save(data)
            return deepcopy(removed)

    def allocate_entry_id(self) -> int:
        with self._lock:
            data = self._load()
            entry_id = int(data.get("next_entry_id", 1))
            data["next_entry_id"] = entry_id + 1
            self._save(data)
            return entry_id

    def append_sync_event(self, operation: str, payload: dict[str, Any]) -> int:
        with self._lock:
            data = self._load()
            event_id = int(data.get("next_sync_event_id", 1))
            data["next_sync_event_id"] = event_id + 1
            event = {
                "cursor": event_id,
                "operation": operation,
                "payload": payload,
            }
            data["shopping_sync_events"].append(event)
            self._save(data)
            return event_id

    def sync_events_since(self, cursor: int) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            return [
                deepcopy(event)
                for event in data.get("shopping_sync_events", [])
                if int(event.get("cursor", 0)) > cursor
            ]

    def current_sync_cursor(self) -> int:
        with self._lock:
            data = self._load()
            return max(int(data.get("next_sync_event_id", 1)) - 1, 0)

    def set_shopping_status(self, entry_id: int, status: str) -> None:
        with self._lock:
            data = self._load()
            data["shopping_status_overrides"][str(entry_id)] = status
            self._save(data)

    def get_shopping_statuses(self) -> dict[str, str]:
        with self._lock:
            data = self._load()
            raw = data.get("shopping_status_overrides", {})
            if not isinstance(raw, dict):
                return {}
            return {str(k): str(v) for k, v in raw.items()}

    def set_shopping_item_metadata(self, entry_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            key = str(entry_id)
            raw = data.get("shopping_item_metadata", {})
            current = raw.get(key, {}) if isinstance(raw, dict) else {}
            if not isinstance(current, dict):
                current = {}
            current.update(patch)
            if not isinstance(data.get("shopping_item_metadata"), dict):
                data["shopping_item_metadata"] = {}
            data["shopping_item_metadata"][key] = current
            self._save(data)
            return deepcopy(current)

    def delete_shopping_item_metadata(self, entry_id: int) -> None:
        with self._lock:
            data = self._load()
            raw = data.get("shopping_item_metadata")
            if isinstance(raw, dict):
                raw.pop(str(entry_id), None)
                self._save(data)

    def get_shopping_item_metadata(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            data = self._load()
            raw = data.get("shopping_item_metadata", {})
            if not isinstance(raw, dict):
                return {}
            sanitized: dict[str, dict[str, Any]] = {}
            for key, value in raw.items():
                if isinstance(value, dict):
                    sanitized[str(key)] = deepcopy(value)
            return sanitized

    def allocate_local_shopping_entry_id(self) -> int:
        with self._lock:
            data = self._load()
            next_id = int(data.get("next_local_shopping_entry_id", -1))
            if next_id >= 0:
                next_id = -1
            data["next_local_shopping_entry_id"] = next_id - 1
            self._save(data)
            return next_id

    def list_local_shopping_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            raw = data.get("local_shopping_entries", {})
            if not isinstance(raw, dict):
                return []
            items: list[dict[str, Any]] = []
            for _, value in raw.items():
                if isinstance(value, dict):
                    items.append(deepcopy(value))
            return items

    def get_local_shopping_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            raw = data.get("local_shopping_entries", {})
            if not isinstance(raw, dict):
                return None
            entry = raw.get(str(entry_id))
            if not isinstance(entry, dict):
                return None
            return deepcopy(entry)

    def set_local_shopping_entry(self, entry_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            if not isinstance(data.get("local_shopping_entries"), dict):
                data["local_shopping_entries"] = {}
            data["local_shopping_entries"][str(entry_id)] = deepcopy(payload)
            self._save(data)
            return deepcopy(payload)

    def update_local_shopping_entry(self, entry_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            raw = data.get("local_shopping_entries", {})
            if not isinstance(raw, dict):
                return None
            current = raw.get(str(entry_id))
            if not isinstance(current, dict):
                return None
            current.update(deepcopy(patch))
            raw[str(entry_id)] = current
            self._save(data)
            return deepcopy(current)

    def delete_local_shopping_entry(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            raw = data.get("local_shopping_entries", {})
            if not isinstance(raw, dict):
                return None
            removed = raw.pop(str(entry_id), None)
            if not isinstance(removed, dict):
                return None
            self._save(data)
            return deepcopy(removed)
