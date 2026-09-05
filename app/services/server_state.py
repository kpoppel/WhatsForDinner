from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from threading import Lock, Timer
import tempfile
from typing import Any
import uuid

from app.models.state_schema import default_state_payload
from app.services.state_migrations import StateSchemaError, migrate_and_validate_state

DEFAULT_STATE_FILENAME = "state.json"
STATE_FLUSH_DELAY_SECONDS = 0.25
logger = logging.getLogger(__name__)


class ServerState:
    def __init__(
        self,
        data_dir: str,
    ) -> None:
        self.state_file = Path(data_dir) / DEFAULT_STATE_FILENAME
        self._lock = Lock()
        self._write_lock = Lock()
        self._flush_timer: Timer | None = None
        self._dirty = False
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._data = migrate_and_validate_state(default_state_payload())
            self._write(self._data)
        else:
            self._data = self._read()
            self._write(self._data)

    def _read(self) -> dict[str, Any]:
        with self.state_file.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        if not isinstance(data, dict):
            raise StateSchemaError("Invalid stage2 state payload: expected a JSON object.")

        try:
            return migrate_and_validate_state(data)
        except StateSchemaError:
            logger.exception("server_state_validation_failed state_file=%s", self.state_file)
            raise

    def _load(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def _save(self, data: dict[str, Any]) -> None:
        self._data = migrate_and_validate_state(deepcopy(data))
        self._dirty = True
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_timer is not None:
            return
        self._flush_timer = Timer(STATE_FLUSH_DELAY_SECONDS, self._flush_background)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _flush_background(self) -> None:
        try:
            self.flush()
        except Exception:
            logger.exception("server_state_flush_failed state_file=%s", self.state_file)

    def flush(self) -> None:
        while True:
            with self._lock:
                if self._flush_timer is not None:
                    self._flush_timer.cancel()
                    self._flush_timer = None
                if not self._dirty:
                    return
                payload = deepcopy(self._data)
                self._dirty = False

            self._write(payload)

            with self._lock:
                if not self._dirty:
                    return

    def _write(self, data: dict[str, Any]) -> None:
        tmp_path: Path | None = None
        with self._write_lock:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.state_file.parent,
                    prefix=f"{self.state_file.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as fp:
                    tmp_path = Path(fp.name)
                    json.dump(data, fp, indent=2, ensure_ascii=True)
                    fp.flush()
                    os.fsync(fp.fileno())

                os.replace(tmp_path, self.state_file)
            finally:
                if tmp_path is not None and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)

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
                raise StateSchemaError("Invalid state: user_settings must be an object.")

            default_diners = raw.get("default_diners")
            default_notification_time = raw.get("default_notification_time")
            if not isinstance(default_diners, int) or not isinstance(default_notification_time, str):
                raise StateSchemaError("Invalid state: user_settings fields are not valid.")

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

    def set_settings(
        self,
        default_diners: int,
        default_notification_time: str,
        no_repeat_days: int,
        keyword_ids: list[int],
    ) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            data["user_settings"] = {
                "default_diners": default_diners,
                "default_notification_time": default_notification_time,
            }
            data["meal_plan_rules"] = {"no_repeat_days": no_repeat_days}
            data["selected_keyword_ids"] = keyword_ids
            self._save(data)

        return {
            "user_settings": {
                "default_diners": default_diners,
                "default_notification_time": default_notification_time,
            },
            "meal_plan_rules": {"no_repeat_days": no_repeat_days},
            "selected_keyword_ids": keyword_ids,
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
            meal_plan_sync = data.get("meal_plan_instance_sync")
            if isinstance(meal_plan_sync, dict):
                meal_plan_sync.pop(str(plan_id), None)
            self._save(data)
            return deepcopy(removed)

    def get_meal_plan_instance_sync(self, plan_id: int) -> dict[str, dict[str, Any]]:
        with self._lock:
            data = self._load()
            raw_sync = data.get("meal_plan_instance_sync")
            if not isinstance(raw_sync, dict):
                return {}
            plan_sync = raw_sync.get(str(plan_id))
            if not isinstance(plan_sync, dict):
                return {}
            instances = plan_sync.get("instances")
            if not isinstance(instances, dict):
                return {}
            sanitized: dict[str, dict[str, Any]] = {}
            for key, value in instances.items():
                if isinstance(value, dict):
                    sanitized[str(key)] = deepcopy(value)
            return sanitized

    def set_meal_plan_instance_sync(self, plan_id: int, instances: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            data = self._load()
            if not isinstance(data.get("meal_plan_instance_sync"), dict):
                data["meal_plan_instance_sync"] = {}
            sanitized: dict[str, dict[str, Any]] = {}
            for key, value in instances.items():
                if isinstance(value, dict):
                    sanitized[str(key)] = deepcopy(value)
            data["meal_plan_instance_sync"][str(plan_id)] = {"instances": sanitized}
            self._save(data)

    def allocate_entry_id(self) -> int:
        with self._lock:
            data = self._load()
            entry_id = int(data.get("next_entry_id", 1))
            data["next_entry_id"] = entry_id + 1
            self._save(data)
            return entry_id

    def set_shopping_status(self, entry_id: int, status: str) -> None:
        with self._lock:
            data = self._load()
            key = str(entry_id)
            if entry_id < 0:
                data["shopping_status_overrides"][key] = status
            else:
                data["shopping_status_overrides"].pop(key, None)
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

    def set_pending_shopping_changes(self, changes: list[dict[str, Any]]) -> None:
        with self._lock:
            data = self._load()
            existing = data.get("pending_shopping_changes", {})
            pending = deepcopy(existing) if isinstance(existing, dict) else {}
            for change in changes:
                if not isinstance(change, dict):
                    continue
                operation = change.get("operation")
                entry_id = change.get("entry_id")
                if not isinstance(operation, str) or operation not in {"create", "update", "delete"}:
                    continue
                if operation == "create" and entry_id is None:
                    key = f"create:{uuid.uuid4().hex}"
                elif isinstance(entry_id, int):
                    key = str(entry_id)
                else:
                    continue
                pending[key] = {
                    "operation": operation,
                    "entry_id": entry_id,
                    "payload": deepcopy(change.get("payload", {})),
                }
            data["pending_shopping_changes"] = pending
            self._save(data)

    def pending_shopping_changes(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            data = self._load()
            pending = data.get("pending_shopping_changes", {})
            return deepcopy(pending) if isinstance(pending, dict) else {}

    def clear_pending_shopping_changes(self) -> None:
        with self._lock:
            data = self._load()
            data["pending_shopping_changes"] = {}
            self._save(data)
