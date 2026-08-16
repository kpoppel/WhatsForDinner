from fastapi.responses import HTMLResponse

from app.ui.rendering import render_ui_page


def render_user_app(api_prefix: str) -> HTMLResponse:
    return render_ui_page("user_app.html", api_prefix=api_prefix)
