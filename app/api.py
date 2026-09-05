"""Versioned FastAPI routes and API-facing model transformations.

Routes validate transport contracts and delegate mutations to domain services.
Normalization helpers translate Tandoor payloads into stable client view models;
they do not own persistence or synchronization policy.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile

from app.config import settings
from app.models.contracts import (
    GenerateMealPlanRequest,
    MealPlanEntryCreateRequest,
    MealPlanEntryPatchRequest,
    MealPlanPatchRequest,
    MealPlanRulesRequest,
    SetSelectedKeywordsRequest,
    ShoppingEntryCreateRequest,
    ShoppingEntryPatchRequest,
    ShoppingListOcrResponse,
    ShoppingSyncRequest,
    UserSettingsRequest,
)
from app.services.meal_plan_service import MealPlanService
from app.services.ocr_client import GeminiOcrClient, OcrError
from app.services.shopping_service import ShoppingService
from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorClient, TandoorError

router = APIRouter(tags=["mobile-api"])
client = TandoorClient()
stage2_state = Stage2State(
    settings.stage2_data_dir,
    sync_event_max_count=settings.stage2_sync_event_max_count,
    sync_event_max_age_days=settings.stage2_sync_event_max_age_days,
)


@cache
def _shopping_service_for(state: Stage2State, tandoor_client: TandoorClient) -> ShoppingService:
    """Return the cached shopping service for a state/client pair."""
    return ShoppingService(state, tandoor_client)


def _shopping_service() -> ShoppingService:
    """Resolve the process-wide shopping service used by API handlers."""
    return _shopping_service_for(stage2_state, client)


@cache
def _meal_plan_service_for(state: Stage2State, tandoor_client: TandoorClient) -> MealPlanService:
    """Return the cached meal-plan service for a state/client pair."""
    return MealPlanService(state, tandoor_client)


def _meal_plan_service() -> MealPlanService:
    """Resolve the process-wide meal-plan service used by API handlers."""
    return _meal_plan_service_for(stage2_state, client)


def _ocr_client() -> GeminiOcrClient:
    """Create the configured OCR adapter at request time."""
    return GeminiOcrClient()

SHOPPING_STATUSES = {"remaining", "skipped", "completed"}
OCR_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _ensure_tandoor_writes_enabled(operation: str) -> None:
    """Enforce the deployment switch before any upstream write."""
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
    """Normalize paginated or list-shaped upstream results to dictionaries."""
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return [row for row in results if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _effective_status(entry: dict[str, Any], overrides: dict[str, str]) -> str:
    """Resolve app status precedence from overrides, completion, and delay."""
    override = overrides.get(str(entry.get("id")))
    if override in SHOPPING_STATUSES:
        return override
    if bool(entry.get("checked")):
        return "completed"
    if _has_active_delay(entry):
        return "skipped"
    return "remaining"


def _has_active_delay(entry: dict[str, Any]) -> bool:
    """Determine whether an entry's delay date is still active."""
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
    """Translate the app status contract into Tandoor fields."""
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
    """Normalize supported date values to ISO text or reject them as absent."""
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
    """Return whether an enabled reminder is due today or earlier."""
    if not reminder_enabled or reminder_date is None:
        return False
    try:
        due_day = date.fromisoformat(reminder_date)
    except ValueError:
        return False
    return due_day <= date.today()


def _normalize_store_group(raw_group: Any) -> dict[str, Any]:
    """Convert Tandoor/local store-group variants to one client shape."""
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
    """Extract the first usable recipe label for shopping display grouping."""
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
    """Build a navigable Tandoor recipe URL for a valid recipe ID."""
    if recipe_id is None:
        return None
    return f"{settings.tandoor_base_url.rstrip('/')}/recipe/{recipe_id}"


def _enrich_plan_recipe_urls(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add recipe links to a copied plan without mutating stored state."""
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
        recipe = entry.get("recipe")
        if isinstance(recipe, dict):
            enriched_recipe = dict(recipe)
            recipe_id = recipe.get("id")
            enriched_recipe["url"] = _recipe_url(recipe_id) if isinstance(recipe_id, int) else None
            enriched_entry["recipe"] = enriched_recipe
        enriched_entries.append(enriched_entry)

    enriched["entries"] = enriched_entries
    return enriched


def _normalize_recipe_payload(raw_recipe: Any, fallback_name: str) -> dict[str, Any]:
    """Normalize a recipe variant into the frontend recipe contract."""
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
    """Extract recipe identity and label from a shopping entry payload."""
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
    """Build one stable shopping row from upstream data and local overlays."""
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
    """Partition shopping rows by a status or grouping key."""
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
    """Extract reminder metadata while leaving upstream fields untouched."""
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
    """Normalize a local item's store group before persistence."""
    normalized = _normalize_store_group(raw)
    return {
        "id": normalized.get("id"),
        "name": str(normalized.get("name") or "General"),
    }


def _build_local_entry_payload(entry_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical persisted shape for an ad-hoc shopping item."""
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
    """Project a locally stored item into the same view shape as Tandoor rows."""
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
    """Combine upstream rows and local overlays into status sections."""
    overrides = stage2_state.get_shopping_statuses()
    metadata = stage2_state.get_shopping_item_metadata()
    local_entries = stage2_state.list_local_shopping_entries()
    sectioned: dict[str, list[dict[str, Any]]] = {
        "remaining": [],
        "skipped": [],
        "completed": [],
    }

    for entry in entries:
        entry_id = entry.get("id")
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
    """Parse a plan start date while keeping malformed optional data absent."""
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
    """Provide a stable newest-first sort key for stored plan summaries."""
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
    """Return a liveness response for monitoring and client probes."""
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
    """Search Tandoor recipes and return normalized recipe summaries."""
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
    """Return the configured recipe keyword catalog."""
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/today-meal")
async def today_meal() -> dict:
    """Return the selected recipe projection for the current day."""
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
    """Return keyword options used by meal-plan generation."""
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/config/keywords/selected")
async def selected_keywords() -> dict:
    """Return the locally selected recipe keyword IDs."""
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "selected_keyword_ids": stage2_state.selected_keywords(),
    }


@router.put("/config/keywords/selected")
async def set_selected_keywords(payload: SetSelectedKeywordsRequest = Body(...)) -> dict:
    """Persist the selected recipe keyword IDs."""
    keyword_ids = sorted({int(v) for v in payload.keyword_ids})

    stage2_state.set_selected_keywords(keyword_ids)
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "selected_keyword_ids": keyword_ids,
    }


@router.get("/config/meal-plan-rules")
async def get_meal_plan_rules() -> dict:
    """Return local meal-plan generation rules."""
    rules = stage2_state.meal_plan_rules()
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "data": rules,
    }


@router.get("/config/user-settings")
async def get_user_settings() -> dict:
    """Return user defaults used by the application shell."""
    settings_data = stage2_state.user_settings()
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "data": settings_data,
    }


@router.put("/config/user-settings")
async def set_user_settings(payload: UserSettingsRequest = Body(...)) -> dict:
    """Persist validated user defaults."""
    default_diners = int(payload.default_diners)
    default_notification_time = payload.default_notification_time.strip()

    saved = stage2_state.set_user_settings(default_diners, default_notification_time)
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "data": saved,
    }


@router.put("/config/meal-plan-rules")
async def set_meal_plan_rules(payload: MealPlanRulesRequest = Body(...)) -> dict:
    """Persist validated meal-plan generation rules."""
    no_repeat_days = int(payload.no_repeat_days)

    rules = stage2_state.set_meal_plan_rules(no_repeat_days)
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "data": rules,
    }


@router.post("/meal-plans/generate")
async def generate_meal_plan(payload: GenerateMealPlanRequest = Body(...)) -> dict:
    """Generate a local plan and attempt its upstream projection."""
    start_day = payload.start_date
    length_days = int(payload.length_days)
    configured_user_settings = stage2_state.user_settings()
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
        keyword_ids = stage2_state.selected_keywords()

    configured_rules = stage2_state.meal_plan_rules()
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
async def list_stored_meal_plans() -> dict:
    """List local meal-plan summaries in newest-first order."""
    plans = stage2_state.list_meal_plans()
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
        "revision": stage2_state.current_revision(),
        "count": len(summary),
        "data": summary,
    }


@router.post("/meal-plans/sync")
async def sync_meal_plans() -> dict:
    """Pull Tandoor meal-plan changes into local plan projections."""
    return await _meal_plan_service().sync_from_tandoor(
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        build_shopping_view=_build_shopping_view,
    )


@router.get("/meal-plans/{plan_id}")
async def get_meal_plan_stage2(plan_id: int) -> dict:
    """Return one local meal plan with enriched recipe links."""
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "projection": {"status": "synchronized"},
        "data": _enrich_plan_recipe_urls(plan),
    }


@router.delete("/meal-plans/stored/{plan_id}")
async def delete_stored_meal_plan(plan_id: int) -> dict:
    """Delete one local plan and its upstream projection."""
    return await _meal_plan_service().delete_plan(
        plan_id,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.patch("/meal-plans/{plan_id}")
async def patch_meal_plan_stage2(plan_id: int, payload: MealPlanPatchRequest = Body(...)) -> dict:
    """Patch one local plan through the meal-plan service."""
    return await _meal_plan_service().patch_plan(
        plan_id,
        payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.post("/meal-plans/{plan_id}/entries")
async def add_meal_plan_entry(plan_id: int, payload: MealPlanEntryCreateRequest = Body(...)) -> dict:
    """Add one entry to a local meal plan."""
    return await _meal_plan_service().add_entry(
        plan_id,
        payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.patch("/meal-plans/{plan_id}/entries/{entry_id}")
async def patch_meal_plan_entry(
    plan_id: int,
    entry_id: int,
    payload: MealPlanEntryPatchRequest = Body(...),
) -> dict:
    return await _meal_plan_service().patch_entry(
        plan_id,
        entry_id,
        payload.model_dump(mode="python", exclude_unset=True),
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
    )


@router.delete("/meal-plans/{plan_id}/entries/{entry_id}")
async def delete_meal_plan_entry(plan_id: int, entry_id: int) -> dict:
    """Delete one entry from a local meal plan."""
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
    """Generate or reconcile shopping rows for a meal-plan instance set."""
    if mode not in {"sync", "regenerate_missing"}:
        raise HTTPException(status_code=400, detail="mode must be 'sync' or 'regenerate_missing'.")

    return await _meal_plan_service().generate_shopping_from_plan(
        plan_id=plan_id,
        mode=mode,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        build_shopping_view=_build_shopping_view,
    )


@router.get("/shopping-list/view")
async def shopping_list_view(limit: int = Query(default=300, ge=1, le=1000)) -> dict:
    """Return canonical shopping sections with local overlays applied."""
    return await _shopping_service().get_view(
        limit=limit,
        extract_results=_extract_results,
        build_shopping_view=_build_shopping_view,
    )


@router.post("/shopping-list/entries")
async def shopping_entries_stage2_create(payload: ShoppingEntryCreateRequest = Body(...)) -> dict:
    """Create a local or Tandoor-backed shopping entry."""
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
    """Patch one shopping entry through the shopping service."""
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
    """Delete one shopping entry and its local overlays."""
    return await _shopping_service().delete_entry(
        entry_id=entry_id,
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        operation_name="shopping_entries_stage2_delete",
    )


@router.get("/shopping-list/sync")
async def shopping_sync_get(
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    """Return shopping sync events after the requested cursor."""
    changes = stage2_state.sync_events_since(since)[:limit]
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "since": since,
        "server_cursor": stage2_state.current_sync_cursor(),
        "changes": changes,
    }


@router.get("/sync/pending")
async def pending_projections() -> dict:
    """Return durable upstream operations awaiting reconciliation."""
    return {
        "source": "local-state",
        "revision": stage2_state.current_revision(),
        "data": stage2_state.pending_projections(),
    }


@router.post("/sync/pending/{operation_id}/retry")
async def retry_pending_projection(operation_id: str) -> dict:
    """Retry one pending meal-plan or shopping projection."""
    pending = stage2_state.pending_projection(operation_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Pending projection not found.")
    if pending.get("domain") == "meal_plan":
        return await _meal_plan_service().retry_pending_projection(
            operation_id,
            ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        )
    if pending.get("domain") == "shopping":
        return await _shopping_service().retry_pending_reconciliation(
            operation_id,
            extract_results=_extract_results,
            build_shopping_view=_build_shopping_view,
        )
    raise HTTPException(status_code=409, detail="Pending projection domain is unsupported.")


@router.post("/shopping-list/ocr", response_model=ShoppingListOcrResponse)
async def shopping_list_ocr(image: UploadFile = File(...)) -> ShoppingListOcrResponse:
    """Transcribe a bounded uploaded shopping-list image."""
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
async def shopping_sync_post(payload: ShoppingSyncRequest = Body(...)) -> dict:
    """Apply queued shopping mutations serially and return canonical state."""
    response = await _shopping_service().apply_sync_changes(
        changes=[change.model_dump(mode="python") for change in payload.changes],
        ensure_tandoor_writes_enabled=_ensure_tandoor_writes_enabled,
        extract_reminder_patch=_extract_reminder_patch,
        build_local_entry_payload=_build_local_entry_payload,
        local_store_group_payload=_local_store_group_payload,
        status_to_tandoor_fields=_status_to_tandoor_fields,
        effective_status=_effective_status,
        extract_results=_extract_results,
        build_shopping_view=_build_shopping_view,
    )
    return {
        "source": "tandoor+local-state",
        "revision": response["revision"],
        "server_cursor": response["server_cursor"],
        "cursor": response["cursor"],
        "data": response["data"],
        "projection": response.get("projection", {"status": "synchronized"}),
        "pending_projections": response["pending_projections"],
        "applied": response["applied"],
        "rejected": response["rejected"],
    }
