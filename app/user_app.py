import json
from pathlib import Path

from fastapi.responses import HTMLResponse

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "user_app.html"
_CLIENT_MANIFEST_PATH = Path(__file__).resolve().parent / "static" / "dist" / "manifest.json"


def render_user_app(api_prefix: str, tandoor_base_url: str) -> HTMLResponse:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    manifest = json.loads(_CLIENT_MANIFEST_PATH.read_text(encoding="utf-8"))
    html = template.replace("{{ api_prefix_js }}", repr(api_prefix))
    html = html.replace("{{ tandoor_base_url_js }}", repr(tandoor_base_url))
    html = html.replace("{{ app_css }}", manifest["app_css"])
    html = html.replace("{{ app_js }}", manifest["app_js"])
    return HTMLResponse(content=html)
