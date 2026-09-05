"""Render the unified PWA shell and inject runtime browser configuration."""

from pathlib import Path

from fastapi.responses import HTMLResponse

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "user_app.html"


def render_user_app(
    api_prefix: str,
    tandoor_base_url: str,
    performance_metrics_enabled: bool = False,
) -> HTMLResponse:
    """Render the unified app shell with the configured API prefix."""
    """Return the app template with escaped runtime configuration values."""

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("{{ api_prefix_js }}", repr(api_prefix))
    html = html.replace("{{ tandoor_base_url_js }}", repr(tandoor_base_url))
    metrics_flag = "true" if performance_metrics_enabled else "false"
    html = html.replace("{{ performance_metrics_enabled_js }}", metrics_flag)
    return HTMLResponse(content=html)
