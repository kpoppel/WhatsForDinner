from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.config import settings
from app.home_app import render_home_app
from app.inspect_ui import render_inspector
from app.shopping_app import render_shopping_app
from app.user_app import render_user_app

REDOC_JS_BUNDLE = "https://cdn.jsdelivr.net/npm/redoc@2.4.0/bundles/redoc.standalone.js"
OPENAPI_TAGS = [
    {
        "name": "core",
        "description": "Basic service endpoints and recipe lookup helpers backed by Tandoor.",
    },
    {
        "name": "configuration",
        "description": "Stage 2 local configuration for keyword selection and meal plan rules.",
    },
    {
        "name": "meal-plans",
        "description": "Generate, store, edit, and convert meal plans into shopping list updates.",
    },
    {
        "name": "shopping",
        "description": "Shopping list view, CRUD operations, and offline sync surfaces.",
    },
]

app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend API for WhatsForDinner mobile and web clients.\n\n"
        "This service uses Tandoor as source of truth for recipes and shopping data, "
        "and keeps lightweight local state for app-specific workflows such as selected "
        "keywords, meal-plan drafts, and offline shopping sync events."
    ),
    version="0.1.0",
    contact={"name": "WhatsForDinner Maintainers"},
    license_info={"name": "Open Source"},
    openapi_tags=OPENAPI_TAGS,
    redoc_url=None,
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


@app.get("/redoc", include_in_schema=False)
async def root_redoc_docs() -> object:
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{settings.app_name} API - ReDoc",
        redoc_js_url=REDOC_JS_BUNDLE,
        with_google_fonts=False,
    )


@app.get(f"{settings.api_v1_prefix}/redoc", include_in_schema=False)
async def versioned_redoc_docs() -> object:
    return get_redoc_html(
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
        title=f"{settings.app_name} API - ReDoc",
        redoc_js_url=REDOC_JS_BUNDLE,
        with_google_fonts=False,
    )


@app.get("/", include_in_schema=False)
async def home() -> HTMLResponse:
    return render_home_app()


@app.get("/app", include_in_schema=False)
async def user_app() -> object:
    return render_user_app(settings.api_v1_prefix)


@app.get("/inspect", include_in_schema=False)
async def inspect() -> object:
    return render_inspector(settings.api_v1_prefix)


@app.get("/shopping", include_in_schema=False)
async def shopping_app() -> object:
    return render_shopping_app(settings.api_v1_prefix)


@app.get("/shopping.webmanifest", include_in_schema=False)
async def shopping_manifest() -> FileResponse:
    return FileResponse("app/static/shopping.webmanifest", media_type="application/manifest+json")


@app.get("/shopping-sw.js", include_in_schema=False)
async def shopping_service_worker() -> FileResponse:
    return FileResponse("app/static/shopping-sw.js", media_type="application/javascript")
