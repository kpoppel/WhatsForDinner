import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for frontend store smoke tests")
def test_store_commands_and_selectors_smoke() -> None:
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

let reportFlag = null;
globalThis.fetch = async () => ({{ ok: true, json: async () => ({{ source: 'ok' }}) }});
const okPayload = await commands.api('/health', null, (value) => {{ reportFlag = value; }});
if (!okPayload || okPayload.source !== 'ok' || reportFlag !== true) {{
  throw new Error('api success path smoke failed');
}}

globalThis.fetch = async () => ({{ ok: false, json: async () => ({{ detail: 'boom' }}) }});
reportFlag = null;
let failed = false;
try {{
  await commands.api('/health', null, (value) => {{ reportFlag = value; }});
}} catch (error) {{
  failed = String(error).includes('boom');
}}
if (!failed || reportFlag !== false) {{
  throw new Error('api error path smoke failed');
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
