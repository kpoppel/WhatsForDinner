from functools import lru_cache
from pathlib import Path

from fastapi.responses import HTMLResponse

TEMPLATE_DIRECTORY = Path(__file__).resolve().parent.parent / "templates"
API_PREFIX_TOKEN = "{{ api_prefix_js }}"


@lru_cache(maxsize=8)
def _load_template(template_name: str) -> str:
    template_path = TEMPLATE_DIRECTORY / template_name
    return template_path.read_text(encoding="utf-8")


def render_ui_page(template_name: str, *, api_prefix: str) -> HTMLResponse:
    template = _load_template(template_name)
    rendered_html = template.replace(API_PREFIX_TOKEN, repr(api_prefix))
    return HTMLResponse(content=rendered_html)
