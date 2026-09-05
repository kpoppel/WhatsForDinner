from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, Query, UploadFile

from app.config import settings
from app.models.contracts import (
    GenerateMealPlanRequest,
    MealPlanEntryCreateRequest,
    MealPlanEntryPatchRequest,
    MealPlanPatchRequest,
    MealPlanRulesRequest,
    SetSelectedKeywordsRequest,
    SettingsRequest,
    ShoppingEntryCreateRequest,
    ShoppingEntryPatchRequest,
    ShoppingListOcrResponse,
    ShoppingSyncRequest,
    UserSettingsRequest,
)
from app.services.meal_plan_service import MealPlanService
from app.services.ocr_client import GeminiOcrClient, OcrError
from app.services.shopping_service import ShoppingService
from app.services.server_state import ServerState
from app.services.tandoor_client import TandoorClient, TandoorError

router = APIRouter(tags=["mobile-api"])
logger = logging.getLogger(__name__)
meal_plan_sync_locks: dict[int, asyncio.Lock] = {}
shopping_sync_lock = asyncio.Lock()
SYNC_RETRY_DELAY_SECONDS = 5
SYNC_MAX_RETRIES = 10
client = TandoorClient()
server_state = ServerState(
    settings.stage2_data_dir,
)


def _shopping_service() -> ShoppingService:
    return ShoppingService(server_state, client)


def _meal_plan_service() -> MealPlanService:
    return MealPlanService(server_state, client)


async def _sync_pending_meal_plan_entry(plan_id: int, entry_id: int) -> None:
    if plan_id not in meal_plan_sync_locks:
        meal_plan_sync_locks[plan_id] = asyncio.Lock()
    async with meal_plan_sync_locks[plan_id]:
        for retry_count in range(SYNC_MAX_RETRIES + 1):
            try:
                await _meal_plan_service().sync_pending_entry(
                    plan_id,
                    entry_id,
                    _ensure_tandoor_writes_enabled,
                )
                return
            except HTTPException as exc:
                logger.warning("meal_plan_entry_sync_deferred plan_id=%s entry_id=%s error=%s", plan_id, entry_id, exc)
                return
            except TandoorError as exc:
                if retry_count == SYNC_MAX_RETRIES:
                    logger.warning("meal_plan_entry_sync_deferred plan_id=%s entry_id=%s retries=%s error=%s", plan_id, entry_id, retry_count, exc)
                    return
                logger.warning("meal_plan_entry_sync_retry plan_id=%s entry_id=%s retry=%s error=%s", plan_id, entry_id, retry_count + 1, exc)
                await asyncio.sleep(SYNC_RETRY_DELAY_SECONDS)


async def _sync_pending_meal_plan(plan_id: int) -> None:
    if plan_id not in meal_plan_sync_locks:
        meal_plan_sync_locks[plan_id] = asyncio.Lock()
    async with meal_plan_sync_locks[plan_id]:
        for retry_count in range(SYNC_MAX_RETRIES + 1):
            try:
                await _meal_plan_service().sync_pending_plan(plan_id, _ensure_tandoor_writes_enabled)
                return
            except HTTPException as exc:
                logger.warning("meal_plan_sync_deferred plan_id=%s error=%s", plan_id, exc)
                return
            except TandoorError as exc:
                if retry_count == SYNC_MAX_RETRIES:
                    logger.warning("meal_plan_sync_deferred plan_id=%s retries=%s error=%s", plan_id, retry_count, exc)
                    return
                logger.warning("meal_plan_sync_retry plan_id=%s retry=%s error=%s", plan_id, retry_count + 1, exc)
                await asyncio.sleep(SYNC_RETRY_DELAY_SECONDS)


async def _sync_pending_shopping_changes() -> None:
    async with shopping_sync_lock:
        for retry_count in range(SYNC_MAX_RETRIES + 1):
            try:
                response = await _shopping_service().apply_sync_changes(
                    changes=[],
                    ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
                    extract_reminder_patch=_extract_reminder_patch,
                    build_local_entry_payload=_build_local_entry_payload,
                    local_store_group_payload=_local_store_group_payload,
                    status_to_tandoor_fields=_status_to_tandoor_fields,
                    effective_status=_effective_status,
                )
            except HTTPException as exc:
                logger.warning("shopping_sync_deferred error=%s", exc)
                return
            except TandoorError as exc:
                response = {"deferred": True}
                error = exc
            else:
                error = None

            if not response["deferred"]:
                return
            if retry_count == SYNC_MAX_RETRIES:
                logger.warning("shopping_sync_deferred retries=%s error=%s", retry_count, error)
                return
            logger.warning("shopping_sync_retry retry=%s error=%s", retry_count + 1, error)
            await asyncio.sleep(SYNC_RETRY_DELAY_SECONDS)


def _ocr_client() -> GeminiOcrClient:
    return GeminiOcrClient()

SHOPPING_STATUSES = {"remaining", "skipped", "completed"}
OCR_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _ensure_tandoor_writes_enabled(operation: str) -> None:
    if settings.tandoor_write_enabled:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            "Tandoor write operations are disabled by configuration "
            f"(operation={operation}, TANDOOR_WRITE_ENABLED=false)."
        ),
    )


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [row for row in results if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _effective_status(entry: dict[str, Any], overrides: dict[str, str]) -> str:
    override = overrides.get(str(entry.get("id")))
    if override in SHOPPING_STATUSES:
        return override
    if bool(entry.get("checked")):
        return "completed"
    if _has_active_delay(entry):
        return "skipped"
    return "remaining"


def _has_active_delay(entry: dict[str, Any]) -> bool:
    raw = entry.get("delay_until")
    if raw is None:
        return False

    if isinstance(raw, date):
        return raw >= date.today()

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return False
        try:
            delay_date = date.fromisoformat(text[:10])
        except ValueError:
            return False
        return delay_date >= date.today()

    return False


def _status_to_tandoor_fields(status: str) -> dict[str, Any]:
    if status == "completed":
        return {
            "checked": True,
            "delay_until": None,
        }
    if status == "skipped":
        return {
            "checked": False,
            # Delay to tomorrow so item is postponed in Tandoor's shopping flow.
            "delay_until": (date.today() + timedelta(days=1)).isoformat(),
        }
    return {
        "checked": False,
        "delay_until": None,
    }


def _iso_date_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    return None


def _is_reminder_due(reminder_enabled: bool, reminder_date: str | None) -> bool:
    if not reminder_enabled or reminder_date is None:
        return False
    try:
        due_day = date.fromisoformat(reminder_date)
    except ValueError:
        return False
    return due_day <= date.today()


def _normalize_store_group(raw_group: Any) -> dict[str, Any]:
    if isinstance(raw_group, dict):
        group_id = raw_group.get("id")
        group_name = raw_group.get("name")
        return {
            "id": group_id if isinstance(group_id, int) else None,
            "name": str(group_name or "General"),
        }
    if isinstance(raw_group, str):
        text = raw_group.strip()
        return {
            "id": None,
            "name": text or "General",
        }
    if isinstance(raw_group, int):
        return {
            "id": raw_group,
            "name": str(raw_group),
        }
    return {
        "id": None,
        "name": "General",
    }


def _recipe_context_from_entry(entry: dict[str, Any]) -> str:
    for key in ("recipe_name", "recipe", "meal", "meal_title"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            text = value.get("name") or value.get("title")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return "Unassigned"


def _recipe_url(recipe_id: int | None) -> str | None:
    if recipe_id is None:
        return None
    return f"{settings.tandoor_base_url.rstrip('/')}/recipe/{recipe_id}"


def _enrich_plan_recipe_urls(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return plan
    enriched = dict(plan)
    entries = plan.get("entries")
    if not isinstance(entries, list):
        return enriched

    enriched_entries: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict):
            enriched_entries.append(entry)
            continue
        enriched_entry = dict(entry)
        recipes = entry.get("recipes")
        if isinstance(recipes, list):
            enriched_entry["recipes"] = [
                {
                    **recipe,
                    "url": _recipe_url(recipe.get("id")) if isinstance(recipe.get("id"), int) else None,
                }
                for recipe in recipes
                if isinstance(recipe, dict)
            ]
        enriched_entries.append(enriched_entry)

    enriched["entries"] = enriched_entries
    return enriched


def _normalize_recipe_payload(raw_recipe: Any, fallback_name: str) -> dict[str, Any]:
    recipe_id: int | None = None
    recipe_name = fallback_name
    recipe_image = ""

    if isinstance(raw_recipe, dict):
        raw_id = raw_recipe.get("id")
        if isinstance(raw_id, int):
            recipe_id = raw_id

        raw_name = raw_recipe.get("name") or raw_recipe.get("title")
        if isinstance(raw_name, str) and raw_name.strip():
            recipe_name = raw_name.strip()

        raw_image = raw_recipe.get("image")
        if isinstance(raw_image, str):
            recipe_image = raw_image
        elif raw_image is not None:
            recipe_image = str(raw_image)

    return {
        "id": recipe_id,
        "name": recipe_name,
        "image": recipe_image,
        "url": _recipe_url(recipe_id),
    }


def _recipe_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fallback_name = _recipe_context_from_entry(entry)
    list_recipe_data = entry.get("list_recipe_data") if isinstance(entry.get("list_recipe_data"), dict) else {}
    recipe_data = list_recipe_data.get("recipe_data") if isinstance(list_recipe_data.get("recipe_data"), dict) else None
    if isinstance(recipe_data, dict):
        return _normalize_recipe_payload(recipe_data, fallback_name)

    for key in ("recipe", "meal"):
        candidate = entry.get(key)
        if isinstance(candidate, dict):
            return _normalize_recipe_payload(candidate, fallback_name)

    return _normalize_recipe_payload(None, fallback_name)


def _normalize_shopping_entry(
    entry: dict[str, Any],
    status: str,
    reminder_meta: dict[str, Any],
) -> dict[str, Any]:
    food = entry.get("food") if isinstance(entry.get("food"), dict) else {}
    unit = entry.get("unit") if isinstance(entry.get("unit"), dict) else {}

    ingredient_type = (
        str(food.get("category") or food.get("food_type") or food.get("type") or "Other")
    )
    store_group = _normalize_store_group(
        food.get("supermarket_category") or food.get("supermarket") or food.get("store_group")
    )
    reminder_enabled = bool(reminder_meta.get("reminder_enabled", False))
    reminder_date = _iso_date_or_none(reminder_meta.get("reminder_date"))
    reminder_text = str(reminder_meta.get("reminder_text") or "")
    raw_food_id = food.get("id")
    food_id = raw_food_id if isinstance(raw_food_id, int) else None
    recipe = _recipe_from_entry(entry)

    return {
        "id": entry.get("id"),
        "food_id": food_id,
        "name": food.get("name") or entry.get("name") or "Unnamed",
        "amount": entry.get("amount"),
        "unit": unit.get("name") or entry.get("unit") or "",
        "status": status,
        "ingredient_type": ingredient_type,
        "store_group": store_group,
        "recipe": recipe,
        "recipe_context": _recipe_context_from_entry(entry),
        "reminder_enabled": reminder_enabled,
        "reminder_date": reminder_date,
        "reminder_text": reminder_text,
        "reminder_due": _is_reminder_due(reminder_enabled, reminder_date),
        "raw": entry,
    }


def _group_section(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        value = item.get(key)
        if key == "store_group" and isinstance(value, dict):
            group = str(value.get("id") or value.get("name") or "Other")
        else:
            group = str(value or "Other")
        grouped.setdefault(group, []).append(item)
    return grouped


def _extract_reminder_patch(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    patch: dict[str, Any] = {}
    touched = False

    if "reminder_enabled" in payload:
        value = payload.pop("reminder_enabled")
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="reminder_enabled must be a boolean.")
        patch["reminder_enabled"] = value
        touched = True

    if "reminder_date" in payload:
        raw = payload.pop("reminder_date")
        normalized = _iso_date_or_none(raw)
        if raw is not None and normalized is None:
            raise HTTPException(status_code=400, detail="reminder_date must be YYYY-MM-DD or null.")
        patch["reminder_date"] = normalized
        touched = True

    if "reminder_text" in payload:
        raw_text = payload.pop("reminder_text")
        if raw_text is None:
            patch["reminder_text"] = ""
        elif isinstance(raw_text, str):
            patch["reminder_text"] = raw_text.strip()
        else:
            raise HTTPException(status_code=400, detail="reminder_text must be a string.")
        touched = True

    return patch, touched


def _local_store_group_payload(raw: Any) -> dict[str, Any]:
    normalized = _normalize_store_group(raw)
    return {
        "id": normalized.get("id"),
        "name": str(normalized.get("name") or "General"),
    }


def _build_local_entry_payload(entry_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    raw_name = payload.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise HTTPException(status_code=400, detail="name is required for ad_hoc items.")

    amount = payload.get("amount")
    if amount is None:
        amount = 0
    if not isinstance(amount, (int, float)):
        raise HTTPException(status_code=400, detail="amount must be numeric for ad_hoc items.")

    raw_unit = payload.get("unit")
    if raw_unit is None:
        unit = ""
    elif isinstance(raw_unit, str):
        unit = raw_unit.strip()
    else:
        raise HTTPException(status_code=400, detail="unit must be a string.")

    raw_category = payload.get("ingredient_type")
    if raw_category is None:
        ingredient_type = "Other"
    elif isinstance(raw_category, str) and raw_category.strip():
        ingredient_type = raw_category.strip()
    else:
        raise HTTPException(status_code=400, detail="ingredient_type must be a non-empty string.")

    raw_recipe_context = payload.get("recipe_context")
    if raw_recipe_context is None:
        recipe_context = "Unassigned"
    elif isinstance(raw_recipe_context, str) and raw_recipe_context.strip():
        recipe_context = raw_recipe_context.strip()
    else:
        raise HTTPException(status_code=400, detail="recipe_context must be a non-empty string.")

    raw_food_id = payload.get("food_id")
    food_id = raw_food_id if isinstance(raw_food_id, int) else None
    recipe = _normalize_recipe_payload(payload.get("recipe"), recipe_context)

    return {
        "id": entry_id,
        "source": "local",
        "food_id": food_id,
        "name": raw_name.strip(),
        "amount": amount,
        "unit": unit,
        "ingredient_type": ingredient_type,
        "store_group": _local_store_group_payload(payload.get("store_group")),
        "recipe": recipe,
        "recipe_context": recipe_context,
    }


def _normalize_local_shopping_entry(
    entry: dict[str, Any],
    status: str,
    reminder_meta: dict[str, Any],
) -> dict[str, Any]:
    reminder_enabled = bool(reminder_meta.get("reminder_enabled", False))
    reminder_date = _iso_date_or_none(reminder_meta.get("reminder_date"))
    reminder_text = str(reminder_meta.get("reminder_text") or "")
    raw_food_id = entry.get("food_id")
    food_id = raw_food_id if isinstance(raw_food_id, int) else None
    recipe_context = str(entry.get("recipe_context") or "Unassigned")
    recipe = _normalize_recipe_payload(entry.get("recipe"), recipe_context)
    return {
        "id": entry.get("id"),
        "food_id": food_id,
        "name": str(entry.get("name") or "Unnamed"),
        "amount": entry.get("amount"),
        "unit": str(entry.get("unit") or ""),
        "status": status,
        "ingredient_type": str(entry.get("ingredient_type") or "Other"),
        "store_group": _normalize_store_group(entry.get("store_group")),
        "recipe": recipe,
        "recipe_context": recipe_context,
        "reminder_enabled": reminder_enabled,
        "reminder_date": reminder_date,
        "reminder_text": reminder_text,
        "reminder_due": _is_reminder_due(reminder_enabled, reminder_date),
        "raw": {"id": entry.get("id"), "source": "local", "name": entry.get("name")},
    }


def _build_shopping_view(entries: list[dict[str, Any]]) -> dict[str, Any]:
    overrides = server_state.get_shopping_statuses()
    metadata = server_state.get_shopping_item_metadata()
    local_entries = server_state.list_local_shopping_entries()
    pending_changes = server_state.pending_shopping_changes()
    sectioned: dict[str, list[dict[str, Any]]] = {
        "remaining": [],
        "skipped": [],
        "completed": [],
    }

    for entry in entries:
        entry_id = entry.get("id")
        pending = pending_changes.pop(str(entry_id), None) if isinstance(entry_id, int) else None
        if isinstance(pending, dict) and pending.get("operation") == "delete":
            continue
        if isinstance(pending, dict) and pending.get("operation") == "update":
            patch = pending.get("payload")
            if isinstance(patch, dict):
                entry = {**entry, **patch}
                status_override = patch.get("status")
                if isinstance(status_override, str) and status_override in SHOPPING_STATUSES:
                    overrides[str(entry_id)] = status_override
        meta = metadata.get(str(entry_id), {}) if isinstance(entry_id, int) else {}
        status = _effective_status(entry, overrides)
        normalized = _normalize_shopping_entry(entry, status, meta if isinstance(meta, dict) else {})
        sectioned[status].append(normalized)

    for entry in local_entries:
        entry_id = entry.get("id")
        if not isinstance(entry_id, int):
            continue
        status_value = str(entry.get("status") or "remaining")
        status = status_value if status_value in SHOPPING_STATUSES else "remaining"
        meta = metadata.get(str(entry_id), {})
        normalized = _normalize_local_shopping_entry(entry, status, meta if isinstance(meta, dict) else {})
        sectioned[status].append(normalized)

    grouped_by_type = {
        section: _group_section(items, "ingredient_type")
        for section, items in sectioned.items()
    }
    grouped_by_store = {
        section: _group_section(items, "store_group")
        for section, items in sectioned.items()
    }

    return {
        "sections": sectioned,
        "grouped": {
            "ingredient_type": grouped_by_type,
            "store_layout": grouped_by_store,
        },
    }


def _parse_plan_start_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _stored_plan_sort_key(plan: dict[str, Any]) -> tuple:
    today = date.today()
    start = _parse_plan_start_date(plan.get("start_date"))
    raw_id = plan.get("plan_id")
    plan_id = raw_id if isinstance(raw_id, int) else 0

    if start is None:
        return (10**9, 1, 0, -plan_id)

    # Check if today falls within this plan's date range
    length_days = plan.get("length_days")
    if isinstance(length_days, int) and length_days > 0:
        end = start + timedelta(days=length_days - 1)
        if start <= today <= end:
            # Plan contains today - prioritize it (comes first)
            return (0, -plan_id)

    # Plan does not contain today - sort by distance from today
    diff_days = (start - today).days
    distance = abs(diff_days)
    is_future_or_today = 0 if diff_days >= 0 else 1
    return (1, distance, is_future_or_today, -start.toordinal(), -plan_id)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/recipes")
async def recipes(
    search: str | None = Query(default=None, description="Search term"),
    limit: int = Query(default=20, ge=1, le=100),
    keyword_ids: list[int] | None = Query(
        default=None,
        description="Filter by keyword IDs from /recipe-tags.",
    ),
) -> dict:
    try:
        data = await client.list_recipes(
            search=search,
            limit=limit,
            keyword_ids=keyword_ids,
        )
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/recipe-tags")
async def recipe_tags() -> dict:
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/today-meal")
async def today_meal() -> dict:
    try:
        data = await client.list_recipes(limit=10)
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            raise HTTPException(status_code=404, detail="No recipes found.")

        recipe_id = results[0].get("id") if isinstance(results[0], dict) else None
        if not isinstance(recipe_id, int):
            raise HTTPException(status_code=502, detail="Recipe payload missing ID.")

        recipe_detail = await client.get_recipe(recipe_id)
        meal = TandoorClient.normalize_recipe(recipe_detail)
        return {
            "source": "tandoor",
            "id": meal["id"],
            "title": meal["title"],
            "ingredients": meal["ingredients"],
            "steps": meal["steps"],
        }
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc




@router.get("/config/keywords")
async def config_keywords() -> dict:
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/config/keywords/selected")
async def selected_keywords() -> dict:
    return {
        "source": "local-state",
        "selected_keyword_ids": server_state.selected_keywords(),
    }


@router.put("/config/keywords/selected")
async def set_selected_keywords(payload: SetSelectedKeywordsRequest = Body(...)) -> dict:
    keyword_ids = sorted({int(v) for v in payload.keyword_ids})

    server_state.set_selected_keywords(keyword_ids)
    return {
        "source": "local-state",
        "selected_keyword_ids": keyword_ids,
    }


@router.get("/config/meal-plan-rules")
async def get_meal_plan_rules() -> dict:
    rules = server_state.meal_plan_rules()
    return {
        "source": "local-state",
        "data": rules,
    }


@router.get("/config/user-settings")
async def get_user_settings() -> dict:
    settings_data = server_state.user_settings()
    return {
        "source": "local-state",
        "data": settings_data,
    }


@router.put("/config/user-settings")
async def set_user_settings(payload: UserSettingsRequest = Body(...)) -> dict:
    default_diners = int(payload.default_diners)
    default_notification_time = payload.default_notification_time.strip()

    saved = server_state.set_user_settings(default_diners, default_notification_time)
    return {
        "source": "local-state",
        "data": saved,
    }


@router.put("/config/meal-plan-rules")
async def set_meal_plan_rules(payload: MealPlanRulesRequest = Body(...)) -> dict:
    no_repeat_days = int(payload.no_repeat_days)

    rules = server_state.set_meal_plan_rules(no_repeat_days)
    return {
        "source": "local-state",
        "data": rules,
    }


@router.put("/config/settings")
async def set_settings(payload: SettingsRequest = Body(...)) -> dict:
    default_diners = int(payload.default_diners)
    default_notification_time = payload.default_notification_time.strip()
    no_repeat_days = int(payload.no_repeat_days)
    keyword_ids = sorted({int(value) for value in payload.keyword_ids})

    return {
        "source": "local-state",
        "data": server_state.set_settings(
            default_diners,
            default_notification_time,
            no_repeat_days,
            keyword_ids,
        ),
    }


@router.post("/meal-plans/generate")
async def generate_meal_plan(payload: GenerateMealPlanRequest = Body(...)) -> dict:
    start_day = payload.start_date
    length_days = int(payload.length_days)
    configured_user_settings = server_state.user_settings()
    configured_default_diners = configured_user_settings.get("default_diners")
    if not isinstance(configured_default_diners, int):
        configured_default_diners = 2

    raw_diners = payload.diners
    if raw_diners is None:
        diners = configured_default_diners
    else:
        try:
            diners = int(raw_diners)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="diners must be an integer.") from exc

    if diners < 1 or diners > 20:
        raise HTTPException(status_code=400, detail="diners must be within 1..20.")

    raw_keyword_ids = payload.keyword_ids
    if isinstance(raw_keyword_ids, list) and raw_keyword_ids:
        keyword_ids = [int(v) for v in raw_keyword_ids]
    else:
        keyword_ids = server_state.selected_keywords()

    configured_rules = server_state.meal_plan_rules()
    raw_no_repeat = payload.no_repeat_days
    if raw_no_repeat is None:
        no_repeat_days = int(configured_rules.get("no_repeat_days", 30))
    else:
        try:
            no_repeat_days = int(raw_no_repeat)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="no_repeat_days must be an integer.") from exc

    if no_repeat_days < 0:
        raise HTTPException(status_code=400, detail="no_repeat_days must be >= 0.")

    return await _meal_plan_service().generate_plan(
        start_day=start_day,
        length_days=length_days,
        diners=diners,
        constraints={
            "leftover_days": payload.constraints.leftover_days,
            "takeout_days": payload.constraints.takeout_days,
            "empty_days": payload.constraints.empty_days,
        },
        keyword_ids=keyword_ids,
        no_repeat_days=no_repeat_days,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.get("/meal-plans/stored")
async def list_stored_meal_plans(background_tasks: BackgroundTasks) -> dict:
    for pending_sync in server_state.pending_meal_plan_syncs():
        background_tasks.add_task(_sync_pending_meal_plan, pending_sync["plan_id"])
    for plan in server_state.list_meal_plans():
        for pending_change in server_state.pending_meal_plan_changes(int(plan["plan_id"])):
            background_tasks.add_task(
                _sync_pending_meal_plan_entry,
                pending_change["plan_id"],
                pending_change["entry_id"],
            )

    plans = server_state.list_meal_plans()
    summary: list[dict[str, Any]] = []
    for plan in plans:
        entries = plan.get("entries") if isinstance(plan.get("entries"), list) else []
        summary.append(
            {
                "plan_id": plan.get("plan_id"),
                "start_date": plan.get("start_date"),
                "length_days": plan.get("length_days"),
                "diners": plan.get("diners"),
                "entry_count": len(entries),
                "keyword_ids": plan.get("keyword_ids", []),
            }
        )

    summary.sort(key=_stored_plan_sort_key)

    return {
        "source": "local-state",
        "count": len(summary),
        "data": summary,
    }


@router.get("/meal-plans/{plan_id}")
async def get_meal_plan_stage2(plan_id: int, background_tasks: BackgroundTasks) -> dict:
    plan = server_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")
    if server_state.pending_meal_plan_sync(plan_id) is not None:
        background_tasks.add_task(_sync_pending_meal_plan, plan_id)
    for pending_change in server_state.pending_meal_plan_changes(plan_id):
        background_tasks.add_task(_sync_pending_meal_plan_entry, plan_id, pending_change["entry_id"])
    return {"source": "local-state", "data": _enrich_plan_recipe_urls(plan)}


@router.delete("/meal-plans/stored/{plan_id}")
async def delete_stored_meal_plan(plan_id: int) -> dict:
    return await _meal_plan_service().delete_plan(
        plan_id,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.patch("/meal-plans/{plan_id}")
async def patch_meal_plan_stage2(plan_id: int, payload: MealPlanPatchRequest = Body(...)) -> dict:
    return await _meal_plan_service().patch_plan(
        plan_id,
        payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.post("/meal-plans/{plan_id}/entries")
async def add_meal_plan_entry(plan_id: int, payload: MealPlanEntryCreateRequest = Body(...)) -> dict:
    return await _meal_plan_service().add_entry(
        plan_id,
        payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.patch("/meal-plans/{plan_id}/entries/{entry_id}")
async def patch_meal_plan_entry(
    plan_id: int,
    entry_id: int,
    background_tasks: BackgroundTasks,
    payload: MealPlanEntryPatchRequest = Body(...),
) -> dict:
    request_payload = payload.model_dump(mode="python", exclude_unset=True)
    result = await _meal_plan_service().patch_entry(
        plan_id,
        entry_id,
        request_payload,
        defer_tandoor_sync=True,
    )
    if "target_day_index" in request_payload:
        background_tasks.add_task(_sync_pending_meal_plan, plan_id)
    else:
        background_tasks.add_task(_sync_pending_meal_plan_entry, plan_id, entry_id)
    return result


@router.delete("/meal-plans/{plan_id}/entries/{entry_id}")
async def delete_meal_plan_entry(plan_id: int, entry_id: int) -> dict:
    return await _meal_plan_service().delete_entry(
        plan_id,
        entry_id,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.post("/meal-plans/{plan_id}/shopping-list")
async def meal_plan_to_shopping_list(
    plan_id: int,
    mode: str = Query(default="sync"),
) -> dict:
    if mode not in {"sync", "regenerate_missing"}:
        raise HTTPException(status_code=400, detail="mode must be 'sync' or 'regenerate_missing'.")

    return await _meal_plan_service().generate_shopping_from_plan(
        plan_id=plan_id,
        mode=mode,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        build_shopping_view=_build_shopping_view,
    )


@router.get("/shopping-list/view")
async def shopping_list_view(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=300, ge=1, le=1000),
) -> dict:
    shopping_service = _shopping_service()
    pending_changes = list(server_state.pending_shopping_changes().values())
    if pending_changes:
        background_tasks.add_task(_sync_pending_shopping_changes)
    return await shopping_service.get_view(
        limit=limit,
        extract_results=_extract_results,
        build_shopping_view=_build_shopping_view,
    )


@router.post("/shopping-list/entries")
async def shopping_entries_stage2_create(payload: ShoppingEntryCreateRequest = Body(...)) -> dict:
    return await _shopping_service().create_entry(
        payload=payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        extract_reminder_patch=_extract_reminder_patch,
        build_local_entry_payload=_build_local_entry_payload,
        status_to_tandoor_fields=_status_to_tandoor_fields,
        operation_name="shopping_entries_stage2_create",
    )


@router.patch("/shopping-list/entries/{entry_id}")
async def shopping_entries_stage2_update(
    entry_id: int,
    payload: ShoppingEntryPatchRequest = Body(...),
) -> dict:
    return await _shopping_service().update_entry(
        entry_id=entry_id,
        payload=payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        extract_reminder_patch=_extract_reminder_patch,
        local_store_group_payload=_local_store_group_payload,
        status_to_tandoor_fields=_status_to_tandoor_fields,
        effective_status=_effective_status,
        operation_name="shopping_entries_stage2_update",
    )


@router.delete("/shopping-list/entries/{entry_id}")
async def shopping_entries_stage2_delete(entry_id: int) -> dict:
    return await _shopping_service().delete_entry(
        entry_id=entry_id,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        operation_name="shopping_entries_stage2_delete",
    )


@router.post("/shopping-list/ocr", response_model=ShoppingListOcrResponse)
async def shopping_list_ocr(image: UploadFile = File(...)) -> ShoppingListOcrResponse:
    if not settings.google_llm_api_key:
        raise HTTPException(
            status_code=503,
            detail="OCR is not configured (GOOGLE_LLM_API_KEY missing).",
        )
    content_type = image.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    image_bytes = await image.read()
    if len(image_bytes) > OCR_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large.")

    try:
        text = await _ocr_client().transcribe_handwritten_list(image_bytes, content_type)
    except OcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    items = [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip().lstrip("-*•").strip())
    ]
    return ShoppingListOcrResponse(items=items)


@router.post("/shopping-list/sync")
async def shopping_sync_post(
    background_tasks: BackgroundTasks,
    payload: ShoppingSyncRequest = Body(...),
) -> dict:
    server_state.set_pending_shopping_changes([change.model_dump(mode="python") for change in payload.changes])
    background_tasks.add_task(_sync_pending_shopping_changes)
    return {
        "source": "local-state",
        "deferred": True,
        "applied": [],
        "rejected": [],
    }
