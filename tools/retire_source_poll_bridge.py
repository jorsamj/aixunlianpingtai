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


# 1) app.js: source renderer explicitly hands polling to PollRegistry; no state timer owner.
path = 'static/app.js'
text = read(path)
text = replace_once(text, "  state.source422Timer=null;\n", '', 'remove source timer state initialization')
text = replace_once(
    text,
    "window.renderSources422=async function(){await loadSourcesOnly422();clearInterval(state.source422Timer);const s=",
    "window.renderSources422=async function(){await loadSourcesOnly422();const s=",
    'remove source timer clear from renderer',
)
text = replace_once(
    text,
    "renderSourceRows422();state.source422Timer=setInterval(()=>{if(state.page==='素材接入')refreshSources422();else clearInterval(state.source422Timer)},2500)};",
    "renderSourceRows422();window.PollRegistryRuntime?.replaceSourceTimer?.()};",
    'replace source local interval with explicit PollRegistry handoff',
)
text = replace_once(
    text,
    "window.setPage=function(p){clearInterval(state.source422Timer);if(p==='新建算法'||p==='自动迭代')p='算法列表';set422Base(p)};",
    "window.setPage=function(p){if(p==='新建算法'||p==='自动迭代')p='算法列表';set422Base(p)};",
    'remove source timer clear from v42.2 setPage wrapper',
)
if 'source422Timer' in text:
    raise SystemExit('static/app.js: source422Timer remains after migration')
if text.count('window.PollRegistryRuntime?.replaceSourceTimer?.()') != 1:
    raise SystemExit('static/app.js: expected exactly one explicit source PollRegistry handoff')
write(path, text)


# 2) PollRegistry: remove source renderer wrapper/adoption and keep direct managed interval only.
path = 'static/modules/poll-registry.js'
text = read(path)
text = replace_once(
    text,
    """  let originalRenderSources = null;\n  let wrappedRenderSources = null;\n""",
    '',
    'remove source wrapper state',
)
text = replace_once(
    text,
    "    registry.adopt('sources', sourceOwner, s.source422Timer);\n",
    '',
    'remove source legacy adoption',
)
text = replace_once(
    text,
    "    if (page !== sourceOwner) s.source422Timer = null;\n",
    '',
    'remove source legacy reference clearing',
)
old_replace = """  function replaceSourceTimer() {\n    const s = state();\n    if (s.source422Timer != null) {\n      try { clearInterval(s.source422Timer); } catch (_) {}\n      s.source422Timer = null;\n    }\n    registry.clear('sources');\n    if (String(s.page || '') !== sourceOwner) return null;\n\n    const callback = async () => {\n      const current = state();\n      if (String(current.page || '') !== sourceOwner) return;\n      if (!current.project?.id) return;\n      if (typeof window.refreshSources422 === 'function') await window.refreshSources422();\n    };\n    s.source422Timer = registry.startInterval(\n      'sources',\n      sourceOwner,\n      callback,\n      2500,\n    );\n    return s.source422Timer;\n  }\n"""
new_replace = """  function replaceSourceTimer() {\n    const s = state();\n    registry.clear('sources');\n    if (String(s.page || '') !== sourceOwner) return null;\n\n    const callback = async () => {\n      const current = state();\n      if (String(current.page || '') !== sourceOwner) return;\n      if (!current.project?.id) return;\n      if (typeof window.refreshSources422 === 'function') await window.refreshSources422();\n    };\n    return registry.startInterval(\n      'sources',\n      sourceOwner,\n      callback,\n      2500,\n    );\n  }\n"""
text = replace_once(text, old_replace, new_replace, 'make source timer registry-owned only')
start = text.find('  function installSourceCreationBridge() {')
end = text.find('  function rebindCreation() {', start)
if start < 0 or end < 0:
    raise SystemExit('source creation bridge block not found')
if text.count('  function installSourceCreationBridge() {') != 1:
    raise SystemExit('expected exactly one source creation bridge')
text = text[:start] + text[end:]
text = replace_once(
    text,
    """  function rebindCreation() {\n    const page = installPollingCreationBridge();\n    const source = installSourceCreationBridge();\n    return page || source;\n  }\n""",
    """  function rebindCreation() {\n    return installPollingCreationBridge();\n  }\n""",
    'remove source from compatibility rebind',
)
text = replace_once(
    text,
    """      if (wrappedRenderSources && window.renderSources422 === wrappedRenderSources) {\n        window.renderSources422 = originalRenderSources;\n      }\n""",
    '',
    'remove source wrapper restoration',
)
text = replace_once(text, "      s.source422Timer = null;\n", '', 'remove source timer state cleanup from destroy')
text = replace_once(
    text,
    """  rebindCreation();\n  replaceVideo424Timer();\n  return runtime;\n""",
    """  rebindCreation();\n  replaceVideo424Timer();\n  replaceSourceTimer();\n  return runtime;\n""",
    'initialize direct source owner on install',
)
for token in (
    'source422Timer',
    'installSourceCreationBridge',
    '__pollRegistrySourceWrapped',
    'originalRenderSources',
    'wrappedRenderSources',
    "registry.adopt('sources'",
):
    if token in text:
        raise SystemExit(f'static/modules/poll-registry.js: source compatibility remains: {token}')
write(path, text)


# 3) NavigationStability: source timer fallback is no longer needed.
path = 'static/modules/navigation-stability.js'
text = read(path)
text = replace_once(
    text,
    """  if (nextPage !== '素材接入') {\n    clearTimer(state.source422Timer);\n    state.source422Timer = null;\n  }\n""",
    '',
    'remove source timer fallback from navigation',
)
if 'source422Timer' in text:
    raise SystemExit('static/modules/navigation-stability.js: source422Timer remains')
write(path, text)


# 4) Focused unit tests: model source polling as a direct registry owner.
path = 'tests/frontend/poll-registry.test.mjs'
text = read(path)
old_legacy = """test('remaining legacy page timers are adopted and references are cleared when navigating away', () => {\n  const state = {\n    jobPollTimer: 1,\n    source422Timer: 2,\n  };\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = id => cleared.push(id);\n  globalThis.window = {};\n\n  const runtime = installPollRegistry({getState: () => state});\n  runtime.beforeNavigate('数据集');\n\n  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2]);\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n  assert.deepEqual(runtime.snapshot(), []);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n"""
new_legacy = """test('remaining legacy training timer is adopted and cleared when navigating away', () => {\n  const state = {\n    jobPollTimer: 1,\n  };\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = id => cleared.push(id);\n  globalThis.window = {};\n\n  const runtime = installPollRegistry({getState: () => state});\n  runtime.beforeNavigate('数据集');\n\n  assert.deepEqual(cleared, [1]);\n  assert.equal(state.jobPollTimer, null);\n  assert.deepEqual(runtime.snapshot(), []);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n"""
text = replace_once(text, old_legacy, new_legacy, 'update remaining legacy timer unit test')
# Remove now-obsolete source timer fields from other fixtures deterministically.
source_fixture_count = text.count('    source422Timer: null,\n')
if source_fixture_count != 3:
    raise SystemExit(f'poll-registry test: expected 3 source422Timer null fixtures, found {source_fixture_count}')
text = text.replace('    source422Timer: null,\n', '')
start_marker = "test('source page polling creation is replaced by a PollRegistry-managed interval after first render', async () => {"
start = text.find(start_marker)
if start < 0:
    raise SystemExit('source polling unit-test block not found')
# Source test is last test in file.
new_source_test = """test('source polling is a direct PollRegistry-managed interval and stops on leave', async () => {\n  const state = {\n    page: '素材接入',\n    project: {id: 'p1'},\n    jobs: [],\n    jobPollTimer: null,\n  };\n  const callbacks = new Map();\n  const cleared = [];\n  let nextTimer = 300;\n  let refreshes = 0;\n  const originalSetInterval = globalThis.setInterval;\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.setInterval = (callback, delay) => {\n    const id = ++nextTimer;\n    callbacks.set(id, {callback, delay});\n    return id;\n  };\n  globalThis.clearInterval = id => {\n    cleared.push(id);\n    callbacks.delete(id);\n  };\n  globalThis.window = {\n    refreshSources422: async () => { refreshes += 1; },\n  };\n\n  const runtime = installPollRegistry({getState: () => state});\n  const managed = runtime.snapshot().find(row => row.key === 'sources');\n\n  assert.deepEqual(managed, {\n    key: 'sources', owners: ['素材接入'], active: true, managed: true, delay: 2500,\n  });\n  const timerId = [...callbacks.keys()][0];\n  assert.equal(callbacks.get(timerId)?.delay, 2500);\n\n  await callbacks.get(timerId).callback();\n  assert.equal(refreshes, 1);\n\n  runtime.beforeNavigate('数据集');\n  assert.equal(callbacks.has(timerId), false);\n  assert.equal(runtime.snapshot().some(row => row.key === 'sources'), false);\n\n  runtime.destroy();\n  globalThis.setInterval = originalSetInterval;\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n"""
text = text[:start] + new_source_test
write(path, text)

path = 'tests/frontend/navigation-stability.test.mjs'
text = read(path)
old_nav = """test('navigation fallback clears remaining page-owned polling timers when PollRegistry is absent', () => {\n  const state = {page: '训练任务', jobPollTimer: 101, source422Timer: 202};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(new Set(cleared), new Set([101, 202]));\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n"""
new_nav = """test('navigation fallback clears remaining training polling timer when PollRegistry is absent', () => {\n  const state = {page: '训练任务', jobPollTimer: 101};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(cleared, [101]);\n  assert.equal(state.jobPollTimer, null);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n"""
text = replace_once(text, old_nav, new_nav, 'update navigation fallback timer unit test')
write(path, text)

for product in ('static/app.js', 'static/modules/poll-registry.js', 'static/modules/navigation-stability.js'):
    if 'source422Timer' in read(product):
        raise SystemExit(f'{product}: source422Timer remains in product runtime')

print('retired source polling wrapper bridge and state timer compatibility')
