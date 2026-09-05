"""Schema-versioned JSON repository for application-owned derived state.

Each public mutation performs a locked read-modify-write and atomically replaces
the state file. The lock is process-local; deployments must use one process per
data directory. Tandoor side effects are coordinated by the domain services.
"""

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
from uuid import uuid4

from app.models.state_schema import default_state_payload
from app.services.state_migrations import StateSchemaError, migrate_and_validate_state
from app.services.sync_event_compaction import compact_sync_event_payload

DEFAULT_STATE_FILENAME = "state.json"
logger = logging.getLogger(__name__)


class Stage2State:
    """Persist meal-plan metadata, shopping overlays, revisions, and sync work."""

    def __init__(
        self,
        data_dir: str,
        sync_event_max_count: int = 2000,
        sync_event_max_age_days: int = 30,
        archive_sync_event_max_count: int = 2000,
        archive_meal_plan_max_count: int = 100,
    ) -> None:
        self.state_file = Path(data_dir) / DEFAULT_STATE_FILENAME
        self.backup_file = self.state_file.with_suffix(f"{self.state_file.suffix}.bak")
        self._sync_event_max_count = sync_event_max_count
        self._sync_event_max_age_days = sync_event_max_age_days
        self._archive_sync_event_max_count = archive_sync_event_max_count
        self._archive_meal_plan_max_count = archive_meal_plan_max_count
        self._lock = Lock()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save(default_state_payload(), advance_revision=False)
        else:
            with self._lock:
                data = self._load()
                self._prune_sync_events(data)
                self._prune_archive(data)
                self._save(data, advance_revision=False)

    def _ensure_archive(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure archive collections exist and contain dictionary records only."""
        raw_archive = data.get("archive")
        archive = raw_archive if isinstance(raw_archive, dict) else {}

        meal_plans = archive.get("meal_plans")
        if not isinstance(meal_plans, list):
            meal_plans = []
        archive["meal_plans"] = [row for row in meal_plans if isinstance(row, dict)]

        sync_events = archive.get("sync_events")
        if not isinstance(sync_events, list):
            sync_events = []
        archive["sync_events"] = [row for row in sync_events if isinstance(row, dict)]

        data["archive"] = archive
        return archive

    def _prune_archive(self, data: dict[str, Any]) -> None:
        """Bound archived plans and events according to configured limits."""
        archive = self._ensure_archive(data)

        meal_plans = archive.get("meal_plans", [])
        if self._archive_meal_plan_max_count > 0 and len(meal_plans) > self._archive_meal_plan_max_count:
            archive["meal_plans"] = meal_plans[-self._archive_meal_plan_max_count :]

        sync_events = archive.get("sync_events", [])
        if self._archive_sync_event_max_count > 0 and len(sync_events) > self._archive_sync_event_max_count:
            archive["sync_events"] = sync_events[-self._archive_sync_event_max_count :]

    def _append_archive_sync_events(self, data: dict[str, Any], events: list[dict[str, Any]]) -> None:
        """Move pruned sync events into the bounded archive collection."""
        if len(events) == 0:
            return
        archive = self._ensure_archive(data)
        archive_events = archive.get("sync_events", [])
        for event in events:
            if isinstance(event, dict):
                archive_events.append(deepcopy(event))
        archive["sync_events"] = archive_events
        self._prune_archive(data)

    def _archive_meal_plan(self, data: dict[str, Any], meal_plan: dict[str, Any], reason: str) -> None:
        """Archive a deleted plan as a defensive historical snapshot."""
        plan_id = meal_plan.get("plan_id")
        if not isinstance(plan_id, int):
            return
        archive = self._ensure_archive(data)
        meal_plans = archive.get("meal_plans", [])
        meal_plans.append(
            {
                "plan_id": plan_id,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "data": deepcopy(meal_plan),
            }
        )
        archive["meal_plans"] = meal_plans
        self._prune_archive(data)

    def _load(self) -> dict[str, Any]:
        """Load and validate the primary state document."""
        return self._load_path(self.state_file)

    def _load_path(self, path: Path) -> dict[str, Any]:
        """Load, migrate, and validate a specific state-file path."""
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)

        if not isinstance(data, dict):
            raise StateSchemaError("Invalid stage2 state payload: expected a JSON object.")

        try:
            return migrate_and_validate_state(data)
        except StateSchemaError:
            logger.exception("stage2_state_validation_failed state_file=%s", path)
            raise

    def _write_payload(self, path: Path, payload: dict[str, Any]) -> None:
        """Atomically write JSON and fsync both file and containing directory."""
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f"{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as fp:
                tmp_path = Path(fp.name)
                json.dump(payload, fp, indent=2, ensure_ascii=True)
                fp.flush()
                os.fsync(fp.fileno())

            os.replace(tmp_path, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _save(self, data: dict[str, Any], advance_revision: bool = True) -> None:
        """Validate and atomically persist state, optionally advancing revision."""
        if advance_revision:
            current_revision = data.get("derived_state_revision", 0)
            data["derived_state_revision"] = int(current_revision) + 1
        payload = migrate_and_validate_state(deepcopy(data))
        if self.state_file.exists():
            self._write_payload(self.backup_file, self._load())
        self._write_payload(self.state_file, payload)

    def restore_backup(self) -> None:
        """Replace primary state with the validated backup snapshot."""
        with self._lock:
            payload = self._load_path(self.backup_file)
            self._write_payload(self.state_file, payload)

    def _parse_event_created_at(self, value: Any) -> datetime | None:
        """Parse event timestamps as UTC for age-based pruning."""
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
        """Drop expired/over-limit events and archive what was removed."""
        raw_events = data.get("shopping_sync_events")
        if not isinstance(raw_events, list):
            data["shopping_sync_events"] = []
            return

        events: list[dict[str, Any]] = [event for event in raw_events if isinstance(event, dict)]
        removed_events: list[dict[str, Any]] = []

        if self._sync_event_max_age_days > 0 and events:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._sync_event_max_age_days)
            kept_by_age: list[dict[str, Any]] = []
            for event in events:
                created_at = self._parse_event_created_at(event.get("created_at"))
                if created_at is None or created_at >= cutoff:
                    kept_by_age.append(event)
                else:
                    removed_events.append(event)
            events = kept_by_age

        if self._sync_event_max_count > 0 and len(events) > self._sync_event_max_count:
            removed_events.extend(events[: -self._sync_event_max_count])
            events = events[-self._sync_event_max_count :]

        data["shopping_sync_events"] = events
        self._append_archive_sync_events(data, removed_events)

    def _record_recipe_uses(self, data: dict[str, Any], meal_plan: dict[str, Any]) -> None:
        """Add unique recipe-use records for the plan's concrete entries."""
        plan_id = meal_plan.get("plan_id")
        entries = meal_plan.get("entries")
        if not isinstance(plan_id, int) or not isinstance(entries, list):
            return

        history = data.get("recipe_use_history")
        if not isinstance(history, list):
            history = []

        known = {
            (
                row.get("recipe_id"),
                row.get("used_date"),
                row.get("plan_id"),
                row.get("entry_id"),
            )
            for row in history
            if isinstance(row, dict)
        }
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            recipe = entry.get("recipe")
            recipe_id = recipe.get("id") if isinstance(recipe, dict) else None
            entry_id = entry.get("entry_id")
            used_date = entry.get("date")
            if not isinstance(recipe_id, int) or not isinstance(entry_id, int) or not isinstance(used_date, str):
                continue
            key = (recipe_id, used_date, plan_id, entry_id)
            if key in known:
                continue
            history.append(
                {
                    "recipe_id": recipe_id,
                    "used_date": used_date,
                    "plan_id": plan_id,
                    "entry_id": entry_id,
                }
            )
            known.add(key)
        data["recipe_use_history"] = history

    def recipe_use_history(self) -> list[dict[str, Any]]:
        """Return a defensive copy of recipe-use records used by plan rules."""
        with self._lock:
            data = self._load()
            history = data.get("recipe_use_history")
            return deepcopy(history) if isinstance(history, list) else []

    def record_meal_plan_recipe_uses(self, plan_id: int) -> None:
        """Confirm recipe history after its authoritative projection is available."""
        with self._lock:
            data = self._load()
            meal_plan = data["meal_plans"].get(str(plan_id))
            if not isinstance(meal_plan, dict):
                return
            self._record_recipe_uses(data, meal_plan)
            self._save(data)

    def current_revision(self) -> int:
        """Read the monotonic revision assigned to the latest saved state."""
        with self._lock:
            data = self._load()
            return int(data.get("derived_state_revision", 0))

    def create_pending_projection(
        self,
        domain: str,
        operation: str,
        payload: dict[str, Any],
        error: str,
    ) -> dict[str, Any]:
        """Persist a retryable upstream projection failure and return its record."""
        with self._lock:
            data = self._load()
            now = datetime.now(timezone.utc).isoformat()
            operation_id = str(uuid4())
            record = {
                "operation_id": operation_id,
                "domain": domain,
                "operation": operation,
                "payload": deepcopy(payload),
                "status": "pending",
                "error": error,
                "created_at": now,
                "updated_at": now,
            }
            pending = data.get("pending_projections")
            if not isinstance(pending, dict):
                pending = {}
            pending[operation_id] = record
            data["pending_projections"] = pending
            self._save(data)
            return deepcopy(record)

    def pending_projections(self) -> list[dict[str, Any]]:
        """List all durable projection failures without exposing mutable state."""
        with self._lock:
            data = self._load()
            pending = data.get("pending_projections")
            if not isinstance(pending, dict):
                return []
            return [deepcopy(row) for row in pending.values() if isinstance(row, dict)]

    def pending_projection(self, operation_id: str) -> dict[str, Any] | None:
        """Return one pending projection by ID, or ``None`` when it is unknown."""
        with self._lock:
            data = self._load()
            pending = data.get("pending_projections")
            if not isinstance(pending, dict):
                return None
            record = pending.get(operation_id)
            return deepcopy(record) if isinstance(record, dict) else None

    def delete_pending_projections(self, operation_ids: set[str]) -> None:
        """Remove acknowledged projection records in one locked state update."""
        with self._lock:
            data = self._load()
            pending = data.get("pending_projections")
            if not isinstance(pending, dict):
                return
            changed = False
            for operation_id in operation_ids:
                if pending.pop(operation_id, None) is not None:
                    changed = True
            if changed:
                self._save(data)

    def selected_keywords(self) -> list[int]:
        """Return the keyword IDs selected for recipe filtering."""
        with self._lock:
            data = self._load()
            return [int(v) for v in data.get("selected_keyword_ids", [])]

    def set_selected_keywords(self, keyword_ids: list[int]) -> list[int]:
        """Replace selected recipe keywords and persist the new filter."""
        with self._lock:
            data = self._load()
            data["selected_keyword_ids"] = keyword_ids
            self._save(data)
        return keyword_ids

    def meal_plan_rules(self) -> dict[str, int]:
        """Return persisted meal-plan generation rules."""
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
        """Persist the no-repeat window used by meal-plan generation."""
        with self._lock:
            data = self._load()
            data["meal_plan_rules"] = {"no_repeat_days": no_repeat_days}
            self._save(data)
        return {"no_repeat_days": no_repeat_days}

    def user_settings(self) -> dict[str, Any]:
        """Return validated user-facing defaults stored in application state."""
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
        """Persist diner and notification defaults as one atomic state mutation."""
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
        """Allocate and persist new plan metadata before its upstream rows are created."""
        with self._lock:
            data = self._load()
            plan_id = int(data.get("next_meal_plan_id", 1))
            data["next_meal_plan_id"] = plan_id + 1
            payload["plan_id"] = plan_id
            data["meal_plans"][str(plan_id)] = payload
            self._save(data)
        return payload

    def get_meal_plan(self, plan_id: int) -> dict[str, Any] | None:
        """Return a defensive copy of one local meal plan when present."""
        with self._lock:
            data = self._load()
            plan = data["meal_plans"].get(str(plan_id))
            return deepcopy(plan) if isinstance(plan, dict) else None

    def list_meal_plans(self) -> list[dict[str, Any]]:
        """Return all local plans newest first without sharing stored objects."""
        with self._lock:
            data = self._load()
            values: list[dict[str, Any]] = []
            for _, plan in data.get("meal_plans", {}).items():
                if isinstance(plan, dict):
                    values.append(deepcopy(plan))

            values.sort(key=lambda row: int(row.get("plan_id", 0)), reverse=True)
            return values

    def update_meal_plan(self, plan_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Merge a validated plan patch without confirming recipe-use history."""
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
        """Delete a local plan, archive it, and remove its sync bookkeeping."""
        with self._lock:
            data = self._load()
            removed = data["meal_plans"].pop(str(plan_id), None)
            if not isinstance(removed, dict):
                return None
            self._archive_meal_plan(data, removed, reason="deleted")
            meal_plan_sync = data.get("meal_plan_instance_sync")
            if isinstance(meal_plan_sync, dict):
                meal_plan_sync.pop(str(plan_id), None)
            self._save(data)
            return deepcopy(removed)

    def get_meal_plan_instance_sync(self, plan_id: int) -> dict[str, dict[str, Any]]:
        """Return sanitized per-instance upstream IDs for one meal plan."""
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
        """Replace one plan's instance-sync map with a defensive sanitized copy."""
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
        """Allocate the next positive meal-plan entry ID transactionally."""
        with self._lock:
            data = self._load()
            entry_id = int(data.get("next_entry_id", 1))
            data["next_entry_id"] = entry_id + 1
            self._save(data)
            return entry_id

    def append_sync_event(self, operation: str, payload: dict[str, Any]) -> int:
        """Append a compact shopping event and return its cursor."""
        with self._lock:
            data = self._load()
            event_id = int(data.get("next_sync_event_id", 1))
            data["next_sync_event_id"] = event_id + 1
            compact_payload = compact_sync_event_payload(operation, payload)
            event = {
                "cursor": event_id,
                "operation": operation,
                "payload": compact_payload,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data["shopping_sync_events"].append(event)
            self._prune_sync_events(data)
            self._save(data)
            return event_id

    def sync_events_since(self, cursor: int) -> list[dict[str, Any]]:
        """Return immutable copies of shopping events after a cursor."""
        with self._lock:
            data = self._load()
            return [
                deepcopy(event)
                for event in data.get("shopping_sync_events", [])
                if int(event.get("cursor", 0)) > cursor
            ]

    def current_sync_cursor(self) -> int:
        """Return the cursor of the newest persisted shopping event."""
        with self._lock:
            data = self._load()
            return max(int(data.get("next_sync_event_id", 1)) - 1, 0)

    def set_shopping_status(self, entry_id: int, status: str) -> None:
        """Persist the app-owned status override for a shopping entry."""
        with self._lock:
            data = self._load()
            data["shopping_status_overrides"][str(entry_id)] = status
            self._save(data)

    def get_shopping_statuses(self) -> dict[str, str]:
        """Return all persisted shopping status overrides by string ID."""
        with self._lock:
            data = self._load()
            raw = data.get("shopping_status_overrides", {})
            if not isinstance(raw, dict):
                return {}
            return {str(k): str(v) for k, v in raw.items()}

    def delete_shopping_status(self, entry_id: int) -> None:
        """Remove one status override when an entry is deleted."""
        with self._lock:
            data = self._load()
            statuses = data.get("shopping_status_overrides")
            if isinstance(statuses, dict) and statuses.pop(str(entry_id), None) is not None:
                self._save(data)

    def set_shopping_item_metadata(self, entry_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge reminder or editor metadata for one shopping entry."""
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
        """Remove metadata associated with a deleted shopping entry."""
        with self._lock:
            data = self._load()
            raw = data.get("shopping_item_metadata")
            if isinstance(raw, dict):
                raw.pop(str(entry_id), None)
                self._save(data)

    def get_shopping_item_metadata(self) -> dict[str, dict[str, Any]]:
        """Return sanitized metadata records without mutable storage references."""
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
        """Allocate the next negative ID reserved for a local shopping item."""
        with self._lock:
            data = self._load()
            next_id = int(data.get("next_local_shopping_entry_id", -1))
            if next_id >= 0:
                next_id = -1
            data["next_local_shopping_entry_id"] = next_id - 1
            self._save(data)
            return next_id

    def list_local_shopping_entries(self) -> list[dict[str, Any]]:
        """Return all locally persisted shopping entries as defensive copies."""
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
        """Return one local shopping entry, if the ID belongs to local storage."""
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
        """Create or replace a local shopping entry and persist the change."""
        with self._lock:
            data = self._load()
            if not isinstance(data.get("local_shopping_entries"), dict):
                data["local_shopping_entries"] = {}
            data["local_shopping_entries"][str(entry_id)] = deepcopy(payload)
            self._save(data)
            return deepcopy(payload)

    def update_local_shopping_entry(self, entry_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Merge a local shopping patch, returning ``None`` for an unknown ID."""
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
        """Delete and return one local shopping entry when it exists."""
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
