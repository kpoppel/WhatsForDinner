import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_store_commands_and_selectors_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    selectors_path = (repo_root / "app/static/js/store/selectors.js").as_uri()
    api_path = (repo_root / "app/static/js/api.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
  removeItem(key) {{ this.map.delete(key); }}
}}

globalThis.localStorage = new LocalStorageMock();
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};

const commands = await import({commands_path!r});
const selectors = await import({selectors_path!r});
const apiClient = await import({api_path!r});

commands.cachePlanListRows([{{ plan_id: 1, start_date: '2026-08-20' }}]);
let cache = selectors.readMealPlanCache();
if (!Array.isArray(cache.list) || cache.list.length !== 1) {{
  throw new Error('cachePlanListRows did not persist list cache');
}}
cache.list[0].start_date = 'modified';
if (selectors.readMealPlanCache().list[0].start_date === 'modified') {{
  throw new Error('meal-plan selectors must return snapshots');
}}

commands.cachePlanDetail({{ plan_id: 1, entries: [{{ entry_id: 11 }}] }});
cache = selectors.readMealPlanCache();
if (!cache.byId || !cache.byId['1'] || cache.byId['1'].entries.length !== 1) {{
  throw new Error('cachePlanDetail did not persist byId cache');
}}

commands.writeActiveMealPlanId(42);
if (selectors.readActiveMealPlanId() !== 42) {{
  throw new Error('writeActiveMealPlanId/readActiveMealPlanId mismatch');
}}

commands.writeHomeActivePlanCache({{ plan_id: 7, entries: [{{ day_index: 1 }}, {{ day_index: 0 }}] }});
const homeCache = selectors.readHomeActivePlanCache((entries) =>
  [...(entries || [])].sort((a, b) => a.day_index - b.day_index)
);
if (!homeCache || !homeCache.plan || homeCache.plan.plan_id !== 7) {{
  throw new Error('writeHomeActivePlanCache/readHomeActivePlanCache mismatch');
}}
if (!Array.isArray(homeCache.entries) || homeCache.entries[0].day_index !== 0) {{
  throw new Error('readHomeActivePlanCache did not apply sorter');
}}

let request = null;
globalThis.fetch = async (url, options) => {{
  request = {{ url, options }};
  return {{ ok: true, json: async () => ({{ source: 'ok' }}) }};
}};
const okPayload = await apiClient.api('/health');
if (!okPayload || okPayload.source !== 'ok') {{
  throw new Error('api success path smoke failed');
}}
if (request.url !== '/api/v1/health' || request.options.headers['Content-Type'] !== 'application/json') {{
  throw new Error('api request construction smoke failed');
}}

globalThis.fetch = async () => ({{ ok: false, json: async () => ({{ detail: 'boom' }}) }});
let failed = false;
try {{
  await apiClient.api('/health');
}} catch (error) {{
  failed = String(error).includes('boom');
}}
if (!failed) {{
  throw new Error('api error path smoke failed');
}}

let uploadRequest = null;
const formData = {{ source: 'camera' }};
globalThis.fetch = async (url, options) => {{
  uploadRequest = {{ url, options }};
  return {{ ok: true, json: async () => ({{ rows: [] }}) }};
}};
await apiClient.apiUpload('/shopping-list/ocr', formData);
if (uploadRequest.url !== '/api/v1/shopping-list/ocr' || uploadRequest.options.body !== formData) {{
  throw new Error('api upload request construction smoke failed');
}}

let healthRequest = null;
globalThis.fetch = async (url, options) => {{
  healthRequest = {{ url, options }};
  return {{ ok: true, json: async () => ({{ status: 'ok' }}) }};
}};
await apiClient.health();
if (healthRequest.url !== '/api/v1/health' || healthRequest.options.cache !== 'no-store') {{
  throw new Error('health request construction smoke failed');
}}
"""

    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, f"Node smoke test failed\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"


def test_application_fetches_are_isolated_to_api_layer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    static_root = repo_root / "app/static"
    allowed_paths = {
        static_root / "js/api.js",
        static_root / "shopping-sw.js",
    }

    fetch_users = []
    for source_path in static_root.rglob("*.js"):
        if "fetch(" in source_path.read_text(encoding="utf-8"):
            fetch_users.append(source_path)

    assert set(fetch_users) == allowed_paths


def test_service_worker_precaches_client_module_graph() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "app/static/shopping-sw.js").read_text(encoding="utf-8")
    required_paths = (
        "/static/js/commands/connectivity.js",
        "/static/js/commands/home.js",
        "/static/js/commands/meal-plans.js",
        "/static/js/commands/settings.js",
        "/static/js/commands/shopping-ui.js",
        "/static/js/commands/shopping.js",
        "/static/js/selectors/connectivity.js",
        "/static/js/selectors/shopping.js",
        "/static/js/store/meal-plan-model.js",
    )

    missing_paths = [path for path in required_paths if path not in source]
    assert not missing_paths, f"Service worker omits client modules: {missing_paths}"


def test_ui_modules_do_not_import_api_or_shopping_state() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    static_root = repo_root / "app/static"
    ui_paths = [
        static_root / "home_tab.js",
        static_root / "meal_plans.js",
        static_root / "settings_tab.js",
        static_root / "shop_editor.js",
        static_root / "user_shell.js",
        static_root / "js/gestures.js",
        static_root / "js/render.js",
        static_root / "js/shopping.js",
    ]
    prohibited_imports = (
        'from "./js/api.js"',
        'from "./js/state.js"',
        'from "./api.js"',
        'from "./state.js"',
    )

    violations = []
    for source_path in ui_paths:
        source = source_path.read_text(encoding="utf-8")
        if any(import_text in source for import_text in prohibited_imports):
            violations.append(str(source_path.relative_to(repo_root)))

    assert not violations, f"UI modules bypass command/selector boundaries: {violations}"


def test_selector_modules_are_read_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    selector_paths = [
        repo_root / "app/static/js/selectors/connectivity.js",
        repo_root / "app/static/js/selectors/shopping.js",
        repo_root / "app/static/js/store/selectors.js",
    ]
    prohibited_references = (
        "localStorage.",
        "fetch(",
        'from "../api.js"',
        'from "../commands/',
        'from "./commands/',
    )

    violations = []
    for source_path in selector_paths:
        source = source_path.read_text(encoding="utf-8")
        if any(reference in source for reference in prohibited_references):
            violations.append(str(source_path.relative_to(repo_root)))

    assert not violations, f"Selectors have mutable or remote dependencies: {violations}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_state_queue_create_changes_keep_distinct_entries() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    state_path = (repo_root / "app/static/js/state.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
  removeItem(key) {{ this.map.delete(key); }}
}}

globalThis.localStorage = new LocalStorageMock();

const stateModule = await import({state_path!r});
const {{ state, queueCreateChange }} = stateModule;

state.itemsById = {{}};
state.pendingChanges = [];

for (const [id, name] of [[-1, 'milk'], [-2, 'eggs'], [-3, 'bread']]) {{
  queueCreateChange({{
    id,
    ad_hoc: true,
    name,
    amount: 0,
    unit: '',
    ingredient_type: 'Other',
    store_group: {{ id: null, name: 'Other' }},
    recipe_context: 'Unassigned',
    status: 'remaining',
    reminder_enabled: false,
    reminder_date: null,
    reminder_text: '',
  }});
}}

if (!Array.isArray(state.pendingChanges) || state.pendingChanges.length !== 3) {{
  throw new Error(`Expected 3 pending create changes, got ${{state.pendingChanges.length}}`);
}}

const ids = state.pendingChanges.map((change) => change.entry_id);
if (!ids.every((id) => Number.isInteger(id))) {{
  throw new Error('All create changes must include integer entry_id values');
}}

const uniqueIds = new Set(ids);
if (uniqueIds.size !== 3) {{
  throw new Error(`Expected 3 distinct entry_id values, got ${{Array.from(uniqueIds).join(',')}}`);
}}
"""

    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, (
        "Node queue-create regression test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_shopping_sync_hydrates_only_after_rejected_changes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sync_path = (repo_root / "app/static/js/sync.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
}}

function element() {{
  return {{
    classList: {{ toggle() {{}} }},
    style: {{}},
    setAttribute() {{}},
    appendChild() {{}},
    innerHTML: '',
    textContent: '',
  }};
}}

globalThis.localStorage = new LocalStorageMock();
Object.defineProperty(globalThis, 'navigator', {{ value: {{ onLine: true }}, configurable: true }});
globalThis.window = {{
  WFD_API_PREFIX: '/api/v1',
  dispatchEvent() {{}},
  alert() {{}},
}};
globalThis.CustomEvent = class {{ constructor(name, options) {{ this.name = name; this.options = options; }} }};
globalThis.document = {{ getElementById() {{ return element(); }} }};

const calls = [];
globalThis.fetch = async (url) => {{
  calls.push(url);
  if (url.endsWith('/shopping-list/sync')) {{
    return {{ ok: true, json: async () => ({{ applied: [{{}}], rejected: [], server_cursor: 1 }}) }};
  }}
  return {{ ok: true, json: async () => ({{
    data: {{ sections: {{ remaining: [], skipped: [], completed: [] }} }},
    cursor: 2,
  }}) }};
}};

const sync = await import({sync_path!r});
const stateModule = await import({(repo_root / 'app/static/js/state.js').as_uri()!r});
stateModule.state.itemsById = {{}};
stateModule.state.pendingChanges = [{{ operation: 'delete', entry_id: 1, queued_at: '2026-09-05T00:00:00Z' }}];

await sync.syncPending(false);
if (calls.length !== 1 || !calls[0].endsWith('/shopping-list/sync')) {{
  throw new Error(`Successful sync should only POST once, got ${{calls.join(', ')}}`);
}}

stateModule.state.pendingChanges = [{{ operation: 'delete', entry_id: 2, queued_at: '2026-09-05T00:00:00Z' }}];
globalThis.fetch = async (url) => {{
  calls.push(url);
  if (url.endsWith('/shopping-list/sync')) {{
    return {{ ok: true, json: async () => ({{ applied: [], rejected: [{{ index: 0 }}], server_cursor: 2 }}) }};
  }}
  return {{ ok: true, json: async () => ({{
    data: {{ sections: {{ remaining: [], skipped: [], completed: [] }} }},
    cursor: 3,
  }}) }};
}};

await sync.syncPending(false);
if (calls.length !== 3 || !calls[2].endsWith('/shopping-list/view')) {{
  throw new Error(`Rejected sync should hydrate once, got ${{calls.join(', ')}}`);
}}
"""

    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, (
        "Node shopping-sync regression test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )
