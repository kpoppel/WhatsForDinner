"""One-time title backfill for recipe exclusions saved before schema version 21."""

import asyncio

from app.config import settings
from app.services.server_state import ServerState
from app.services.tandoor_client import TandoorClient


async def backfill_recipe_use_titles(state: ServerState, client: TandoorClient) -> int:
    """Resolve missing titles before writing any changes to local state."""
    missing = [row for row in state.list_recipe_uses() if row["title"] is None]
    titles: dict[int, str] = {}
    for row in missing:
        recipe = await client.get_recipe(row["recipe_id"])
        titles[row["recipe_id"]] = recipe["name"]
    state.backfill_recipe_use_titles(titles)
    state.flush()
    return len(titles)


if __name__ == "__main__":
    count = asyncio.run(backfill_recipe_use_titles(ServerState(settings.stage2_data_dir), TandoorClient()))
    print(f"Backfilled {count} recipe exclusion titles.")