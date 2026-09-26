from __future__ import annotations

from datetime import date, timedelta
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
            self._prune_recipe_use_history(self._data)
            self._data["shopping_status_overrides"] = {
                entry_id: status
                for entry_id, status in self._data["shopping_status_overrides"].items()
                if entry_id in self._data["local_shopping_entries"]
            }
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

    def _prune_recipe_use_history(self, data: dict[str, Any]) -> None:
        """Remove recipe uses that are outside the current no-repeat window."""
        no_repeat_days = data["meal_plan_rules"]["no_repeat_days"]
        if no_repeat_days <= 0:
            data["recipe_use_history"] = []
            return

        cutoff_date = date.today() - timedelta(days=no_repeat_days)
        data["recipe_use_history"] = [
            item
            for item in data["recipe_use_history"]
            if date.fromisoformat(item["used_date"]) >= cutoff_date
        ]

    def selected_keywords(self) -> list[int]:
        with self._lock:
            data = self._load()
            return data["selected_keyword_ids"]

    def set_selected_keywords(self, keyword_ids: list[int]) -> list[int]:
        with self._lock:
            data = self._load()
            data["selected_keyword_ids"] = keyword_ids
            self._save(data)
        return keyword_ids

    def meal_plan_rules(self) -> dict[str, int]:
        with self._lock:
            data = self._load()
            return data["meal_plan_rules"]

    def set_meal_plan_rules(self, no_repeat_days: int) -> dict[str, int]:
        with self._lock:
            data = self._load()
            data["meal_plan_rules"] = {"no_repeat_days": no_repeat_days}
            self._prune_recipe_use_history(data)
            self._save(data)
        return {"no_repeat_days": no_repeat_days}

    def user_settings(self) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            return data["user_settings"]

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
            self._prune_recipe_use_history(data)
            self._save(data)

        return {
            "user_settings": {
                "default_diners": default_diners,
                "default_notification_time": default_notification_time,
            },
            "meal_plan_rules": {"no_repeat_days": no_repeat_days},
            "selected_keyword_ids": keyword_ids,
        }

    def list_recipe_uses(self) -> list[dict[str, Any]]:
        """Return current exclusions and prune expired uses on access."""
        with self._lock:
            data = self._load()
            self._prune_recipe_use_history(data)
            if data["recipe_use_history"] != self._data["recipe_use_history"]:
                self._save(data)
            return data["recipe_use_history"]

    def set_recipe_use(
        self, recipe_id: int, used_date: date, source: str = "manual",
        plan_id: int | None = None, entry_id: int | None = None,
    ) -> dict[str, Any]:
        """Explicitly set the last use date without editing a saved plan."""
        record = {
            "recipe_id": recipe_id, "used_date": used_date.isoformat(),
            "source": source, "plan_id": plan_id, "entry_id": entry_id,
        }
        with self._lock:
            data = self._load()
            data["recipe_use_history"] = [
                item for item in data["recipe_use_history"] if item["recipe_id"] != recipe_id
            ]
            data["recipe_use_history"].append(record)
            self._prune_recipe_use_history(data)
            self._save(data)
        return record

    def remove_recipe_use(self, recipe_id: int) -> bool:
        """Remove an exclusion without changing its original plan entry."""
        with self._lock:
            data = self._load()
            before = len(data["recipe_use_history"])
            data["recipe_use_history"] = [
                item for item in data["recipe_use_history"] if item["recipe_id"] != recipe_id
            ]
            if len(data["recipe_use_history"]) == before:
                return False
            self._save(data)
            return True

    def _record_recipe_uses(
        self, data: dict[str, Any], plan_id: int, plan: dict[str, Any],
        previous: dict[str, Any] | None = None,
    ) -> None:
        """Register only new or rescheduled uses; unchanged entries stay removed."""
        self._prune_recipe_use_history(data)
        previous_uses: set[tuple[int, str, int]] = set()
        if previous is not None:
            for old_entry in previous.get("entries", []):
                for old_recipe in old_entry.get("recipes", []):
                    previous_uses.add((old_recipe["id"], old_entry["date"], old_entry["entry_id"]))
        entries = plan.get("entries")
        if not isinstance(entries, list):
            return

        history = data["recipe_use_history"]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("entry_id")
            used_date = entry.get("date")
            if not isinstance(entry_id, int) or not isinstance(used_date, str):
                continue
            try:
                date.fromisoformat(used_date)
            except ValueError:
                continue

            recipes = entry.get("recipes")
            if not isinstance(recipes, list):
                continue
            for recipe in recipes:
                if not isinstance(recipe, dict):
                    continue
                recipe_id = recipe.get("id")
                if not isinstance(recipe_id, int):
                    continue
                if (recipe_id, used_date, entry_id) in previous_uses:
                    continue
                current = next((item for item in history if item["recipe_id"] == recipe_id), None)
                if current is not None and current["used_date"] >= used_date:
                    continue
                if current is not None:
                    history.remove(current)
                history.append({
                    "recipe_id": recipe_id, "used_date": used_date, "source": "plan",
                    "plan_id": plan_id, "entry_id": entry_id,
                })

    def create_meal_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            plan_id = int(data.get("next_meal_plan_id", 1))
            data["next_meal_plan_id"] = plan_id + 1
            payload["plan_id"] = plan_id
            data["meal_plans"][str(plan_id)] = payload
            self._record_recipe_uses(data, plan_id, payload)
            self._save(data)
        return payload

    def get_meal_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            plan = data["meal_plans"].get(str(plan_id))
            return deepcopy(plan) if plan is not None else None

    def list_meal_plans(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            values = [deepcopy(plan) for plan in data["meal_plans"].values()]

            values.sort(key=lambda row: int(row.get("plan_id", 0)), reverse=True)
            return values

    def update_meal_plan(self, plan_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            key = str(plan_id)
            current = data["meal_plans"].get(key)
            if current is None:
                return None
            previous = deepcopy(current)
            current.update(payload)
            data["meal_plans"][key] = current
            self._record_recipe_uses(data, plan_id, current, previous)
            self._save(data)
            return deepcopy(current)

    def delete_meal_plan(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            removed = data["meal_plans"].pop(str(plan_id), None)
            if removed is None:
                return None
            self._save(data)
            return deepcopy(removed)

    def _tandoor_sync_owner(self, plan: dict[str, Any], instance_key: str) -> dict[str, Any] | None:
        parts = instance_key.split(":")
        entry_id = int(parts[1])
        entry = next(row for row in plan["entries"] if row["entry_id"] == entry_id)
        if len(parts) == 4:
            return entry
        return entry["recipes"][int(parts[3])]

    def get_meal_plan_tandoor_sync(self, plan_id: int) -> dict[str, dict[str, Any]]:
        with self._lock:
            data = self._load()
            plan = data["meal_plans"].get(str(plan_id))
            if not isinstance(plan, dict):
                return {}
            sanitized: dict[str, dict[str, Any]] = {}
            for entry in plan["entries"]:
                entry_id = entry["entry_id"]
                for index, recipe in enumerate(entry["recipes"]):
                    if "tandoor_sync" in recipe:
                        sanitized[f"entry:{entry_id}:recipe:{index}:id:{recipe['id']}"] = deepcopy(recipe["tandoor_sync"])
                if "tandoor_sync" in entry:
                    sanitized[f"entry:{entry_id}:mode:{entry['mode']}"] = deepcopy(entry["tandoor_sync"])
            return sanitized

    def set_meal_plan_tandoor_sync(self, plan_id: int, instances: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            data = self._load()
            plan = data["meal_plans"].get(str(plan_id))
            if not isinstance(plan, dict):
                return
            for entry in plan["entries"]:
                entry.pop("tandoor_sync", None)
                for recipe in entry["recipes"]:
                    recipe.pop("tandoor_sync", None)
            for key, value in instances.items():
                owner = self._tandoor_sync_owner(plan, str(key))
                if owner is None:
                    raise ValueError(f"Invalid meal plan sync instance key: {key}")
                owner["tandoor_sync"] = deepcopy(value)
            self._save(data)

    def queue_meal_plan_entry_sync(
        self,
        plan_id: int,
        entry_id: int,
        previous_sync: dict[str, dict[str, Any]],
    ) -> None:
        """Persist an entry sync request until Tandoor acknowledges it."""
        with self._lock:
            data = self._load()
            key = f"{plan_id}:{entry_id}"
            if key not in data["pending_meal_plan_changes"]:
                data["pending_meal_plan_changes"][key] = {
                    "plan_id": plan_id,
                    "entry_id": entry_id,
                    "previous_sync": previous_sync,
                }
                self._save(data)

    def pending_meal_plan_change(self, plan_id: int, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            change = data["pending_meal_plan_changes"].get(f"{plan_id}:{entry_id}")
            return deepcopy(change) if isinstance(change, dict) else None

    def pending_meal_plan_changes(self, plan_id: int) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            return [
                deepcopy(change)
                for change in data["pending_meal_plan_changes"].values()
                if isinstance(change, dict) and change.get("plan_id") == plan_id
            ]

    def clear_pending_meal_plan_change(self, plan_id: int, entry_id: int) -> None:
        with self._lock:
            data = self._load()
            data["pending_meal_plan_changes"].pop(f"{plan_id}:{entry_id}", None)
            self._save(data)

    def queue_meal_plan_sync(
        self,
        plan_id: int,
        previous_sync: dict[str, dict[str, Any]],
        affected_day_start: int,
        affected_day_end: int,
    ) -> None:
        """Persist a reordered day range, coalescing rapid reorders per plan."""
        with self._lock:
            data = self._load()
            key = str(plan_id)
            existing = data["pending_meal_plan_syncs"].get(key)
            revision = existing["revision"] + 1 if isinstance(existing, dict) else 1
            if isinstance(existing, dict):
                affected_day_start = min(affected_day_start, existing["affected_day_start"])
                affected_day_end = max(affected_day_end, existing["affected_day_end"])
            data["pending_meal_plan_syncs"][key] = {
                "plan_id": plan_id,
                "previous_sync": existing["previous_sync"] if isinstance(existing, dict) else previous_sync,
                "revision": revision,
                "affected_day_start": affected_day_start,
                "affected_day_end": affected_day_end,
            }
            self._save(data)

    def pending_meal_plan_sync(self, plan_id: int) -> dict[str, Any] | None:
        with self._lock:
            data = self._load()
            sync = data["pending_meal_plan_syncs"].get(str(plan_id))
            return deepcopy(sync) if isinstance(sync, dict) else None

    def pending_meal_plan_syncs(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            return [
                deepcopy(sync)
                for sync in data["pending_meal_plan_syncs"].values()
                if isinstance(sync, dict)
            ]

    def clear_pending_meal_plan_sync(self, plan_id: int, revision: int) -> None:
        with self._lock:
            data = self._load()
            pending_sync = data["pending_meal_plan_syncs"].get(str(plan_id))
            if isinstance(pending_sync, dict) and pending_sync.get("revision") == revision:
                data["pending_meal_plan_syncs"].pop(str(plan_id), None)
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
            return data["shopping_status_overrides"]

    def set_shopping_item_metadata(self, entry_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            key = str(entry_id)
            metadata = data["shopping_item_metadata"]
            current = metadata.get(key, {})
            current.update(patch)
            metadata[key] = current
            self._save(data)
            return deepcopy(current)

    def delete_shopping_item_metadata(self, entry_id: int) -> None:
        with self._lock:
            data = self._load()
            data["shopping_item_metadata"].pop(str(entry_id), None)
            self._save(data)

    def get_shopping_item_metadata(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            data = self._load()
            return deepcopy(data["shopping_item_metadata"])

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
            return list(deepcopy(data["local_shopping_entries"]).values())

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
        """Remove a local entry and its associated status and metadata."""
        with self._lock:
            data = self._load()
            raw = data.get("local_shopping_entries", {})
            if not isinstance(raw, dict):
                return None
            removed = raw.pop(str(entry_id), None)
            if not isinstance(removed, dict):
                return None
            data["shopping_status_overrides"].pop(str(entry_id), None)
            data["shopping_item_metadata"].pop(str(entry_id), None)
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

    def clear_pending_shopping_changes(self, expected_changes: dict[str, dict[str, Any]] | None = None) -> None:
        with self._lock:
            data = self._load()
            if expected_changes is None:
                data["pending_shopping_changes"] = {}
            else:
                for key, expected_change in expected_changes.items():
                    if data["pending_shopping_changes"].get(key) == expected_change:
                        data["pending_shopping_changes"].pop(key)
            self._save(data)
