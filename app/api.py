from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.config import settings
from app.services.stage2_state import Stage2State
from app.services.tandoor_client import TandoorClient, TandoorError

router = APIRouter(tags=["mobile-api"])
client = TandoorClient()
stage2_state = Stage2State(settings.stage2_state_file)

SHOPPING_STATUSES = {"remaining", "skipped", "completed"}


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


def _recipe_title(recipe: dict[str, Any]) -> str:
    return str(recipe.get("name") or recipe.get("title") or f"Recipe {recipe.get('id')}")


def _parse_constraint_days(
    days: list[Any],
    start_date: date,
    length_days: int,
) -> set[int]:
    indexes: set[int] = set()
    for item in days:
        if isinstance(item, int):
            idx = item - 1 if item > 0 else item
            if 0 <= idx < length_days:
                indexes.add(idx)
            continue

        if isinstance(item, str):
            try:
                target_date = date.fromisoformat(item)
            except ValueError:
                continue
            idx = (target_date - start_date).days
            if 0 <= idx < length_days:
                indexes.add(idx)
    return indexes


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


def _normalize_shopping_entry(entry: dict[str, Any], status: str) -> dict[str, Any]:
    food = entry.get("food") if isinstance(entry.get("food"), dict) else {}
    unit = entry.get("unit") if isinstance(entry.get("unit"), dict) else {}

    ingredient_type = (
        str(food.get("category") or food.get("food_type") or food.get("type") or "Other")
    )
    store_group = (
        str(food.get("supermarket_category") or food.get("supermarket") or "General")
    )

    return {
        "id": entry.get("id"),
        "name": food.get("name") or entry.get("name") or "Unnamed",
        "amount": entry.get("amount"),
        "unit": unit.get("name") or entry.get("unit") or "",
        "status": status,
        "ingredient_type": ingredient_type,
        "store_group": store_group,
        "raw": entry,
    }


def _group_section(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        group = str(item.get(key) or "Other")
        grouped.setdefault(group, []).append(item)
    return grouped


def _build_shopping_view(entries: list[dict[str, Any]]) -> dict[str, Any]:
    overrides = stage2_state.get_shopping_statuses()
    sectioned: dict[str, list[dict[str, Any]]] = {
        "remaining": [],
        "skipped": [],
        "completed": [],
    }

    for entry in entries:
        status = _effective_status(entry, overrides)
        normalized = _normalize_shopping_entry(entry, status)
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


def _next_plan_entry_id() -> int:
    return stage2_state.allocate_entry_id()


def _find_entry(plan: dict[str, Any], entry_id: int) -> dict[str, Any] | None:
    entries = plan.get("entries", [])
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("entry_id") == entry_id:
            return entry
    return None


def _extract_recipe_ingredient_ids(recipe_payload: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    steps = recipe_payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_ingredients = step.get("ingredients")
            if not isinstance(step_ingredients, list):
                continue
            for ingredient in step_ingredients:
                if not isinstance(ingredient, dict):
                    continue
                ingredient_id = ingredient.get("id")
                if isinstance(ingredient_id, int):
                    ids.append(ingredient_id)

    top_ingredients = recipe_payload.get("ingredients")
    if isinstance(top_ingredients, list):
        for ingredient in top_ingredients:
            if not isinstance(ingredient, dict):
                continue
            ingredient_id = ingredient.get("id")
            if isinstance(ingredient_id, int):
                ids.append(ingredient_id)

    return sorted(set(ids))


def _collect_recipe_history_dates() -> dict[int, list[date]]:
    history: dict[int, list[date]] = {}
    for plan in stage2_state.list_meal_plans():
        entries = plan.get("entries")
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            recipe = entry.get("recipe")
            if not isinstance(recipe, dict):
                continue
            recipe_id = recipe.get("id")
            if not isinstance(recipe_id, int):
                continue
            date_value = entry.get("date")
            if not isinstance(date_value, str):
                continue
            try:
                entry_date = date.fromisoformat(date_value)
            except ValueError:
                continue

            history.setdefault(recipe_id, []).append(entry_date)

    for recipe_id, dates in history.items():
        dates.sort()
        history[recipe_id] = dates
    return history


def _is_within_no_repeat_window(
    recipe_id: int,
    candidate_date: date,
    no_repeat_days: int,
    history_dates: dict[int, list[date]],
) -> bool:
    if no_repeat_days <= 0:
        return False

    for seen_date in history_dates.get(recipe_id, []):
        if seen_date >= candidate_date:
            break
        if (candidate_date - seen_date).days <= no_repeat_days:
            return True
    return False


@router.get(
    "/health",
    tags=["core"],
    summary="Health check",
    description="Simple health endpoint used for liveness checks.",
)
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/recipes",
    tags=["core"],
    summary="List recipes",
    description=(
        "Returns recipes from Tandoor with optional text search, result limit, "
        "and keyword filtering."
    ),
)
async def recipes(
    search: str | None = Query(default=None, description="Search term"),
    limit: int | None = Query(default=None, ge=1, le=100),
    keyword_ids: list[int] | None = Query(
        default=None,
        description="Filter by keyword IDs from /recipe-tags.",
    ),
) -> dict:
    try:
        if limit is None:
            data = await client.list_recipes_all(
                search=search,
                keyword_ids=keyword_ids,
            )
        else:
            data = await client.list_recipes(
                search=search,
                limit=limit,
                keyword_ids=keyword_ids,
            )
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/recipes/{recipe_id}",
    tags=["core"],
    summary="Get recipe by ID",
    description=(
        "Returns the raw recipe payload from Tandoor for the provided recipe ID."
    ),
)
async def recipe_by_id(recipe_id: int) -> dict[str, Any]:
    try:
        data = await client.get_recipe(recipe_id)
        if isinstance(data, dict):
            return data
        raise HTTPException(status_code=502, detail="Unexpected Tandoor response format.")
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/recipe-tags",
    tags=["core"],
    summary="List recipe tags",
    description="Returns available recipe tags/keywords from Tandoor.",
)
async def recipe_tags() -> dict:
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/today-meal",
    tags=["core"],
    summary="Get a single meal payload",
    description=(
        "Fetches one recipe candidate and returns a stable payload with title, "
        "ingredients, and steps for app and dashboard use."
    ),
)
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




@router.get(
    "/config/keywords",
    tags=["configuration"],
    summary="List available keywords",
    description="Returns available Tandoor keywords/tags used by Stage 2 planning flows.",
)
async def config_keywords() -> dict:
    try:
        data = await client.list_tags()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/config/keywords/selected",
    tags=["configuration"],
    summary="Get selected keywords",
    description="Returns locally stored keyword IDs selected for planning and one-meal flows.",
)
async def selected_keywords() -> dict:
    return {
        "source": "local-state",
        "selected_keyword_ids": stage2_state.selected_keywords(),
    }


@router.put(
    "/config/keywords/selected",
    tags=["configuration"],
    summary="Set selected keywords",
    description="Replaces locally stored selected keyword IDs used by Stage 2 flows.",
)
async def set_selected_keywords(payload: dict[str, Any] = Body(...)) -> dict:
    values = payload.get("keyword_ids")
    if not isinstance(values, list):
        raise HTTPException(status_code=400, detail="keyword_ids must be a list of integers.")

    try:
        keyword_ids = sorted({int(v) for v in values})
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="keyword_ids must be integers.") from exc

    stage2_state.set_selected_keywords(keyword_ids)
    return {
        "source": "local-state",
        "selected_keyword_ids": keyword_ids,
    }


@router.get(
    "/config/meal-plan-rules",
    tags=["configuration"],
    summary="Get meal plan rules",
    description="Returns local meal planning rules, including no-repeat behavior.",
)
async def get_meal_plan_rules() -> dict:
    rules = stage2_state.meal_plan_rules()
    return {
        "source": "local-state",
        "data": rules,
    }


@router.put(
    "/config/meal-plan-rules",
    tags=["configuration"],
    summary="Set meal plan rules",
    description="Updates local meal planning rules such as no_repeat_days.",
)
async def set_meal_plan_rules(payload: dict[str, Any] = Body(...)) -> dict:
    raw_value = payload.get("no_repeat_days")
    try:
        no_repeat_days = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="no_repeat_days must be an integer.") from exc

    if no_repeat_days < 0:
        raise HTTPException(status_code=400, detail="no_repeat_days must be >= 0.")

    rules = stage2_state.set_meal_plan_rules(no_repeat_days)
    return {
        "source": "local-state",
        "data": rules,
    }


@router.post(
    "/meal-plans/generate",
    tags=["meal-plans"],
    summary="Generate a meal plan",
    description=(
        "Builds a meal plan from date, duration, diners, constraints, keyword filtering, "
        "and no-repeat rules. Generated plan is stored in local Stage 2 state."
    ),
)
async def generate_meal_plan(payload: dict[str, Any] = Body(...)) -> dict:
    start_date_raw = payload.get("start_date")
    if not isinstance(start_date_raw, str):
        raise HTTPException(status_code=400, detail="start_date must be an ISO date string.")

    try:
        start_day = date.fromisoformat(start_date_raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD.") from exc

    try:
        length_days = int(payload.get("length_days") or 7)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="length_days must be an integer.") from exc

    if length_days < 1 or length_days > 31:
        raise HTTPException(status_code=400, detail="length_days must be within 1..31.")

    diners = int(payload.get("diners") or 2)

    constraints = payload.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}

    leftover_days = _parse_constraint_days(constraints.get("leftover_days", []), start_day, length_days)
    takeout_days = _parse_constraint_days(constraints.get("takeout_days", []), start_day, length_days)
    empty_days = _parse_constraint_days(constraints.get("empty_days", []), start_day, length_days)

    raw_keyword_ids = payload.get("keyword_ids")
    if isinstance(raw_keyword_ids, list) and raw_keyword_ids:
        keyword_ids = [int(v) for v in raw_keyword_ids]
    else:
        keyword_ids = stage2_state.selected_keywords()

    recipe_candidates: list[dict[str, Any]] = []
    if keyword_ids:
        try:
            result = await client.list_recipes(limit=max(20, length_days * 3), keyword_ids=keyword_ids)
            recipe_candidates = _extract_results(result)
        except TandoorError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    configured_rules = stage2_state.meal_plan_rules()
    raw_no_repeat = payload.get("no_repeat_days")
    if raw_no_repeat is None:
        no_repeat_days = int(configured_rules.get("no_repeat_days", 30))
    else:
        try:
            no_repeat_days = int(raw_no_repeat)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="no_repeat_days must be an integer.") from exc

    if no_repeat_days < 0:
        raise HTTPException(status_code=400, detail="no_repeat_days must be >= 0.")

    recipe_history_dates = _collect_recipe_history_dates()

    recipe_pointer = 0
    randomized_candidates = recipe_candidates[:]
    if randomized_candidates:
        random.SystemRandom().shuffle(randomized_candidates)
    entries: list[dict[str, Any]] = []
    last_recipe: dict[str, Any] | None = None

    for day_index in range(length_days):
        entry_date = start_day + timedelta(days=day_index)
        mode = "planned"
        recipe_obj: dict[str, Any] | None = None

        if day_index in empty_days:
            mode = "empty"
        elif day_index in takeout_days:
            mode = "takeout"
        elif day_index in leftover_days and last_recipe is not None:
            mode = "leftover"
            recipe_obj = last_recipe
        elif randomized_candidates:
            # Shuffle candidate order per plan generation to avoid identical plans
            # when Tandoor returns recipes in a stable sort order.
            if recipe_pointer > 0 and recipe_pointer % len(randomized_candidates) == 0:
                random.SystemRandom().shuffle(randomized_candidates)

            chosen_obj: dict[str, Any] | None = None
            candidate_len = len(randomized_candidates)

            for offset in range(candidate_len):
                candidate = randomized_candidates[(recipe_pointer + offset) % candidate_len]
                candidate_id = candidate.get("id") if isinstance(candidate, dict) else None
                if not isinstance(candidate_id, int):
                    continue
                if _is_within_no_repeat_window(
                    recipe_id=candidate_id,
                    candidate_date=entry_date,
                    no_repeat_days=no_repeat_days,
                    history_dates=recipe_history_dates,
                ):
                    continue
                chosen_obj = candidate
                recipe_pointer += offset + 1
                break

            if chosen_obj is not None:
                chosen_id = chosen_obj.get("id")
                if isinstance(chosen_id, int):
                    recipe_history_dates.setdefault(chosen_id, []).append(entry_date)
                    recipe_history_dates[chosen_id].sort()

                recipe_obj = {
                    "id": chosen_obj.get("id"),
                    "title": _recipe_title(chosen_obj),
                }
                last_recipe = recipe_obj

        entries.append(
            {
                "entry_id": _next_plan_entry_id(),
                "day_index": day_index,
                "date": entry_date.isoformat(),
                "mode": mode,
                "recipe": recipe_obj,
                "servings": diners,
                "notes": "",
            }
        )

    plan_payload = {
        "start_date": start_day.isoformat(),
        "length_days": length_days,
        "diners": diners,
        "no_repeat_days": no_repeat_days,
        "keyword_ids": keyword_ids,
        "constraints": {
            "leftover_days": sorted(leftover_days),
            "takeout_days": sorted(takeout_days),
            "empty_days": sorted(empty_days),
        },
        "entries": entries,
    }

    stored = stage2_state.create_meal_plan(plan_payload)
    stage2_state.append_sync_event("meal_plan_generated", stored)

    return {"source": "tandoor+local-state", "data": stored}


@router.get(
    "/meal-plans/stored",
    tags=["meal-plans"],
    summary="List stored meal plans",
    description="Returns summary information for meal plans currently stored in local state.",
)
async def list_stored_meal_plans() -> dict:
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

    return {
        "source": "local-state",
        "count": len(summary),
        "data": summary,
    }


@router.get(
    "/meal-plans/{plan_id}",
    tags=["meal-plans"],
    summary="Get meal plan by ID",
    description="Returns a full stored meal plan, including entries and constraints.",
)
async def get_meal_plan_stage2(plan_id: int) -> dict:
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")
    return {"source": "local-state", "data": plan}


@router.delete(
    "/meal-plans/stored/{plan_id}",
    tags=["meal-plans"],
    summary="Delete stored meal plan",
    description="Deletes a stored meal plan by ID from local state.",
)
async def delete_stored_meal_plan(plan_id: int) -> dict:
    deleted = stage2_state.delete_meal_plan(plan_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    stage2_state.append_sync_event("meal_plan_deleted", {"plan_id": plan_id})
    return {
        "source": "local-state",
        "data": {
            "deleted": True,
            "plan_id": plan_id,
        },
    }


@router.patch(
    "/meal-plans/{plan_id}",
    tags=["meal-plans"],
    summary="Patch meal plan",
    description="Partially updates a stored meal plan and records a sync event.",
)
async def patch_meal_plan_stage2(plan_id: int, payload: dict[str, Any] = Body(...)) -> dict:
    current = stage2_state.get_meal_plan(plan_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    mutable: dict[str, Any] = {}
    for key in ("start_date", "length_days", "diners", "constraints", "keyword_ids"):
        if key in payload:
            mutable[key] = payload[key]

    if "entries" in payload and isinstance(payload["entries"], list):
        mutable["entries"] = payload["entries"]

    updated = stage2_state.update_meal_plan(plan_id, mutable)
    if updated is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    stage2_state.append_sync_event("meal_plan_updated", {"plan_id": plan_id, "payload": payload})
    return {"source": "local-state", "data": updated}


@router.post(
    "/meal-plans/{plan_id}/entries",
    tags=["meal-plans"],
    summary="Add meal plan entry",
    description="Adds a new entry to a stored meal plan and reorders by day index.",
)
async def add_meal_plan_entry(plan_id: int, payload: dict[str, Any] = Body(...)) -> dict:
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    entries = plan.get("entries")
    if not isinstance(entries, list):
        entries = []

    day_index = int(payload.get("day_index") if payload.get("day_index") is not None else len(entries))
    entry_date = payload.get("date")
    if not isinstance(entry_date, str):
        try:
            start_day = date.fromisoformat(str(plan.get("start_date")))
        except ValueError:
            start_day = date.today()
        entry_date = (start_day + timedelta(days=day_index)).isoformat()

    mode = str(payload.get("mode") or "planned")
    recipe = payload.get("recipe") if isinstance(payload.get("recipe"), dict) else None

    entry = {
        "entry_id": _next_plan_entry_id(),
        "day_index": day_index,
        "date": entry_date,
        "mode": mode,
        "recipe": recipe,
        "servings": int(payload.get("servings") or plan.get("diners") or 2),
        "notes": str(payload.get("notes") or ""),
    }

    entries.append(entry)
    entries.sort(key=lambda row: int(row.get("day_index", 0)))

    updated = stage2_state.update_meal_plan(plan_id, {"entries": entries})
    stage2_state.append_sync_event("meal_plan_entry_added", {"plan_id": plan_id, "entry": entry})

    return {"source": "local-state", "data": updated}


@router.patch(
    "/meal-plans/{plan_id}/entries/{entry_id}",
    tags=["meal-plans"],
    summary="Update meal plan entry",
    description="Updates fields for one meal plan entry, including optional day re-targeting.",
)
async def patch_meal_plan_entry(
    plan_id: int,
    entry_id: int,
    payload: dict[str, Any] = Body(...),
) -> dict:
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    entry = _find_entry(plan, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Meal plan entry not found.")

    for key in ("day_index", "date", "mode", "recipe", "servings", "notes"):
        if key in payload:
            entry[key] = payload[key]

    target_day_index = payload.get("target_day_index")
    if target_day_index is not None:
        entry["day_index"] = int(target_day_index)

    entries = plan.get("entries", [])
    if isinstance(entries, list):
        entries.sort(key=lambda row: int(row.get("day_index", 0)))

    updated = stage2_state.update_meal_plan(plan_id, {"entries": entries})
    stage2_state.append_sync_event(
        "meal_plan_entry_updated",
        {"plan_id": plan_id, "entry_id": entry_id, "payload": payload},
    )

    return {"source": "local-state", "data": updated}


@router.delete(
    "/meal-plans/{plan_id}/entries/{entry_id}",
    tags=["meal-plans"],
    summary="Delete meal plan entry",
    description="Removes a specific entry from a stored meal plan.",
)
async def delete_meal_plan_entry(plan_id: int, entry_id: int) -> dict:
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    entries = plan.get("entries")
    if not isinstance(entries, list):
        raise HTTPException(status_code=404, detail="Meal plan entry not found.")

    before = len(entries)
    entries = [row for row in entries if int(row.get("entry_id", -1)) != entry_id]
    if len(entries) == before:
        raise HTTPException(status_code=404, detail="Meal plan entry not found.")

    entries.sort(key=lambda row: int(row.get("day_index", 0)))
    updated = stage2_state.update_meal_plan(plan_id, {"entries": entries})
    stage2_state.append_sync_event("meal_plan_entry_deleted", {"plan_id": plan_id, "entry_id": entry_id})

    return {"source": "local-state", "data": updated}


@router.post(
    "/meal-plans/{plan_id}/shopping-list",
    tags=["meal-plans"],
    summary="Generate shopping list from meal plan",
    description=(
        "Converts meal plan entries into Tandoor shopping updates using recipe ingredients "
        "and returns both operation results and a refreshed shopping view."
    ),
)
async def meal_plan_to_shopping_list(plan_id: int) -> dict:
    _ensure_tandoor_writes_enabled("meal_plan_to_shopping_list")
    plan = stage2_state.get_meal_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Meal plan not found.")

    entries = plan.get("entries")
    if not isinstance(entries, list):
        entries = []

    created: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for entry in entries:
        recipe = entry.get("recipe") if isinstance(entry, dict) else None
        if not isinstance(recipe, dict):
            continue

        recipe_id = recipe.get("id")
        if not isinstance(recipe_id, int):
            continue

        servings = int(entry.get("servings") or plan.get("diners") or 2)
        try:
            recipe_payload = await client.get_recipe(recipe_id)
            ingredient_ids = _extract_recipe_ingredient_ids(recipe_payload)
            request_payload = {"ingredients": ingredient_ids, "servings": servings}
            result = await client.update_recipe_shopping(recipe_id, request_payload)
            created.append(
                {
                    "entry_id": entry.get("entry_id"),
                    "operation": "recipe_shopping_update",
                    "payload": request_payload,
                    "result": result,
                }
            )
        except TandoorError as exc:
            failed.append(
                {
                    "entry_id": entry.get("entry_id"),
                    "operation": "recipe_shopping_update",
                    "payload": {"ingredients": [], "servings": servings},
                    "errors": [str(exc)],
                }
            )

    sync_payload = {
        "plan_id": plan_id,
        "created_count": len(created),
        "failed_count": len(failed),
    }
    stage2_state.append_sync_event("meal_plan_shopping_generated", sync_payload)

    shopping_view: dict[str, Any] | None = None
    shopping_view_error: str | None = None
    try:
        shopping_entries = await client.list_shopping_entries(limit=500)
        shopping_view = _build_shopping_view(_extract_results(shopping_entries))
    except TandoorError as exc:
        shopping_view_error = str(exc)

    return {
        "source": "tandoor+local-state",
        "data": {
            "plan_id": plan_id,
            "created": created,
            "failed": failed,
            "shopping_view": shopping_view,
            "shopping_view_error": shopping_view_error,
        },
    }


@router.get(
    "/shopping-list/view",
    tags=["shopping"],
    summary="Get shopping list view",
    description=(
        "Returns an app-friendly shopping list view grouped into Remaining, Skipped, and "
        "Completed sections, with category-based grouping metadata."
    ),
)
async def shopping_list_view(limit: int = Query(default=300, ge=1, le=1000)) -> dict:
    try:
        data = await client.list_shopping_entries(limit=limit)
        entries = _extract_results(data)
        view = _build_shopping_view(entries)

        return {
            "source": "tandoor+local-state",
            "cursor": stage2_state.current_sync_cursor(),
            "data": view,
        }
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/shopping-list/entries",
    tags=["shopping"],
    summary="Create shopping list entry",
    description="Creates a shopping list entry in Tandoor and records a local sync event.",
)
async def shopping_entries_stage2_create(payload: dict[str, Any] = Body(...)) -> dict:
    _ensure_tandoor_writes_enabled("shopping_entries_stage2_create")
    try:
        created = await client.create_shopping_entry(payload)
        cursor = stage2_state.append_sync_event("shopping_entry_created", created)
        return {
            "source": "tandoor+local-state",
            "cursor": cursor,
            "data": created,
        }
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.patch(
    "/shopping-list/entries/{entry_id}",
    tags=["shopping"],
    summary="Update shopping list entry",
    description=(
        "Updates one shopping entry. Supports explicit status transitions "
        "(remaining/skipped/completed) mapped to Tandoor-compatible fields."
    ),
)
async def shopping_entries_stage2_update(
    entry_id: int,
    payload: dict[str, Any] = Body(...),
) -> dict:
    _ensure_tandoor_writes_enabled("shopping_entries_stage2_update")
    request_payload = dict(payload)

    status = request_payload.pop("status", None)
    if status is not None:
        status = str(status)
        if status not in SHOPPING_STATUSES:
            raise HTTPException(status_code=400, detail="status must be remaining, skipped, or completed.")

        mapped = _status_to_tandoor_fields(status)
        for key, value in mapped.items():
            request_payload.setdefault(key, value)

    try:
        updated = await client.update_shopping_entry(entry_id, request_payload)
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if status is not None:
        stage2_state.set_shopping_status(entry_id, status)

    cursor = stage2_state.append_sync_event(
        "shopping_entry_updated",
        {
            "entry_id": entry_id,
            "request": payload,
            "data": updated,
            "status": status,
        },
    )

    effective = status or _effective_status(updated if isinstance(updated, dict) else {}, stage2_state.get_shopping_statuses())

    return {
        "source": "tandoor+local-state",
        "cursor": cursor,
        "effective_status": effective,
        "data": updated,
    }


@router.delete(
    "/shopping-list/entries/{entry_id}",
    tags=["shopping"],
    summary="Delete shopping list entry",
    description="Deletes one shopping entry in Tandoor and records a local sync event.",
)
async def shopping_entries_stage2_delete(entry_id: int) -> dict:
    _ensure_tandoor_writes_enabled("shopping_entries_stage2_delete")
    try:
        deleted = await client.delete_shopping_entry(entry_id)
        cursor = stage2_state.append_sync_event("shopping_entry_deleted", {"entry_id": entry_id})
        return {
            "source": "tandoor+local-state",
            "cursor": cursor,
            "data": deleted,
        }
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/shopping-list/sync",
    tags=["shopping"],
    summary="Get shopping sync delta",
    description="Returns local shopping sync events newer than the provided cursor.",
)
async def shopping_sync_get(
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    changes = stage2_state.sync_events_since(since)[:limit]
    return {
        "source": "local-state",
        "since": since,
        "server_cursor": stage2_state.current_sync_cursor(),
        "changes": changes,
    }


@router.post(
    "/shopping-list/sync",
    tags=["shopping"],
    summary="Apply offline shopping changes",
    description=(
        "Accepts batched offline create/update/delete operations, applies them to Tandoor, "
        "and returns applied plus rejected results with updated server cursor."
    ),
)
async def shopping_sync_post(payload: dict[str, Any] = Body(...)) -> dict:
    _ensure_tandoor_writes_enabled("shopping_sync_post")
    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise HTTPException(status_code=400, detail="changes must be a list.")

    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for idx, change in enumerate(changes):
        if not isinstance(change, dict):
            rejected.append({"index": idx, "reason": "Change must be an object."})
            continue

        operation = str(change.get("operation") or "").lower()
        entry_id = change.get("entry_id")
        change_payload = change.get("payload") if isinstance(change.get("payload"), dict) else {}

        try:
            if operation == "create":
                data = await client.create_shopping_entry(change_payload)
                cursor = stage2_state.append_sync_event("shopping_entry_created", data)
                applied.append({"index": idx, "cursor": cursor, "operation": operation, "data": data})
            elif operation == "update":
                if not isinstance(entry_id, int):
                    raise ValueError("entry_id is required for update")
                status = change_payload.get("status")
                req = dict(change_payload)
                if status is not None:
                    status_str = str(status)
                    if status_str not in SHOPPING_STATUSES:
                        raise ValueError("status must be remaining, skipped, or completed")
                    stage2_state.set_shopping_status(entry_id, status_str)
                    req.pop("status", None)
                    mapped = _status_to_tandoor_fields(status_str)
                    for key, value in mapped.items():
                        req.setdefault(key, value)

                data = await client.update_shopping_entry(entry_id, req)
                cursor = stage2_state.append_sync_event(
                    "shopping_entry_updated",
                    {"entry_id": entry_id, "request": change_payload, "data": data},
                )
                applied.append({"index": idx, "cursor": cursor, "operation": operation, "data": data})
            elif operation == "delete":
                if not isinstance(entry_id, int):
                    raise ValueError("entry_id is required for delete")
                data = await client.delete_shopping_entry(entry_id)
                cursor = stage2_state.append_sync_event("shopping_entry_deleted", {"entry_id": entry_id})
                applied.append({"index": idx, "cursor": cursor, "operation": operation, "data": data})
            else:
                rejected.append({"index": idx, "reason": f"Unsupported operation: {operation}"})
        except (TandoorError, ValueError) as exc:
            rejected.append({"index": idx, "reason": str(exc)})

    return {
        "source": "tandoor+local-state",
        "server_cursor": stage2_state.current_sync_cursor(),
        "applied": applied,
        "rejected": rejected,
    }
