from pathlib import Path

# Trigger marker: guarded migration for the active frontend-runtime-stabilization branch.


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


runtime = "static/modules/training-task-runtime.js"
replace_once(
    runtime,
    "const DONE_STATUSES = new Set(['done', 'finished', 'completed', 'failed', 'stopped', 'cancelled', 'canceled']);",
    "const DONE_STATUSES = new Set(['done', 'finished', 'completed', 'failed', 'stopped', 'cancelled', 'canceled']);\nconst REFRESH_DEDUP_WINDOW_MS = 120;",
)
replace_once(
    runtime,
    "  let destroyed = false;\n  let lastRefreshAt = 0;",
    "  let destroyed = false;\n  let lastRefreshAt = 0;\n  let lastRefreshSource = '';",
)
replace_once(
    runtime,
    "  async function refresh({render = true} = {}) {",
    "  async function refresh({render = true, force = false, source = 'direct'} = {}) {",
)
replace_once(
    runtime,
    "    const startPage = String(state().page || '');\n    const startEpoch = Number(state().__navigationEpoch || 0);\n    const encoded = encodeURIComponent(pid);",
    "    const startPage = String(state().page || '');\n    const startEpoch = Number(state().__navigationEpoch || 0);\n    const age = Date.now() - lastRefreshAt;\n    const crossSourceDuplicate = (source === 'manual' && lastRefreshSource === 'poll')\n      || (source === 'poll' && lastRefreshSource === 'manual');\n    if (!force\n        && startPage === TRAINING_PAGE\n        && lastRefreshAt > 0\n        && age >= 0\n        && age <= REFRESH_DEDUP_WINDOW_MS\n        && crossSourceDuplicate) {\n      if (render) patchFinalTrainingTable();\n      return {stale: false, jobs: state().jobs || [], reused: true};\n    }\n    const encoded = encodeURIComponent(pid);",
)
replace_once(
    runtime,
    "      state().jobs = jobs;\n      lastRefreshAt = Date.now();\n      if (render) patchFinalTrainingTable();",
    "      state().jobs = jobs;\n      lastRefreshAt = Date.now();\n      lastRefreshSource = String(source || 'direct');\n      if (render) patchFinalTrainingTable();",
)
replace_once(
    runtime,
    "    return refresh({render: true});\n  }\n\n  async function mutate",
    "    return refresh({render: true, force: true, source: 'mutation'});\n  }\n\n  async function mutate",
)
replace_once(
    runtime,
    "  const focusedRefresh = () => refresh({render: true});",
    "  const focusedRefresh = () => refresh({render: true, source: 'poll'});",
)
replace_once(
    runtime,
    "    void refresh({render: true}).then(",
    "    void refresh({render: true, source: 'manual'}).then(",
)
replace_once(
    runtime,
    "    ).finally(() => {\n      if (button?.isConnected !== false) button.disabled = false;\n    });",
    "    ).finally(() => {\n      if (button?.isConnected !== false) button.disabled = false;\n      window.PollRegistryRuntime?.replaceTrainingJobTimer?.();\n    });",
)
replace_once(
    runtime,
    "    build: 'training-task-runtime-422502',",
    "    build: 'training-task-runtime-422503',",
)
replace_once(
    runtime,
    "      return {inflight: Boolean(inflight), lastRefreshAt, mutations: mutationLocks.size};",
    "      return {inflight: Boolean(inflight), lastRefreshAt, lastRefreshSource, mutations: mutationLocks.size};",
)

poll = "static/modules/poll-registry.js"
replace_once(
    poll,
    "      if (typeof window.refreshJobsOnly === 'function') await window.refreshJobsOnly();",
    "      if (typeof window.TrainingTaskRuntime?.refresh === 'function') {\n        await window.TrainingTaskRuntime.refresh({render: true, source: 'poll'});\n      } else if (typeof window.refreshJobsOnly === 'function') {\n        await window.refreshJobsOnly();\n      }",
)

main = "static/main.mjs"
replace_once(main, "./modules/poll-registry.js?v=422506", "./modules/poll-registry.js?v=422507")
replace_once(main, "./modules/training-task-runtime.js?v=422502", "./modules/training-task-runtime.js?v=422503")

index = "static/index.html"
replace_once(index, "/static/main.mjs?v=42.25.33", "/static/main.mjs?v=42.25.34")

browser = "tests/browser/training-task-performance.spec.mjs"
replace_once(
    browser,
    "  });\n\n  const apiRequests = [];",
    "  });\n  // Drain callbacks that were already queued before the managed poll was cleared.\n  // The assertions below still require exactly one jobs GET for each manual refresh.\n  await page.waitForTimeout(160);\n\n  const apiRequests = [];",
)

selector = "tests/browser/training-label-selector.spec.mjs"
replace_once(selector, "training-task-runtime-422502", "training-task-runtime-422503") if "training-task-runtime-422502" in Path(selector).read_text(encoding="utf-8") else None

unit = "tests/frontend/training-task-runtime.test.mjs"
unit_text = Path(unit).read_text(encoding="utf-8")
anchor = "test('training refresh discards response after navigation and always releases inflight lock', async () => {"
if unit_text.count(anchor) != 1:
    raise SystemExit("training task unit-test anchor mismatch")
new_tests = r'''test('manual refresh reuses a poll result that completed in the same interaction window', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [], __navigationEpoch: 1};
  let requests = 0;
  const originalNow = Date.now;
  let now = 1_000;
  Date.now = () => now;
  globalThis.window = {
    async fetch() { requests += 1; return response([{id: 'j1', status: 'running'}]); },
    updateTrainingJobTable() {},
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({source: 'poll'});
  now += 60;
  const result = await runtime.refresh({source: 'manual'});

  assert.equal(requests, 1);
  assert.equal(result.reused, true);
  assert.equal(runtime.state().lastRefreshSource, 'poll');

  runtime.destroy();
  Date.now = originalNow;
  cleanup();
});

test('task mutation forces a fresh jobs request even after a very recent poll', async () => {
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}], __navigationEpoch: 1};
  const calls = [];
  const originalNow = Date.now;
  let now = 2_000;
  Date.now = () => now;
  globalThis.window = {
    async fetch(url, init = {}) {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (url.endsWith('/pause')) return response({ok: true});
      if (url.endsWith('/jobs')) return response([{id: 'j1', status: calls.some(row => row.includes('/pause')) ? 'paused' : 'running'}]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };

  const runtime = installTrainingTaskRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({source: 'poll'});
  now += 20;
  await window.pauseTrain428('j1');

  assert.deepEqual(calls, [
    'GET /api/projects/p1/jobs',
    'POST /api/v48/projects/p1/jobs/j1/pause',
    'GET /api/projects/p1/jobs',
  ]);
  assert.equal(state.jobs[0].status, 'paused');

  runtime.destroy();
  Date.now = originalNow;
  cleanup();
});

'''
Path(unit).write_text(unit_text.replace(anchor, new_tests + anchor, 1), encoding="utf-8")

print("patched training task refresh coalescing and regression coverage")
