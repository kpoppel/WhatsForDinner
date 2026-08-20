from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
import tempfile
from typing import Any

from app.models.state_schema import default_state_payload
from app.services.state_migrations import StateSchemaError, migrate_and_validate_state

DEFAULT_STATE_FILENAME = "state.json"
logger = logging.getLogger(__name__)


class Stage2State:
    def __init__(
        self,
        data_dir: str,
        sync_event_max_count: int = 2000,
        sync_event_max_age_days: int = 30,
    ) -> None:
        self.state_file = Path(data_dir) / DEFAULT_STATE_FILENAME
        self._sync_event_max_count = sync_event_max_count
        self._sync_event_max_age_days = sync_event_max_age_days
        self._lock = Lock()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save(default_state_payload())

    def _load(self) -> dict[str, Any]:
        with self.state_file.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        if not isinstance(data, dict):
            raise StateSchemaError("Invalid stage2 state payload: expected a JSON object.")

        try:
            return migrate_and_validate_state(data)
        except StateSchemaError:
            logger.exception("stage2_state_validation_failed state_file=%s", self.state_file)
            raise

    def _save(self, data: dict[str, Any]) -> None:
        payload = migrate_and_validate_state(deepcopy(data))
        tmp_path: Path | None = None
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
                json.dump(payload, fp, indent=2, ensure_ascii=True)
                fp.flush()
                os.fsync(fp.fileno())

            os.replace(tmp_path, self.state_file)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _parse_event_created_at(self, value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _prune_sync_events(self, data: dict[str, Any]) -> None:
        raw_events = data.get("shopping_sync_events")
        if not isinstance(raw_events, list):
            data["shopping_sync_events"] = []
            return

        events: list[dict[str, Any]] = [event for event in raw_events if isinstance(event, dict)]

        if self._sync_event_max_age_days > 0 and events:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._sync_event_max_age_days)
            kept_by_age: list[dict[str, Any]] = []
            for event in events:
                created_at = self._parse_event_created_at(event.get("created_at"))
                if created_at is None or created_at >= cutoff:
                    kept_by_age.append(event)
            events = kept_by_age

        if self._sync_event_max_count > 0 and len(events) > self._sync_event_max_count:
            events = events[-self._sync_event_max_count :]

        data["shopping_sync_events"] = events

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
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data["shopping_sync_events"].append(event)
            self._prune_sync_events(data)
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
