from fastapi.responses import HTMLResponse


def render_user_app(api_prefix: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>WhatsForDinner User App</title>
  <style>
    :root {{
      --bg: #f2f7f4;
      --panel: #fcfffd;
      --ink: #1f2a25;
      --muted: #5e6b63;
      --accent: #176b5a;
      --accent-2: #a54818;
      --line: #d9e7df;
      --danger: #b42318;
      --soft: #eef6f2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 92% 2%, #d8ebe4 0%, transparent 34%),
        radial-gradient(circle at 8% 96%, #ffe3cd 0%, transparent 34%),
        var(--bg);
      min-height: 100vh;
      padding: 1.2rem;
    }}
    .shell {{ max-width: 1200px; margin: 0 auto; }}
    h1 {{ margin: 0; font-size: clamp(1.4rem, 2vw, 2rem); }}
    .sub {{ margin: 0.35rem 0 1.2rem; color: var(--muted); }}
    .grid {{
      display: grid;
      gap: 1rem;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      align-items: start;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 1rem;
      box-shadow: 0 16px 30px rgba(12, 31, 23, 0.07);
      animation: rise 0.35s ease-out;
    }}
    @keyframes rise {{
      from {{ opacity: 0; transform: translateY(8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    .wide {{ grid-column: 1 / -1; }}
    h2 {{ margin: 0 0 0.55rem; font-size: 1.02rem; }}
    h3 {{ margin: 0.3rem 0 0.45rem; font-size: 0.95rem; }}
    p {{ margin: 0.3rem 0 0.7rem; color: var(--muted); }}
    label {{ display: block; margin: 0.45rem 0 0.2rem; font-weight: 600; }}
    input, select, button, textarea {{
      width: 100%;
      padding: 0.52rem 0.62rem;
      border-radius: 8px;
      border: 1px solid var(--line);
      font: inherit;
      background: #fff;
      color: inherit;
    }}
    textarea {{ min-height: 90px; resize: vertical; }}
    button {{
      width: auto;
      cursor: pointer;
      border: none;
      margin-top: 0.45rem;
      color: #fff;
      background: var(--accent);
      font-weight: 600;
      padding: 0.52rem 0.82rem;
    }}
    button.alt {{ background: var(--accent-2); }}
    button.danger {{ background: var(--danger); }}
    button.ghost {{ background: #42524a; }}
    .row {{ display: flex; gap: 0.45rem; flex-wrap: wrap; align-items: end; }}
    .row > * {{ flex: 1; min-width: 120px; }}
    .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0.22rem 0.52rem;
      margin: 0.2rem 0.2rem 0 0;
      background: #fff;
      font-size: 0.88rem;
    }}
    .mini-grid {{
      display: grid;
      gap: 0.6rem;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    }}
    .stack {{ display: grid; gap: 0.65rem; }}
    .listbox {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--soft);
      padding: 0.5rem;
      max-height: 280px;
      overflow: auto;
    }}
    .item {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.55rem;
      margin-bottom: 0.45rem;
    }}
    .item:last-child {{ margin-bottom: 0; }}
    .item.active {{ border-color: #74b6a5; box-shadow: inset 0 0 0 1px #74b6a5; }}
    .item-head {{
      display: flex;
      gap: 0.45rem;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 0.3rem;
    }}
    .muted {{ color: var(--muted); font-size: 0.9rem; }}
    .actions {{ display: flex; gap: 0.35rem; flex-wrap: wrap; }}
    .actions button {{ margin: 0; font-size: 0.85rem; padding: 0.4rem 0.6rem; }}
    .shop-mode {{
      margin-top: 0.7rem;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: #ffffff;
      padding: 0.75rem;
    }}
    .shop-mode-head {{
      display: flex;
      justify-content: space-between;
      gap: 0.5rem;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 0.3rem;
    }}
    .shop-status {{
      display: inline-flex;
      gap: 0.35rem;
      flex-wrap: wrap;
      align-items: center;
      font-size: 0.84rem;
      color: var(--muted);
    }}
    .shop-badge {{
      display: inline-block;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 0.14rem 0.45rem;
      background: #f7fbf9;
    }}
    .shop-mode-section {{ margin-top: 0.65rem; }}
    .shop-mode-section h4 {{ margin: 0 0 0.35rem; font-size: 0.92rem; }}
    .shop-category {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.5rem;
      background: var(--soft);
      margin-bottom: 0.45rem;
    }}
    .shop-category-title {{
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
    .shop-help {{ margin: 0.2rem 0 0.5rem; color: var(--muted); font-size: 0.86rem; }}
    .shop-empty {{ color: var(--muted); font-size: 0.9rem; }}
    @media (max-width: 720px) {{
      body {{ padding: 0.75rem; }}
      .card {{ padding: 0.8rem; }}
      .actions button {{ flex: 1; }}
    }}
    pre {{
      margin: 0;
      padding: 0.85rem;
      border-radius: 10px;
      background: #17211d;
      color: #d9f9e9;
      min-height: 180px;
      max-height: 380px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }}
  </style>
</head>
<body>
  <main class=\"shell\">
    <h1>WhatsForDinner User App</h1>
    <p class=\"sub\">Workflow-first Stage 2 UI: configure keywords, plan meals, manage stored plans, generate shopping, then manage shopping items.</p>

    <section class=\"grid\">
      <article class=\"card\">
        <h2>1) Configuration</h2>
        <p>Choose the keywords used for one-meal panic and meal-plan generation.</p>
        <button id=\"cfg-load-tags\">Load Available Keywords</button>
        <label for=\"cfg-tags\">Available tags/keywords</label>
        <select id=\"cfg-tags\" multiple size=\"8\"></select>
        <div class=\"row\">
          <button id=\"cfg-load-selected\" class=\"alt\">Load Selected</button>
          <button id=\"cfg-save-selected\">Save Selected</button>
        </div>
          <label for="cfg-no-repeat-days">Don't repeat recipe within days</label>
          <input id="cfg-no-repeat-days" type="number" min="0" value="30" />
          <div class="row">
            <button id="cfg-load-rules" class="ghost">Load Plan Rules</button>
            <button id="cfg-save-rules">Save Plan Rules</button>
          </div>
        <div id=\"cfg-selected\"></div>
      </article>

      <article class=\"card\">
        <h2>2) Quick Meal Plan (1 Day)</h2>
        <p>Use the same meal-plan pipeline for a single-day plan and generate shopping from it.</p>
        <label for=\"panic-servings\">Servings</label>
        <input id=\"panic-servings\" type=\"number\" min=\"1\" value=\"1\" />
        <div class=\"row\">
          <button id="panic-run">Run Quick Meal</button>
          <button id="panic-last" class="alt">Load Newest Stored Plan</button>
        </div>
        <p>This creates a 1-day meal plan, selects it, and generates shopping list entries.</p>
      </article>

      <article class=\"card wide\">
        <h2>3) Meal Plans</h2>
        <p>Generate a plan, review stored plans, then edit or delete selected plans.</p>

        <div class=\"mini-grid\">
          <div>
            <label for=\"plan-start\">Start date</label>
            <input id=\"plan-start\" type=\"date\" />
          </div>
          <div>
            <label for=\"plan-length\">Length (days)</label>
            <input id=\"plan-length\" type=\"number\" min=\"1\" max=\"31\" value=\"7\" />
          </div>
          <div>
            <label for=\"plan-diners\">Diners</label>
            <input id=\"plan-diners\" type=\"number\" min=\"1\" value=\"2\" />
          </div>
        </div>
        <label for=\"plan-leftover\">Leftover days (1-based, comma separated)</label>
        <input id=\"plan-leftover\" type=\"text\" placeholder=\"3, 6\" />
        <label for=\"plan-takeout\">Takeout days (1-based, comma separated)</label>
        <input id=\"plan-takeout\" type=\"text\" placeholder=\"5\" />
        <label for=\"plan-empty\">Empty days (1-based, comma separated)</label>
        <input id=\"plan-empty\" type=\"text\" placeholder=\"7\" />
        <div class=\"row\">
          <button id=\"plan-generate\">Generate Plan</button>
          <button id=\"plan-list\" class=\"ghost\">List Stored Plans</button>
          <button id=\"plan-shopping\" class=\"alt\">Generate Shopping For Selected Plan</button>
        </div>

        <h3>Stored meal plans</h3>
        <div id=\"plan-listbox\" class=\"listbox\"></div>

        <div class=\"mini-grid\">
          <div>
            <label for=\"plan-id\">Selected plan ID</label>
            <input id=\"plan-id\" type=\"number\" min=\"1\" placeholder=\"Plan ID\" />
          </div>
          <div>
            <label for=\"plan-entry-id\">Entry ID</label>
            <input id=\"plan-entry-id\" type=\"number\" min=\"1\" placeholder=\"Entry ID\" />
          </div>
          <div>
            <label for=\"plan-entry-day\">Target day index</label>
            <input id=\"plan-entry-day\" type=\"number\" min=\"0\" placeholder=\"Target day index\" />
          </div>
        </div>
        <div class=\"row\">
          <button id=\"plan-fetch\" class=\"ghost\">Load Selected Plan Details</button>
          <button id=\"plan-move-entry\" class=\"alt\">Move Entry</button>
          <button id=\"plan-delete-entry\" class=\"danger\">Delete Entry</button>
          <button id=\"plan-delete\" class=\"danger\">Delete Selected Plan</button>
        </div>

        <h3>Entries in selected plan</h3>
        <div id=\"plan-entries\" class=\"listbox\"></div>
      </article>

      <article class=\"card wide\">
        <h2>4) Shopping List</h2>
        <p>After generation, all items appear below and each item can be updated directly.</p>
        <div class=\"mini-grid\">
          <div>
            <label for=\"shop-name\">Food name</label>
            <input id=\"shop-name\" type=\"text\" placeholder=\"milk\" />
          </div>
          <div>
            <label for=\"shop-amount\">Amount</label>
            <input id=\"shop-amount\" type=\"number\" value=\"1\" step=\"0.5\" />
          </div>
        </div>
        <div class=\"row\">
          <button id=\"shop-refresh\">Refresh Shopping List</button>
          <button id=\"shop-add\" class=\"alt\">Add Item</button>
        </div>

        <h3>Remaining items</h3>
        <div id=\"shop-remaining\" class=\"listbox\"></div>

        <h3>Skipped items</h3>
        <div id=\"shop-skipped\" class=\"listbox\"></div>

        <h3>Completed items</h3>
        <div id=\"shop-completed\" class=\"listbox\"></div>

        <div class=\"row\">
          <input id=\"sync-cursor\" type=\"number\" min=\"0\" value=\"0\" placeholder=\"Since cursor\" />
          <button id=\"sync-pull\" class=\"ghost\">Pull Sync Changes</button>
        </div>

        <p>Use the dedicated phone-friendly shopping screen at <a href=\"/shopping\">/shopping</a>.</p>
      </article>

      <article class=\"card wide\">
        <h2>API Result</h2>
        <pre id=\"output\">Ready.</pre>
      </article>
    </section>
  </main>

  <script>window.WFD_API_PREFIX = {api_prefix!r};</script>
  <script src=\"/static/user_app.js\"></script>
</body>
</html>
"""
    return HTMLResponse(content=html)
