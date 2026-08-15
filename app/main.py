from fastapi import FastAPI

from app.api import router as api_router
from app.config import settings
from app.inspect_ui import render_inspector

app = FastAPI(
    title=settings.app_name,
    description="FastAPI backend for mobile clients using Tandoor recipe and shopping data.",
    version="0.1.0",
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/inspect", include_in_schema=False)
async def inspect() -> object:
    return render_inspector(settings.api_v1_prefix)
