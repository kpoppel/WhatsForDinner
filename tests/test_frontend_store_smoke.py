"""Browser-module contract tests executed through Node and source assertions."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_store_commands_and_selectors_smoke() -> None:
    """Verify store commands and selectors can load and execute in Node."""
    repo_root = Path(__file__).resolve().parents[1]
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    selectors_path = (repo_root / "app/static/js/store/selectors.js").as_uri()

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

commands.cachePlanListRows([{{ plan_id: 1, start_date: '2026-08-20' }}]);
let cache = selectors.readMealPlanCache();
if (!Array.isArray(cache.list) || cache.list.length !== 1) {{
  throw new Error('cachePlanListRows did not persist list cache');
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

"""

    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, f"Node smoke test failed\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_state_queue_create_changes_keep_distinct_entries() -> None:
    """Verify queued creates retain distinct optimistic shopping entries."""
    repo_root = Path(__file__).resolve().parents[1]
    state_path = (repo_root / "app/static/js/store/index.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
  removeItem(key) {{ this.map.delete(key); }}
}}

globalThis.localStorage = new LocalStorageMock();

const stateModule = await import({state_path!r});
const {{ store, queueCreateChange }} = stateModule;

store.shopping.itemsById = {{}};
store.shopping.pendingChanges = [];

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

if (!Array.isArray(store.shopping.pendingChanges) || store.shopping.pendingChanges.length !== 3) {{
  throw new Error(`Expected 3 pending create changes, got ${{store.shopping.pendingChanges.length}}`);
}}

const ids = store.shopping.pendingChanges.map((change) => change.entry_id);
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
def test_shopping_state_mutations_are_optimistic_and_persisted() -> None:
    """Verify shopping mutations update both the model and local persistence."""
    repo_root = Path(__file__).resolve().parents[1]
    state_path = (repo_root / "app/static/js/store/index.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
  removeItem(key) {{ this.map.delete(key); }}
}}

globalThis.localStorage = new LocalStorageMock();

const stateModule = await import({state_path!r});
const {{ loadShoppingCache, store, queueDeleteChange, queueUpdateChange }} = stateModule;

store.shopping.itemsById = {{
  '41': {{ id: 41, name: 'Milk', amount: 1, status: 'remaining' }},
}};
store.shopping.pendingChanges = [];

queueUpdateChange(41, {{ amount: 2 }});
if (store.shopping.itemsById['41'].amount !== 2) {{
  throw new Error('queueUpdateChange did not update model state immediately');
}}
if (store.shopping.pendingChanges.length !== 1 || store.shopping.pendingChanges[0].operation !== 'update') {{
  throw new Error('queueUpdateChange did not retain one pending update');
}}

let persisted = JSON.parse(localStorage.getItem('wfd.shopping-mode.v1'));
if (persisted.itemsById['41'].amount !== 2 || persisted.pendingChanges.length !== 1) {{
  throw new Error('queueUpdateChange did not persist optimistic state');
}}

store.shopping.itemsById = {{}};
store.shopping.pendingChanges = [];
loadShoppingCache();
if (store.shopping.itemsById['41'].amount !== 2) {{
  throw new Error('shopping persistence round-trip failed');
}}

queueDeleteChange(41);
if (Object.prototype.hasOwnProperty.call(store.shopping.itemsById, '41')) {{
  throw new Error('queueDeleteChange did not remove model state immediately');
}}
if (store.shopping.pendingChanges.length !== 1 || store.shopping.pendingChanges[0].operation !== 'delete') {{
  throw new Error('queueDeleteChange did not retain one pending delete');
}}

persisted = JSON.parse(localStorage.getItem('wfd.shopping-mode.v1'));
if (Object.prototype.hasOwnProperty.call(persisted.itemsById, '41')) {{
  throw new Error('queueDeleteChange did not persist optimistic deletion');
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
        "Node optimistic-state contract test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_shopping_sync_batches_preserve_newer_and_rejected_changes() -> None:
    """Verify sync batching preserves newer changes and rejection records."""
    repo_root = Path(__file__).resolve().parents[1]
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    store_path = (repo_root / "app/static/js/store/index.js").as_uri()
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
const {{ store }} = await import({store_path!r});
store.shopping.itemsById = {{
  '1': {{ id: 1, name: 'Milk', status: 'remaining' }},
  '2': {{ id: 2, name: 'Bread', status: 'remaining' }},
}};
commands.updateShoppingChange(1, {{ status: 'completed' }});
const outgoing = commands.takeShoppingPendingChanges();
commands.updateShoppingChange(2, {{ status: 'skipped' }});
commands.applyShoppingSyncResult(outgoing, [{{ index: 0, reason: 'write failed' }}]);

if (store.shopping.pendingChanges.length !== 1 || store.shopping.pendingChanges[0].entry_id !== 2) {{
  throw new Error('newer queued change was lost or replaced by the completed batch');
}}
if (store.shopping.rejectedChanges.length !== 1 || store.shopping.rejectedChanges[0].entry_id !== 1) {{
  throw new Error('failed write was not moved to the rejected collection');
}}
commands.hydrateShoppingModel({{
  remaining: [
    {{ id: 1, name: 'Milk', status: 'remaining' }},
    {{ id: 2, name: 'Bread', status: 'remaining' }},
  ],
  skipped: [],
  completed: [],
}}, 4);
if (store.shopping.itemsById['1'].status !== 'completed' || store.shopping.itemsById['2'].status !== 'skipped') {{
  throw new Error('canonical hydration hid rejected or newer optimistic values');
}}
commands.hydrateShoppingModel({{ remaining: [], skipped: [], completed: [] }}, 5);
if (store.shopping.rejectedChanges.length !== 0) {{
  throw new Error('canonical hydration retained a rejected change for a missing server entry');
}}
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, f"Node shopping batch contract failed\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"


def test_phase_zero_frontend_boundary_inventory_matches_source() -> None:
    """Verify the baseline inventory still matches the implemented frontend boundaries."""
    repo_root = Path(__file__).resolve().parents[1]

    expected_direct_fetch_owners = {"app/static/js/api.js"}
    candidate_paths = [
        "app/static/js/store/index.js",
        "app/static/js/store/schema.js",
        "app/static/js/store/commands.js",
        "app/static/js/store/selectors.js",
        "app/static/js/api.js",
        "app/static/js/sync.js",
        "app/static/js/shopping.js",
        "app/static/shop_editor.js",
        "app/static/meal_plans.js",
        "app/static/home_tab.js",
        "app/static/settings_tab.js",
        "app/static/user_shell.js",
    ]

    for relative_path in candidate_paths:
        assert (repo_root / relative_path).is_file(), f"Missing Phase 0 candidate: {relative_path}"

    actual_direct_fetch_owners = {
        relative_path
        for relative_path in candidate_paths
        if "fetch(" in (repo_root / relative_path).read_text(encoding="utf-8")
    }
    assert actual_direct_fetch_owners == expected_direct_fetch_owners

    ui_paths = [
      "app/static/home_tab.js",
      "app/static/meal_plans.js",
      "app/static/settings_tab.js",
      "app/static/shop_editor.js",
      "app/static/js/render.js",
      "app/static/js/shopping.js",
    ]
    endpoint_fragments = ("/meal-plans", "/shopping-list", "/config/", "/recipes?")
    for relative_path in ui_paths:
      source = (repo_root / relative_path).read_text(encoding="utf-8")
      assert not any(fragment in source for fragment in endpoint_fragments), relative_path
      assert "shoppingState(" not in source, relative_path

    shop_editor_source = (repo_root / "app/static/shop_editor.js").read_text(encoding="utf-8")
    assert "from \"./js/state.js\"" not in shop_editor_source
    assert "createShoppingChange" in shop_editor_source

    for relative_path in [
      "app/static/js/shopping.js",
      "app/static/js/sync.js",
      "app/static/js/render.js",
      "app/static/js/api.js",
    ]:
      source = (repo_root / relative_path).read_text(encoding="utf-8")
      assert "from \"./state.js\"" not in source, relative_path

    settings_source = (repo_root / "app/static/settings_tab.js").read_text(encoding="utf-8")
    assert "selectSettings" in settings_source
    assert "let defaultDinersValue" not in settings_source
    assert "let noRepeatDaysValue" not in settings_source

    meal_plans_source = (repo_root / "app/static/meal_plans.js").read_text(encoding="utf-8")
    assert "selectMealPlans" in meal_plans_source
    assert "let selectedPlanId" not in meal_plans_source
    assert "let selectedPlan" not in meal_plans_source

    sync_source = (repo_root / "app/static/js/sync.js").read_text(encoding="utf-8")
    assert "createSyncCoordinator" in sync_source
    assert "coordinator.push(" in sync_source
    assert "await refresh();" in sync_source
    assert "if (payload.data && payload.data.sections)" in sync_source

    shop_editor_source = (repo_root / "app/static/shop_editor.js").read_text(encoding="utf-8")
    assert "await syncPending(false);\n    await refresh();" not in shop_editor_source
    assert "await refresh();" in shop_editor_source


def test_service_worker_requires_complete_shell_and_uses_network_first_navigation() -> None:
    """Verify the PWA precache and navigation fallback policy remain explicit."""
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "app/static/shopping-sw.js").read_text(encoding="utf-8")

    assert "cache.addAll(APP_SHELL)" in source
    assert "Ignore individual precache failures" not in source
    assert "const response = await fetch(request);" in source
    assert "return cachedShell || Response.error();" in source
    assert ".then(() => self.clients.claim())" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend coordinator tests")
def test_phase_three_sync_coordinator_contract() -> None:
    """Verify refresh and push coordination rejects stale asynchronous results."""
    repo_root = Path(__file__).resolve().parents[1]
    coordinator_path = (repo_root / "app/static/js/sync_coordinator.js").as_uri()
    script = f"""
  const {{ createSyncCoordinator }} = await import({coordinator_path!r});
  const statuses = [];
  const coordinator = createSyncCoordinator({{ onStatus: (value) => statuses.push(value.status) }});

  let refreshCalls = 0;
  let releaseRefresh;
  const refreshResult = new Promise((resolve) => {{ releaseRefresh = resolve; }});
  const applied = [];
  const firstRefresh = coordinator.refresh(
    async () => {{ refreshCalls += 1; return refreshResult; }},
    (payload) => applied.push(payload),
  );
  const secondRefresh = coordinator.refresh(
    async () => {{ refreshCalls += 1; return {{ id: 2 }}; }},
    (payload) => applied.push(payload),
  );
  if (firstRefresh !== secondRefresh) throw new Error('refresh calls were not coalesced');
  releaseRefresh({{ id: 1 }});
  await firstRefresh;
  if (refreshCalls !== 1 || applied.length !== 1 || applied[0].id !== 1) throw new Error('refresh coalescing failed');

  let releasePush;
  let pushCalls = 0;
  const pushResult = new Promise((resolve) => {{ releasePush = resolve; }});
  let releaseStaleRefresh;
  const staleRefreshResult = new Promise((resolve) => {{ releaseStaleRefresh = resolve; }});
  const pushed = [];
  const staleRefresh = coordinator.refresh(
    async () => staleRefreshResult,
    (payload) => pushed.push(payload),
  );
  const firstPush = coordinator.push('first', async () => {{ pushCalls += 1; return pushResult; }}, (payload) => pushed.push(payload));
  const secondPush = coordinator.push('second', async () => {{ pushCalls += 1; return {{ id: 2 }}; }}, (payload) => pushed.push(payload));
  releasePush({{ id: 1 }});
  releaseStaleRefresh({{ id: 'stale' }});
  await firstPush;
  await secondPush;
  await staleRefresh;
  if (pushCalls !== 2) throw new Error(`expected two serialized pushes, got ${{pushCalls}}`);
  if (pushed.some((payload) => payload.id === 'stale')) throw new Error('stale refresh was applied after push');
  if (!statuses.includes('pushing') || !statuses.includes('idle')) throw new Error('sync status was not observable');

  const queuedCoordinator = createSyncCoordinator({{ onStatus: () => {{}} }});
  const queuedCalls = [];
  let releaseQueuedFirst;
  const queuedFirstResult = new Promise((resolve) => {{ releaseQueuedFirst = resolve; }});
  const queuedFirst = queuedCoordinator.push(
    'one',
    async () => {{ queuedCalls.push('one'); return queuedFirstResult; }},
    async () => {{}},
  );
  const queuedSecond = queuedCoordinator.push(
    'two',
    async () => {{ queuedCalls.push('two'); return {{ id: 2 }}; }},
    async () => {{}},
  );
  const queuedThird = queuedCoordinator.push(
    'three',
    async () => {{ queuedCalls.push('three'); return {{ id: 3 }}; }},
    async () => {{}},
  );
  releaseQueuedFirst({{ id: 1 }});
  await Promise.all([queuedFirst, queuedSecond, queuedThird]);
  if (queuedCalls.join(',') !== 'one,two,three') {{
    throw new Error(`queued pushes were replaced or reordered: ${{queuedCalls.join(',')}}`);
  }}

  const failure = new Error('sync unavailable');
  const failedCoordinator = createSyncCoordinator({{ onStatus: () => {{}} }});
  try {{
    await failedCoordinator.push('failed', async () => {{ throw failure; }}, async () => {{}});
    throw new Error('failed push unexpectedly resolved');
  }} catch (error) {{
    if (error !== failure) throw new Error(`failed push masked the original error: ${{error}}`);
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
      "Node sync coordinator contract test failed\n"
      f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend render tests")
def test_phase_five_render_generation_contract() -> None:
    """Verify render generations prevent delayed work from overwriting newer UI."""
    repo_root = Path(__file__).resolve().parents[1]
    render_path = (repo_root / "app/static/js/render.js").as_uri()
    script = f"""
const nodes = new Map();
function node() {{
  return {{
    style: {{}},
    dataset: {{}},
    classList: {{ toggle() {{}} }},
    setAttribute() {{}},
    innerHTML: "",
    textContent: "",
    appendChild() {{}},
  }};
}}
for (const id of [
  'output', 'shop-mode-network', 'shop-mode-pending', 'shop-mode-pending-count',
  'shop-mode-remaining', 'shop-mode-skipped', 'shop-mode-completed',
  'shop-mode-remaining-title', 'shop-mode-skipped-title', 'shop-mode-completed-title',
]) nodes.set(id, node());
globalThis.document = {{ body: {{ dataset: {{}} }}, getElementById: (id) => nodes.get(id) }};
Object.defineProperty(globalThis, 'navigator', {{ value: {{ onLine: true }}, writable: true }});
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};
const metrics = [];
window.WFD_recordRenderMetric = (metric) => metrics.push(metric);
const renderModule = await import({render_path!r});
const first = renderModule.render({{ source: 'optimistic', status: 'optimistic', generation: 4, revision: 7 }});
const stale = renderModule.render({{ source: 'server', status: 'server', generation: 3, revision: 7 }});
if (!first || stale || renderModule.getLastRenderMeta().source !== 'optimistic') {{
  throw new Error('stale render generation was accepted');
}}
const canonical = renderModule.render({{ source: 'canonical', status: 'server', generation: 5, revision: 8 }});
if (!canonical || renderModule.getLastRenderMeta().source !== 'canonical' ||
    metrics.length !== 2 || metrics[0].generation !== 4 || metrics[1].revision !== 8 ||
    document.body.dataset.wfdRenderStatus !== 'server') {{
  throw new Error('render metadata contract failed');
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
        "Node render contract test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for render scheduler tests")
def test_phase_five_render_scheduler_contract() -> None:
    """Verify render scheduling coalesces requests and retains latest metadata."""
    repo_root = Path(__file__).resolve().parents[1]
    scheduler_path = (repo_root / "app/static/js/render_scheduler.js").as_uri()
    script = f"""
const {{ createRenderScheduler }} = await import({scheduler_path!r});
let revision = 3;
const rendered = [];
const metrics = [];
const scheduler = createRenderScheduler({{
  getRevision: () => revision,
  render: (request) => rendered.push(request.source),
  onRender: (metric) => metrics.push(metric),
}});
if (!scheduler.request({{ source: 'navigation', revision: 3 }})) throw new Error('first render was not queued');
if (!scheduler.request({{ source: 'store-change', revision: 3 }})) throw new Error('same-turn render was not queued');
await Promise.resolve();
if (rendered.length !== 1 || rendered[0] !== 'store-change' || metrics[0].renderCount !== 1) {{
  throw new Error('same-turn renders were not coalesced');
}}
if (scheduler.request({{ source: 'unchanged-navigation', revision: 3 }})) throw new Error('unchanged navigation rendered');
if (scheduler.request({{ source: 'stale', revision: 2 }})) throw new Error('stale revision rendered');
revision = 4;
if (!scheduler.request({{ source: 'server', revision: 4 }})) throw new Error('new revision was not queued');
await Promise.resolve();
if (rendered.length !== 2 || scheduler.getRenderCount() !== 2) throw new Error('new revision render failed');
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, (
        "Node render scheduler contract test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for cross-tab tests")
def test_phase_five_cross_tab_store_notification_contract() -> None:
    """Verify cross-tab storage changes notify the store observers."""
    repo_root = Path(__file__).resolve().parents[1]
    index_path = (repo_root / "app/static/js/store/index.js").as_uri()
    script = f"""
const listeners = new Map();
globalThis.window = {{ addEventListener: (name, handler) => listeners.set(name, handler) }};
globalThis.localStorage = {{
  value: JSON.stringify({{ itemsById: {{ '3': {{ id: 3, name: 'Beans' }} }}, pendingChanges: [] }}),
  getItem() {{ return this.value; }},
  setItem() {{}},
  removeItem() {{}},
}};
const index = await import({index_path!r});
const notifications = [];
index.subscribe((notification) => notifications.push(notification));
index.installCrossTabSync();
listeners.get('storage')({{ key: 'wfd.shopping-mode.v1' }});
if (notifications.length !== 1 || notifications[0].source !== 'cross-tab' ||
    index.store.shopping.itemsById['3'].name !== 'Beans') {{
  throw new Error('cross-tab store notification contract failed');
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
        "Node cross-tab contract test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend gateway tests")
def test_phase_two_gateway_contract() -> None:
    """Verify gateway methods map to the expected API paths and operations."""
    repo_root = Path(__file__).resolve().parents[1]
    api_path = (repo_root / "app/static/js/api.js").as_uri()
    script = f"""
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};
globalThis.performance = {{ now: () => 10 }};
const apiModule = await import({api_path!r});
const {{ gateway }} = apiModule;
const {{ selectShoppingApiReachable }} = await import('./app/static/js/store/selectors.js');
const metrics = [];
window.WFD_recordApiMetric = (metric) => metrics.push(metric);

let request = null;
globalThis.fetch = async (url, options) => {{
  request = {{ url, options }};
  return {{ ok: true, status: 200, headers: {{ get: () => null }}, json: async () => ({{ status: 'ok' }}) }};
}};
const healthPayload = await apiModule.health();
if (healthPayload.status !== 'ok' || request.url !== '/api/v1/health' || request.options.cache !== 'no-store') {{
  throw new Error('health gateway contract failed');
}}

const formData = {{ name: 'photo' }};
await apiModule.apiUpload('/shopping-list/ocr', formData);
if (request.options.body !== formData || request.options.headers) {{
  throw new Error('upload gateway contract failed');
}}

globalThis.fetch = async (url, options) => {{
  request = {{ url, options }};
  return {{ ok: true, status: 200, headers: {{ get: () => null }}, json: async () => ({{ data: {{ sections: {{}} }} }}) }};
}};
await gateway.shopping.sync([{{ operation: 'update', entry_id: 4 }}]);
if (request.url !== '/api/v1/shopping-list/sync' || request.options.method !== 'POST' ||
    request.options.body !== JSON.stringify({{ changes: [{{ operation: 'update', entry_id: 4 }}] }})) {{
  throw new Error('shopping domain gateway contract failed');
}}

await gateway.mealPlans.patchEntry(8, 12, {{ servings: 4 }});
if (request.url !== '/api/v1/meal-plans/8/entries/12' || request.options.method !== 'PATCH' ||
    request.options.body !== JSON.stringify({{ servings: 4 }})) {{
  throw new Error('meal-plan domain gateway contract failed');
}}

await gateway.synchronization.retry('operation 7');
if (request.url !== '/api/v1/sync/pending/operation%207/retry' || request.options.method !== 'POST') {{
  throw new Error('projection retry gateway contract failed');
}}

globalThis.fetch = async () => ({{ ok: false, status: 503, headers: {{ get: () => null }}, json: async () => ({{ detail: 'unavailable' }}) }});
let failed = null;
try {{ await apiModule.api('/health'); }} catch (error) {{ failed = error; }}
if (!failed || failed.message !== 'unavailable' || failed.status !== 503 || failed.detail !== 'unavailable') {{
  throw new Error('normalized HTTP error contract failed');
}}
if (!selectShoppingApiReachable()) throw new Error('HTTP error incorrectly marked the reachable API offline');

globalThis.fetch = async () => ({{ ok: true, status: 200, headers: {{ get: () => null }}, json: async () => {{ throw new Error('invalid json'); }} }});
try {{ await apiModule.api('/health'); }} catch (error) {{
  if (!String(error).includes('invalid json')) throw new Error('malformed response contract failed');
}}

globalThis.fetch = async () => {{ throw new Error('network down'); }};
try {{ await apiModule.api('/health'); }} catch (error) {{
  if (!String(error).includes('network down')) throw new Error('network error contract failed');
}}
if (selectShoppingApiReachable()) throw new Error('network failure did not mark the API offline');
if (metrics.length < 4 || !metrics.every((metric) => metric.requestId && metric.operation)) {{
  throw new Error('gateway metrics were not recorded');
}}
if (metrics[0].operation !== 'health' || metrics[2].operation !== 'shopping.sync' || metrics[0].responseSize !== 15) {{
  throw new Error('gateway metric semantics failed');
}}
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, f"Node gateway contract test failed\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"


def test_settings_screen_does_not_capture_replaceable_store_collections() -> None:
    """Verify settings rendering does not retain stale mutable store collections."""
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "app/static/settings_tab.js").read_text(encoding="utf-8")

    assert "const settings = selectSettings();\n  const keywordCatalog" not in source
    assert "const selectedKeywordSet = settings.selectedKeywordIds" not in source
    assert "selectSettings().selectedKeywordIds" in source
    assert "selectSettings().keywordCatalog" in source


def test_meal_plan_canonical_responses_reject_stale_revisions() -> None:
    """Verify meal-plan UI ignores canonical responses older than its revision."""
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "app/static/meal_plans.js").read_text(encoding="utf-8")

    assert "acceptsRevision," in source
    assert "if (!acceptsRevision(payload.revision)) {\n      return null;\n    }" in source
    assert 'setPendingProjections(payload.pending_projections, "meal-plan-mutation")' in source
    assert "const requestId = ++latestPlanOpenRequest;" in source
    assert "if (requestId !== latestPlanOpenRequest) {\n      return;\n    }" in source


def test_sync_keeps_rejections_separate_from_server_pending_projections() -> None:
    """Verify rejected shopping mutations remain distinct from server projections."""
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "app/static/js/sync.js").read_text(encoding="utf-8")

    assert 'payload.projection.status === "pending"' in source
    assert 'setPendingProjections([payload.projection], "sync")' in source
    assert 'status: "rejected"' not in source

    editor_source = (repo_root / "app/static/shop_editor.js").read_text(encoding="utf-8")
    assert "selectShoppingRejectedChanges" in editor_source
    assert "Sync rejected. Edit to retry." in editor_source


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for performance metrics tests")
def test_phase_six_performance_metrics_contract() -> None:
    """Verify frontend performance metrics retain bounded diagnostic behavior."""
    repo_root = Path(__file__).resolve().parents[1]
    metrics_path = (repo_root / "app/static/js/performance_metrics.js").as_uri()
    script = f"""
  globalThis.window = {{ WFD_PERFORMANCE_METRICS_ENABLED: true, dispatchEvent() {{}} }};
  globalThis.CustomEvent = class CustomEvent {{ constructor(name, init) {{ this.type = name; this.detail = init.detail; }} }};
  const metricsModule = await import({metrics_path!r});
  window.WFD_recordApiMetric({{ operation: 'health', durationMs: 3, responseSize: 12 }});
  window.WFD_recordRenderMetric({{ screen: 'shopping', renderCount: 1 }});
  window.WFD_recordSyncMetric({{ operation: 'refresh', durationMs: 4 }});
  const metrics = window.WFD_getPerformanceMetrics();
  if (metrics.length !== 3 || metrics[0].kind !== 'api' || metrics[1].kind !== 'render' ||
    metrics[2].kind !== 'sync' || metrics[0].responseSize !== 12) {{
    throw new Error('performance metric collection contract failed');
  }}
  window.WFD_clearPerformanceMetrics();
  if (window.WFD_getPerformanceMetrics().length !== 0) throw new Error('metric clearing failed');
  """
    run = subprocess.run(
      ["node", "--input-type=module", "-e", script],
      cwd=repo_root,
      capture_output=True,
      text=True,
      check=False,
    )
    assert run.returncode == 0, (
      "Node performance metrics contract failed\n"
      f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_named_commands_reach_domain_gateway() -> None:
    """Verify named commands delegate to the correct domain gateway methods."""
    repo_root = Path(__file__).resolve().parents[1]
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    script = f"""
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};
const requestedPaths = [];
globalThis.fetch = async (path) => {{
  requestedPaths.push(path);
  return {{
    ok: true,
    status: 200,
    headers: {{ get() {{ return null; }} }},
    async json() {{ return {{ data: [] }}; }},
  }};
}};
const commands = await import({commands_path!r});
await commands.mealPlanCommands.list();
await commands.settingsCommands.user();
if (requestedPaths.join(',') !== '/api/v1/meal-plans/stored,/api/v1/config/user-settings') {{
  throw new Error(`Named command gateway contract failed: ${{requestedPaths.join(',')}}`);
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
        "Node named command gateway contract failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_phase_one_store_notifications_revisions_and_settings_contract() -> None:
    """Verify store notifications carry domain, source, status, and revision."""
    repo_root = Path(__file__).resolve().parents[1]
    index_path = (repo_root / "app/static/js/store/index.js").as_uri()
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    selectors_path = (repo_root / "app/static/js/store/selectors.js").as_uri()

    script = f"""
class LocalStorageMock {{
  constructor() {{ this.map = new Map(); }}
  getItem(key) {{ return this.map.has(key) ? this.map.get(key) : null; }}
  setItem(key, value) {{ this.map.set(key, String(value)); }}
  removeItem(key) {{ this.map.delete(key); }}
}}

globalThis.localStorage = new LocalStorageMock();
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};

const index = await import({index_path!r});
const commands = await import({commands_path!r});
const selectors = await import({selectors_path!r});
const notifications = [];
const unsubscribe = index.subscribe((event) => notifications.push(event));

index.store.shopping.itemsById = {{ '7': {{ id: 7, amount: 1 }} }};
index.store.shopping.pendingChanges = [];
commands.updateShoppingChange(7, {{ amount: 2 }});
if (notifications.length !== 1 || notifications[0].domain !== 'shopping' || notifications[0].status !== 'optimistic') {{
  throw new Error('Optimistic shopping notification contract failed');
}}

commands.setRevision(4, 'server');
if (selectors.selectSyncState().revision !== 4 || notifications[1].revision !== 4) {{
  throw new Error('Revision notification contract failed');
}}

commands.setPendingProjections([{{ operation_id: 'op-1', status: 'pending' }}]);
if (selectors.selectPendingProjections().length !== 1 || selectors.selectPendingProjections()[0].status !== 'pending') {{
  throw new Error('Pending projection selector contract failed');
}}
index.store.sync.pendingProjections = [];
commands.loadShoppingCacheCommand();
if (selectors.selectPendingProjections()[0].operation_id !== 'op-1') {{
  throw new Error('Pending projections did not survive cache reload');
}}

commands.setSettingsSlice({{ user: {{ default_diners: 4 }} }});
if (selectors.selectSettings().user.default_diners !== 4 || notifications[3].domain !== 'settings') {{
  throw new Error('Settings store contract failed');
}}
unsubscribe();
"""

    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0, (
        "Node Phase 1 contract test failed\n"
        f"STDOUT:\n{{run.stdout}}\nSTDERR:\n{{run.stderr}}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_phase_one_metadata_rejected_state_and_online_write_contract() -> None:
    """Verify metadata, rejected rows, and online-only write policy coexist."""
    repo_root = Path(__file__).resolve().parents[1]
    index_path = (repo_root / "app/static/js/store/index.js").as_uri()
    commands_path = (repo_root / "app/static/js/store/commands.js").as_uri()
    selectors_path = (repo_root / "app/static/js/store/selectors.js").as_uri()

    script = f"""
globalThis.localStorage = {{
  getItem() {{ return null; }},
  setItem() {{}},
  removeItem() {{}},
}};
globalThis.window = {{ WFD_API_PREFIX: '/api/v1' }};
Object.defineProperty(globalThis, 'navigator', {{ value: {{ onLine: true }}, writable: true }});

const index = await import({index_path!r});
const commands = await import({commands_path!r});
const selectors = await import({selectors_path!r});

index.store.shopping.itemsById = {{ '8': {{ id: 8, amount: 1 }} }};
index.store.shopping.pendingChanges = [];
index.store.shopping.rejectedChanges = [];
commands.updateShoppingChange(8, {{ amount: 3 }});
if (selectors.selectDomainMeta('shopping').status !== 'optimistic') {{
  throw new Error('Optimistic metadata was not recorded');
}}

index.store.shopping.rejectedChanges = [{{ operation: 'update', entry_id: 8, payload: {{ amount: 3 }}, error: {{ reason: 'locked' }} }}];
if (selectors.selectShoppingRejectedChanges()[0].payload.amount !== 3) {{
  throw new Error('Rejected attempted value was not retained');
}}

commands.setRevision(9, 'server');
if (commands.acceptsRevision(8) || !commands.acceptsRevision(9)) {{
  throw new Error('Stale revision acceptance contract failed');
}}

globalThis.navigator.onLine = false;
let blocked = false;
try {{ commands.assertOnlineMutation('settings'); }} catch (error) {{ blocked = String(error).includes('offline'); }}
if (!blocked) {{
  throw new Error('Offline settings mutation was not blocked');
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
        "Node Phase 1 metadata contract test failed\n"
        f"STDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
    )
