from pathlib import Path

from fastapi.responses import HTMLResponse

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "user_app.html"


def render_user_app(api_prefix: str, tandoor_base_url: str) -> HTMLResponse:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("{{ api_prefix_js }}", repr(api_prefix))
    html = html.replace("{{ tandoor_base_url_js }}", repr(tandoor_base_url))
    return HTMLResponse(content=html)
