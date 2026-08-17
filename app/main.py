from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import settings
from app.inspect_ui import render_inspector
from app.user_app import render_user_app

app = FastAPI(
    title=settings.app_name,
    description="FastAPI backend for mobile clients using Tandoor recipe and shopping data.",
    version="0.1.0",
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get(f"{settings.api_v1_prefix}/openapi.json", include_in_schema=False)
async def versioned_openapi_schema() -> dict:
    return app.openapi()


@app.get(f"{settings.api_v1_prefix}/docs", include_in_schema=False)
async def versioned_swagger_docs() -> object:
    return get_swagger_ui_html(
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        title=f"{settings.app_name} API - Swagger UI",
    )


@app.get(f"{settings.api_v1_prefix}/redoc", include_in_schema=False)
async def versioned_redoc_docs() -> object:
    return get_redoc_html(
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        title=f"{settings.app_name} API - ReDoc",
    )


@app.get("/app", include_in_schema=False)
async def user_app() -> object:
    return render_user_app(settings.api_v1_prefix)


@app.get("/inspect", include_in_schema=False)
async def inspect() -> object:
    return render_inspector(settings.api_v1_prefix)


@app.get("/shopping-sw.js", include_in_schema=False)
async def shopping_service_worker() -> FileResponse:
    return FileResponse(
        "app/static/shopping-sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/shopping.webmanifest", include_in_schema=False)
async def shopping_webmanifest() -> FileResponse:
    return FileResponse(
        "app/static/shopping.webmanifest",
        media_type="application/manifest+json",
    )
