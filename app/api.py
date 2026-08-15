from fastapi import APIRouter, HTTPException, Query

from app.services.tandoor_client import TandoorClient, TandoorError

router = APIRouter(tags=["mobile-api"])
client = TandoorClient()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/recipes")
async def recipes(
    search: str | None = Query(default=None, description="Search term"),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    try:
        data = await client.list_recipes(search=search, limit=limit)
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/shopping-list")
async def shopping_list() -> dict:
    try:
        data = await client.shopping_list()
        return {"source": "tandoor", "data": data}
    except TandoorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
