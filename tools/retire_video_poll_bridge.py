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


# 1) app.js: video renderer/refresh explicitly hands lifecycle to PollRegistry.
path = 'static/app.js'
text = read(path)
text = replace_once(
    text,
    "window.refreshVideo424Delta=async function(){await loadVideo424();patchVideoRows424();clearTimeout(state.video424Timer);if(state.page==='视频切帧'&&state.video424.some(t=>videoCore424()?.isActiveVideoTask(t)))state.video424Timer=setTimeout(refreshVideo424Delta,2000)};",
    "window.refreshVideo424Delta=async function(){await loadVideo424();patchVideoRows424();window.PollRegistryRuntime?.replaceVideo424Timer?.()};",
    'make video delta refresh hand off polling explicitly',
)
text = replace_once(
    text,
    "window.renderVideo424=async function(){clearTimeout(state.video424Timer);await loadVideo424();",
    "window.renderVideo424=async function(){await loadVideo424();",
    'remove local video timer clear from renderer',
)
text = replace_once(
    text,
    ";if(state.video424.some(t=>videoCore424()?.isActiveVideoTask(t)))state.video424Timer=setTimeout(refreshVideo424Delta,2000)};",
    ";window.PollRegistryRuntime?.replaceVideo424Timer?.()};",
    'replace local video timer creation with explicit managed handoff',
)
if text.count('window.PollRegistryRuntime?.replaceVideo424Timer?.()') != 2:
    raise SystemExit('app.js: expected exactly two explicit video polling handoffs')
for token in ('setTimeout(refreshVideo424Delta,2000)', 'clearTimeout(state.video424Timer)'):
    if token in text:
        raise SystemExit(f'app.js: legacy video timer lifecycle remains: {token}')
write(path, text)


# 2) PollRegistry: remove render/refresh wrapper bridge; keep direct managed owner.
path = 'static/modules/poll-registry.js'
text = read(path)
text = replace_once(
    text,
    """  let originalRenderVideo424 = null;\n  let wrappedRenderVideo424 = null;\n  let originalRefreshVideo424 = null;\n  let wrappedRefreshVideo424 = null;\n""",
    '',
    'remove video wrapper state',
)
text = replace_once(
    text,
    "    registry.adopt('video-frames', videoOwner, s.video424Timer, clearTimeout);\n",
    '',
    'stop adopting video timer as legacy state',
)
start = text.find('  function installVideo424CreationBridge() {')
end = text.find('  function installSourceCreationBridge() {', start)
if start < 0 or end < 0:
    raise SystemExit('video creation bridge block not found')
if text.count('  function installVideo424CreationBridge() {') != 1:
    raise SystemExit('expected exactly one video creation bridge')
text = text[:start] + text[end:]
text = replace_once(
    text,
    """  function rebindCreation() {\n    const page = installPollingCreationBridge();\n    const video = installVideo424CreationBridge();\n    const source = installSourceCreationBridge();\n    return page || video || source;\n  }\n""",
    """  function rebindCreation() {\n    const page = installPollingCreationBridge();\n    const source = installSourceCreationBridge();\n    return page || source;\n  }\n""",
    'remove video from compatibility rebind',
)
text = replace_once(
    text,
    """      if (wrappedRenderVideo424 && window.renderVideo424 === wrappedRenderVideo424) {\n        window.renderVideo424 = originalRenderVideo424;\n      }\n      if (wrappedRefreshVideo424 && window.refreshVideo424Delta === wrappedRefreshVideo424) {\n        window.refreshVideo424Delta = originalRefreshVideo424;\n      }\n""",
    '',
    'remove video wrapper restoration',
)
text = replace_once(
    text,
    """  adoptLegacy();\n  rebindCreation();\n  return runtime;\n}\n""",
    """  adoptLegacy();\n  rebindCreation();\n  replaceVideo424Timer();\n  return runtime;\n}\n""",
    'initialize explicit managed video owner on install',
)
for token in (
    'installVideo424CreationBridge',
    '__pollRegistryVideoWrapped',
    'originalRenderVideo424',
    'wrappedRenderVideo424',
    'originalRefreshVideo424',
    'wrappedRefreshVideo424',
):
    if token in text:
        raise SystemExit(f'poll-registry.js: video wrapper compatibility remains: {token}')
write(path, text)


# 3) Unit contract: managed video owner is direct; renderer wrapping is not part of the test anymore.
path = 'tests/frontend/poll-registry.test.mjs'
text = read(path)
start_marker = "test('final v42.4 video polling uses a managed one-shot and re-arms only while a task is active', async () => {"
end_marker = "test('source page polling creation is replaced by a PollRegistry-managed interval after first render', async () => {"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('video polling unit-test block not found')
new_test = """test('video polling is a direct PollRegistry-managed one-shot and re-arms only while a task is active', async () => {\n  const state = {\n    page: '视频切帧',\n    project: {id: 'p1'},\n    jobs: [],\n    jobPollTimer: null,\n    source422Timer: null,\n    video424: [{id: 'v1', status: 'RUNNING'}],\n    video424Timer: null,\n  };\n  const timeouts = new Map();\n  const clearedTimeouts = [];\n  let nextTimer = 200;\n  let refreshes = 0;\n  const originalSetTimeout = globalThis.setTimeout;\n  const originalClearTimeout = globalThis.clearTimeout;\n  globalThis.setTimeout = (callback, delay) => {\n    const id = ++nextTimer;\n    timeouts.set(id, {callback, delay});\n    return id;\n  };\n  globalThis.clearTimeout = id => {\n    clearedTimeouts.push(id);\n    timeouts.delete(id);\n  };\n\n  let runtime;\n  globalThis.window = {\n    PlatformCore: {video: {isActiveVideoTask: task => String(task?.status).toUpperCase() === 'RUNNING'}},\n    refreshVideo424Delta: async () => {\n      refreshes += 1;\n      runtime.replaceVideo424Timer();\n    },\n  };\n\n  runtime = installPollRegistry({getState: () => state});\n\n  const firstManaged = state.video424Timer;\n  assert.equal(timeouts.get(firstManaged)?.delay, 2000);\n  assert.deepEqual(runtime.snapshot().find(row => row.key === 'video-frames'), {\n    key: 'video-frames', owners: ['视频切帧'], active: true, managed: true, delay: 2000,\n  });\n\n  await timeouts.get(firstManaged).callback();\n  assert.equal(refreshes, 1);\n  const secondManaged = state.video424Timer;\n  assert.notEqual(secondManaged, firstManaged);\n  assert.equal(timeouts.get(secondManaged)?.delay, 2000);\n  assert.equal(runtime.snapshot().find(row => row.key === 'video-frames')?.managed, true);\n\n  state.video424 = [{id: 'v1', status: 'SUCCEEDED'}];\n  await timeouts.get(secondManaged).callback();\n  assert.equal(refreshes, 2);\n  assert.equal(state.video424Timer, null);\n  assert.equal(runtime.snapshot().some(row => row.key === 'video-frames'), false);\n\n  runtime.beforeNavigate('数据集');\n  assert.equal(state.video424Timer, null);\n\n  runtime.destroy();\n  globalThis.setTimeout = originalSetTimeout;\n  globalThis.clearTimeout = originalClearTimeout;\n  delete globalThis.window;\n});\n\n"""
text = text[:start] + new_test + text[end:]
write(path, text)

print('retired PollRegistry video render/refresh creation bridge')
