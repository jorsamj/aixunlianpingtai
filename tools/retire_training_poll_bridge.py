from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


# 1) app.js: both historical setupPagePolling generations become explicit lifecycle handoffs only.
path = 'static/app.js'
text = read(path)
text = replace_once(text, 'state.jobPollTimer = state.jobPollTimer || null;\n', '', 'remove legacy job timer state initialization')

first_start = text.find('function setupPagePolling(){')
first_end = text.find('\nrender=function(){', first_start)
if first_start < 0 or first_end < 0:
    raise SystemExit('first setupPagePolling declaration not found')
if text.count('function setupPagePolling(){') != 1:
    raise SystemExit(f'expected one setupPagePolling declaration, found {text.count("function setupPagePolling(){")}')
text = text[:first_start] + "function setupPagePolling(){window.PollRegistryRuntime?.replaceTrainingJobTimer?.();}" + text[first_end:]

second_start = text.find('  setupPagePolling=function(){')
second_end = text.find('\n\n  render=function(){', second_start)
if second_start < 0 or second_end < 0:
    raise SystemExit('final setupPagePolling assignment not found')
if text.count('  setupPagePolling=function(){') != 1:
    raise SystemExit(f'expected one setupPagePolling assignment, found {text.count("  setupPagePolling=function(){")}')
text = text[:second_start] + "  setupPagePolling=function(){window.PollRegistryRuntime?.replaceTrainingJobTimer?.();};" + text[second_end:]

if 'jobPollTimer' in text:
    raise SystemExit('static/app.js: jobPollTimer remains after migration')
if text.count('window.PollRegistryRuntime?.replaceTrainingJobTimer?.()') != 2:
    raise SystemExit('static/app.js: expected two historical setupPagePolling handoff definitions')
write(path, text)


# 2) PollRegistry: direct training-jobs ownership; no setupPagePolling wrapper or state timer compatibility.
path = 'static/modules/poll-registry.js'
text = read(path)
text = replace_once(
    text,
    """  let originalSetupPagePolling = null;\n  let wrappedSetupPagePolling = null;\n""",
    '',
    'remove setupPagePolling wrapper state',
)
text = replace_once(
    text,
    """  function adoptLegacy() {\n    const s = state();\n    registry.adopt('training-jobs', trainingOwners, s.jobPollTimer);\n    return registry.snapshot();\n  }\n\n""",
    '',
    'remove final legacy timer adoption',
)
text = replace_once(text, "    if (!trainingOwners.includes(page)) s.jobPollTimer = null;\n", '', 'remove job timer legacy ref clearing')
old_replace = """  function replaceTrainingJobTimer() {\n    const s = state();\n    if (s.jobPollTimer != null) {\n      try { clearInterval(s.jobPollTimer); } catch (_) {}\n      s.jobPollTimer = null;\n    }\n    registry.clear('training-jobs');\n    if (!trainingOwners.includes(String(s.page || ''))) return null;\n\n    const callback = async () => {\n      const current = state();\n      if (!trainingOwners.includes(String(current.page || ''))) return;\n      if (!current.project?.id) return;\n      if (typeof window.TrainingTaskRuntime?.refresh === 'function') {\n        await window.TrainingTaskRuntime.refresh({render: true, source: 'poll'});\n      } else if (typeof window.refreshJobsOnly === 'function') {\n        await window.refreshJobsOnly();\n      }\n    };\n    s.jobPollTimer = registry.startInterval(\n      'training-jobs',\n      trainingOwners,\n      callback,\n      trainingPollDelay(s),\n    );\n    return s.jobPollTimer;\n  }\n"""
new_replace = """  function replaceTrainingJobTimer() {\n    const s = state();\n    registry.clear('training-jobs');\n    if (!trainingOwners.includes(String(s.page || ''))) return null;\n\n    const callback = async () => {\n      const current = state();\n      if (!trainingOwners.includes(String(current.page || ''))) return;\n      if (!current.project?.id) return;\n      if (typeof window.TrainingTaskRuntime?.refresh === 'function') {\n        await window.TrainingTaskRuntime.refresh({render: true, source: 'poll'});\n      } else if (typeof window.refreshJobsOnly === 'function') {\n        await window.refreshJobsOnly();\n      }\n    };\n    return registry.startInterval(\n      'training-jobs',\n      trainingOwners,\n      callback,\n      trainingPollDelay(s),\n    );\n  }\n"""
text = replace_once(text, old_replace, new_replace, 'make training timer registry-owned only')

start = text.find('  function installPollingCreationBridge() {')
end = text.find('  function rebindCreation() {', start)
if start < 0 or end < 0:
    raise SystemExit('training polling creation bridge block not found')
if text.count('  function installPollingCreationBridge() {') != 1:
    raise SystemExit('expected exactly one training polling creation bridge')
text = text[:start] + text[end:]
text = replace_once(
    text,
    """  function rebindCreation() {\n    return installPollingCreationBridge();\n  }\n\n""",
    '',
    'remove final creation rebind helper',
)
text = replace_once(text, '    adoptLegacy,\n', '', 'remove adoptLegacy runtime API')
text = replace_once(text, '    rebindCreation,\n', '', 'remove rebindCreation runtime API')
text = replace_once(
    text,
    """    beforeNavigate(nextPage) {\n      adoptLegacy();\n      registry.leave(nextPage);\n      clearLegacyReferences(nextPage);\n    },\n    afterNavigate() {\n      adoptLegacy();\n    },\n""",
    """    beforeNavigate(nextPage) {\n      registry.leave(nextPage);\n      clearLegacyReferences(nextPage);\n    },\n""",
    'remove legacy adoption from navigation lifecycle',
)
text = replace_once(
    text,
    """      if (wrappedSetupPagePolling && window.setupPagePolling === wrappedSetupPagePolling) {\n        window.setupPagePolling = originalSetupPagePolling;\n      }\n""",
    '',
    'remove setupPagePolling wrapper restoration',
)
text = replace_once(text, '      s.jobPollTimer = null;\n', '', 'remove job timer state cleanup from destroy')
text = replace_once(
    text,
    """  adoptLegacy();\n  rebindCreation();\n  replaceVideo424Timer();\n  replaceSourceTimer();\n  return runtime;\n""",
    """  replaceTrainingJobTimer();\n  replaceVideo424Timer();\n  replaceSourceTimer();\n  return runtime;\n""",
    'initialize all direct PollRegistry owners',
)
for token in (
    'jobPollTimer',
    'installPollingCreationBridge',
    '__pollRegistryCreationWrapped',
    'originalSetupPagePolling',
    'wrappedSetupPagePolling',
    "registry.adopt('training-jobs'",
    'adoptLegacy',
    'rebindCreation',
):
    if token in text:
        raise SystemExit(f'static/modules/poll-registry.js: training compatibility remains: {token}')
write(path, text)


# 3) NavigationStability: no legacy polling timer fallback remains at all.
path = 'static/modules/navigation-stability.js'
text = read(path)
clear_start = text.find('function clearTimer(value, clearFn = clearInterval) {')
owners_start = text.find('const OWNER_FUNCTIONS = {', clear_start)
if clear_start < 0 or owners_start < 0:
    raise SystemExit('navigation legacy timer helper block not found')
legacy_block = text[clear_start:owners_start]
if 'jobPollTimer' not in legacy_block or 'clearPageTimers' not in legacy_block:
    raise SystemExit('navigation legacy block did not contain expected job timer fallback')
text = text[:clear_start] + text[owners_start:]
text = replace_once(
    text,
    """      if (pollRegistry?.beforeNavigate) pollRegistry.beforeNavigate(requested);\n      else clearPageTimers(s, requested);\n""",
    "      pollRegistry?.beforeNavigate?.(requested);\n",
    'remove navigation legacy timer fallback call',
)
if 'jobPollTimer' in text or 'clearPageTimers' in text or 'function clearTimer' in text:
    raise SystemExit('static/modules/navigation-stability.js: legacy timer fallback remains')
write(path, text)


# 4) PollRegistry unit tests: direct training owner only; no legacy job state fixture.
path = 'tests/frontend/poll-registry.test.mjs'
text = read(path)
legacy_start = text.find("test('remaining legacy training timer is adopted and cleared when navigating away', () => {")
training_start = text.find("test('final training polling creation is replaced by a PollRegistry-managed interval', async () => {")
video_start = text.find("test('video polling is a direct PollRegistry-managed one-shot", training_start)
if legacy_start < 0 or training_start < 0 or video_start < 0:
    raise SystemExit('expected legacy/training/video unit-test boundaries not found')
new_training = """test('training polling is a direct PollRegistry-managed interval and stops on leave', async () => {\n  const state = {\n    page: '训练任务',\n    project: {id: 'p1'},\n    jobs: [{id: 'j1', status: 'running'}],\n  };\n  const callbacks = new Map();\n  const cleared = [];\n  let nextTimer = 100;\n  let refreshes = 0;\n  const originalSetInterval = globalThis.setInterval;\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.setInterval = (callback, delay) => {\n    const id = ++nextTimer;\n    callbacks.set(id, {callback, delay});\n    return id;\n  };\n  globalThis.clearInterval = id => {\n    cleared.push(id);\n    callbacks.delete(id);\n  };\n  globalThis.window = {\n    TrainingTaskRuntime: {refresh: async ({source}) => {\n      assert.equal(source, 'poll');\n      refreshes += 1;\n    }},\n  };\n\n  const runtime = installPollRegistry({getState: () => state});\n  const managed = runtime.snapshot().find(row => row.key === 'training-jobs');\n  assert.deepEqual(managed, {\n    key: 'training-jobs', owners: ['训练任务', '检测台'], active: true, managed: true, delay: 2000,\n  });\n  const timerId = [...callbacks.keys()][0];\n  assert.equal(callbacks.get(timerId)?.delay, 2000);\n\n  await callbacks.get(timerId).callback();\n  assert.equal(refreshes, 1);\n\n  runtime.beforeNavigate('数据集');\n  assert.equal(callbacks.has(timerId), false);\n  assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);\n\n  runtime.destroy();\n  globalThis.setInterval = originalSetInterval;\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n\n"""
text = text[:legacy_start] + new_training + text[video_start:]
# Remaining direct video/source fixtures must not carry job timer compatibility fields.
count = text.count('    jobPollTimer: null,\n')
if count != 2:
    raise SystemExit(f'poll-registry tests: expected 2 remaining jobPollTimer null fixtures, found {count}')
text = text.replace('    jobPollTimer: null,\n', '')
write(path, text)


# 5) Navigation unit test: prove no hidden clearInterval fallback remains without PollRegistry.
path = 'tests/frontend/navigation-stability.test.mjs'
text = read(path)
old = """test('navigation fallback clears remaining training polling timer when PollRegistry is absent', () => {\n  const state = {page: '训练任务', jobPollTimer: 101};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(cleared, [101]);\n  assert.equal(state.jobPollTimer, null);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n"""
new = """test('navigation without PollRegistry has no legacy timer fallback side effects', () => {\n  const state = {page: '训练任务'};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(cleared, []);\n  assert.equal(state.page, '算法列表');\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n"""
text = replace_once(text, old, new, 'replace navigation legacy timer fallback test')
write(path, text)

for product in ('static/app.js', 'static/modules/poll-registry.js', 'static/modules/navigation-stability.js'):
    if 'jobPollTimer' in read(product):
        raise SystemExit(f'{product}: jobPollTimer remains in product runtime')

print('retired training polling wrapper bridge and job timer compatibility')
