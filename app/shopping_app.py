from fastapi.responses import HTMLResponse


def render_shopping_app(api_prefix: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>WhatsForDinner Shopping Mode</title>
  <style>
    :root {{
      --bg: #f0f6f3;
      --ink: #1d2b25;
      --muted: #5b6b64;
      --line: #d6e3dc;
      --panel: #ffffff;
      --accent: #176b5a;
      --soft: #eef6f2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 90% 0%, #dcebe5 0%, transparent 35%),
        radial-gradient(circle at 8% 100%, #ffe8d6 0%, transparent 32%),
        var(--bg);
      min-height: 100vh;
      padding: 0.8rem;
    }}
    .shell {{ max-width: 680px; margin: 0 auto; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 0.85rem;
      box-shadow: 0 12px 24px rgba(12, 31, 23, 0.07);
    }}
    h1 {{ margin: 0; font-size: clamp(1.2rem, 4.2vw, 1.6rem); }}
    p {{ margin: 0.3rem 0 0.5rem; color: var(--muted); }}
    .row {{ display: flex; gap: 0.45rem; flex-wrap: wrap; align-items: center; }}
    button {{
      border: none;
      border-radius: 8px;
      padding: 0.5rem 0.7rem;
      font: inherit;
      font-weight: 600;
      color: #fff;
      background: var(--accent);
      cursor: pointer;
    }}
    button.ghost {{ background: #42524a; }}
    .status {{
      display: inline-flex;
      gap: 0.35rem;
      flex-wrap: wrap;
      align-items: center;
      font-size: 0.84rem;
      color: var(--muted);
      margin: 0.5rem 0;
    }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0.14rem 0.45rem;
      background: #f7fbf9;
    }}
    .section {{ margin-top: 0.65rem; }}
    .section h2 {{ margin: 0 0 0.35rem; font-size: 1rem; }}
    .category {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.5rem;
      background: var(--soft);
      margin-bottom: 0.45rem;
    }}
    .category-title {{
      font-weight: 700;
      font-size: 0.9rem;
      margin-bottom: 0.35rem;
    }}
    .shop-card {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      padding: 0.56rem;
      margin-bottom: 0.4rem;
      touch-action: pan-y;
      transition: transform 120ms ease, box-shadow 120ms ease, border-color 120ms ease;
      user-select: none;
    }}
    .shop-card:last-child {{ margin-bottom: 0; }}
    .shop-card:active {{ box-shadow: 0 8px 16px rgba(12, 31, 23, 0.08); }}
    .shop-card.swiping {{ border-color: #e59c71; }}
    .shop-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 0.5rem;
      align-items: center;
      flex-wrap: wrap;
    }}
    .muted {{ color: var(--muted); font-size: 0.88rem; }}
    .empty {{ color: var(--muted); font-size: 0.9rem; }}
    pre {{
      margin: 0.6rem 0 0;
      padding: 0.6rem;
      border-radius: 10px;
      background: #17211d;
      color: #d9f9e9;
      min-height: 120px;
      max-height: 260px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 0.82rem;
    }}
    @media (max-width: 720px) {{
      body {{ padding: 0.6rem; }}
      .card {{ padding: 0.75rem; }}
      button {{ flex: 1; }}
    }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <article class=\"card\">
      <h1>Shopping Mode</h1>
      <p>Tap a remaining item to complete it. Swipe left on a remaining item to postpone it. Tap postponed or completed items to move them back to remaining.</p>

      <div class=\"status\">
        <span id=\"shop-mode-network\" class=\"badge\">Status: -</span>
        <span id=\"shop-mode-pending\" class=\"badge\">Pending sync: 0</span>
      </div>

      <div class=\"row\">
        <button id=\"shop-mode-refresh\" class=\"ghost\">Refresh From Server</button>
        <button id=\"shop-mode-sync\">Sync Pending Changes</button>
      </div>

      <section class=\"section\">
        <h2>Remaining by Category</h2>
        <div id=\"shop-mode-remaining\"></div>
      </section>

      <section class=\"section\">
        <h2>Postponed / Skipped</h2>
        <div id=\"shop-mode-skipped\"></div>
      </section>

      <section class=\"section\">
        <h2>Completed</h2>
        <div id=\"shop-mode-completed\"></div>
      </section>

      <pre id=\"output\">Ready.</pre>
    </article>
  </main>

  <script>window.WFD_API_PREFIX = {api_prefix!r};</script>
  <script src=\"/static/shopping_mode.js\"></script>
</body>
</html>
"""
    return HTMLResponse(content=html)
