from fastapi.responses import HTMLResponse


def render_inspector(api_prefix: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>WhatsForDinner API Inspector</title>
  <style>
    :root {{
      --bg: #f7f3ea;
      --panel: #fffdfa;
      --ink: #26211c;
      --accent: #bc5f04;
      --accent-2: #226f54;
      --muted: #6e6257;
      --border: #e6d9c9;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 85% 5%, #ffddba 0%, transparent 40%),
        radial-gradient(circle at 10% 95%, #d8f0e6 0%, transparent 40%),
        var(--bg);
      min-height: 100vh;
      display: grid;
      place-items: start center;
      padding: 2rem 1rem;
    }}
    .card {{
      width: min(920px, 100%);
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 16px 32px rgba(44, 33, 22, 0.08);
      overflow: hidden;
      animation: rise 0.5s ease-out;
    }}
    @keyframes rise {{
      from {{ transform: translateY(10px); opacity: 0; }}
      to {{ transform: translateY(0); opacity: 1; }}
    }}
    header {{
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      background: linear-gradient(110deg, #fffaf2, #fff);
    }}
    h1 {{
      margin: 0;
      font-size: clamp(1.2rem, 1.8vw, 1.6rem);
    }}
    header p {{
      margin: 0.35rem 0 0;
      color: var(--muted);
    }}
    .grid {{
      display: grid;
      gap: 1rem;
      padding: 1rem;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    }}
    .panel {{
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      background: #fff;
    }}
    .panel h2 {{
      margin-top: 0;
      font-size: 1rem;
    }}
    input, button {{
      font: inherit;
      border-radius: 8px;
      border: 1px solid var(--border);
      padding: 0.5rem 0.6rem;
    }}
    input {{ width: 100%; box-sizing: border-box; margin: 0.45rem 0 0.7rem; }}
    button {{
      cursor: pointer;
      border: none;
      background: var(--accent);
      color: #fff;
      font-weight: 600;
      transition: transform 0.15s ease, background 0.15s ease;
    }}
    button:hover {{ transform: translateY(-1px); background: #a15304; }}
    .secondary {{ background: var(--accent-2); }}
    .secondary:hover {{ background: #1d5f48; }}
    pre {{
      margin: 0;
      background: #1c1917;
      color: #d2f4dd;
      border-radius: 10px;
      padding: 1rem;
      overflow: auto;
      min-height: 220px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .output {{ padding: 0 1rem 1rem; }}
  </style>
</head>
<body>
  <main class=\"card\">
    <header>
      <h1>WhatsForDinner REST Inspector</h1>
      <p>Try mobile-facing endpoints and inspect JSON responses directly in your browser.</p>
    </header>
    <section class=\"grid\">
      <article class=\"panel\">
        <h2>Recipes</h2>
        <label for=\"search\">Search</label>
        <input id=\"search\" type=\"text\" placeholder=\"chicken, soup, pasta...\" />
        <label for=\"limit\">Limit</label>
      <article class="panel">
        <h2>Recipe Tags</h2>
        <p>Fetch available Tandoor recipe tags and categories.</p>
        <button id="tags">GET /recipe-tags</button>
      </article>
      <article class="panel">
        <h2>Today Meal</h2>
        <p>Fetch a normalized today meal payload for app and Home Assistant.</p>
        <button id="today" class="secondary">GET /today-meal</button>
      </article>
        <input id=\"limit\" type=\"number\" value=\"10\" min=\"1\" max=\"100\" />
        <button id=\"recipes\">GET /recipes</button>
      </article>
      <article class=\"panel\">
        <h2>Shopping List</h2>
        <p>Fetch current shopping list from Tandoor through this API.</p>
        <button id=\"shopping\" class=\"secondary\">GET /shopping-list</button>
      </article>
    </section>
    <section class=\"output\">
      <pre id=\"output\">Response will appear here...</pre>
    </section>
  </main>
  <script>
    const apiPrefix = {api_prefix!r};
    const output = document.getElementById("output");

    async function callApi(path) {{
      output.textContent = "Loading...";
      try {{
        const res = await fetch(`${{apiPrefix}}${{path}}`);
        const data = await res.json();
        output.textContent = JSON.stringify(data, null, 2);
      }} catch (err) {{
        output.textContent = `Request failed: ${{err}}`;
      }}
    }}

    document.getElementById("recipes").addEventListener("click", () => {{
      const search = document.getElementById("search").value.trim();
      const limit = document.getElementById("limit").value || "10";
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      params.set("limit", limit);
      callApi(`/recipes?${{params.toString()}}`);
    }});

    document.getElementById("shopping").addEventListener("click", () => {{
      callApi("/shopping-list");
    }});

    document.getElementById("tags").addEventListener("click", () => {{
      callApi("/recipe-tags");
    }});

    document.getElementById("today").addEventListener("click", () => {{
      callApi("/today-meal");
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
