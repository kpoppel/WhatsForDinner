from pathlib import Path

from fastapi.responses import HTMLResponse

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "home.html"


def render_home_app() -> HTMLResponse:
    return HTMLResponse(content=_TEMPLATE_PATH.read_text(encoding="utf-8"))
