from pathlib import Path


def read(path):
    return Path(path).read_text(encoding='utf-8')


def write(path, text):
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)

# 1) app.js: retire the v33 wrapper whose only job was legacy video/prelabel interval ownership.
path = 'static/app.js'
text = read(path)
old = """  const _oldSetupPollV33 = typeof setupPagePolling==='function' ? setupPagePolling : function(){};\n  setupPagePolling=function(){\n    _oldSetupPollV33();\n    clearInterval(window.__videoFramePollTimer);\n    clearInterval(window.__prelabelPollTimer);\n    if(state.page==='视频切帧'){\n      window.__videoFramePollTimer=setInterval(()=>refreshVideoTasksOnly(),2500);\n    }\n  };\n\n"""
text = replace_once(text, old, '', 'retire v33 setupPagePolling wrapper')
write(path, text)

# 2) PollRegistry: stop adopting/clearing timer names that product code no longer creates.
path = 'static/modules/poll-registry.js'
text = read(path)
text = replace_once(text, """  function retireLegacyVideoInterval() {\n    if (window.__videoFramePollTimer != null) {\n      try { clearInterval(window.__videoFramePollTimer); } catch (_) {}\n      window.__videoFramePollTimer = null;\n    }\n  }\n\n""", '', 'remove legacy video interval helper')
text = replace_once(text, """    registry.adopt('auto-label', ['自动标注', '自动标注及清洗'], s.auto422Timer);\n    registry.adopt('video-frames', videoOwner, s.video424Timer, clearTimeout);\n    registry.adopt('prelabel', ['自动标注', '自动标注及清洗'], window.__prelabelPollTimer);\n""", """    registry.adopt('video-frames', videoOwner, s.video424Timer, clearTimeout);\n""", 'remove retired legacy adoptions')
text = replace_once(text, """    if (!['自动标注', '自动标注及清洗'].includes(page)) s.auto422Timer = null;\n    if (page !== videoOwner) {\n      if (s.video424Timer != null) {\n        try { clearTimeout(s.video424Timer); } catch (_) {}\n      }\n      s.video424Timer = null;\n      retireLegacyVideoInterval();\n    }\n    if (!['自动标注', '自动标注及清洗'].includes(page)) window.__prelabelPollTimer = null;\n""", """    if (page !== videoOwner) {\n      if (s.video424Timer != null) {\n        try { clearTimeout(s.video424Timer); } catch (_) {}\n      }\n      s.video424Timer = null;\n    }\n""", 'remove retired legacy clear references')
text = replace_once(text, """    registry.clear('video-frames');\n    retireLegacyVideoInterval();\n    if (String(s.page || '') !== videoOwner) return null;\n""", """    registry.clear('video-frames');\n    if (String(s.page || '') !== videoOwner) return null;\n""", 'remove legacy video retirement from managed video owner')
text = replace_once(text, """      replaceTrainingJobTimer();\n      retireLegacyVideoInterval();\n      adoptLegacy();\n""", """      replaceTrainingJobTimer();\n      adoptLegacy();\n""", 'remove legacy video retirement from setup bridge callback')
text = replace_once(text, """    replaceTrainingJobTimer();\n    retireLegacyVideoInterval();\n    adoptLegacy();\n""", """    replaceTrainingJobTimer();\n    adoptLegacy();\n""", 'remove legacy video retirement from setup bridge install')
text = replace_once(text, """      s.video424Timer = null;\n      retireLegacyVideoInterval();\n      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;\n""", """      s.video424Timer = null;\n      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;\n""", 'remove legacy video retirement from destroy')
write(path, text)

# 3) Navigation fallback: only current legacy job/source refs remain; PollRegistry handles managed owners.
path = 'static/modules/navigation-stability.js'
text = read(path)
text = replace_once(text, """  if (!['自动标注', '自动标注及清洗'].includes(nextPage)) {\n    clearTimer(state.auto422Timer);\n    state.auto422Timer = null;\n  }\n  if (nextPage !== '视频切帧') clearTimer(window.__videoFramePollTimer);\n  if (!['自动标注', '自动标注及清洗'].includes(nextPage)) clearTimer(window.__prelabelPollTimer);\n""", '', 'remove retired navigation fallback timers')
write(path, text)

# 4) Focused tests: remove expectations for timers that no longer exist.
path = 'tests/frontend/navigation-stability.test.mjs'
text = read(path)
text = replace_once(text,
"""test('navigation clears page-owned polling timers when leaving the page', () => {\n  const state = {page: '训练任务', jobPollTimer: 101, source422Timer: 202, auto422Timer: 303};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n    __videoFramePollTimer: 404,\n    __prelabelPollTimer: 505,\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(new Set(cleared), new Set([101, 202, 303, 404, 505]));\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n  assert.equal(state.auto422Timer, null);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n""",
"""test('navigation fallback clears remaining page-owned polling timers when PollRegistry is absent', () => {\n  const state = {page: '训练任务', jobPollTimer: 101, source422Timer: 202};\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = value => cleared.push(value);\n\n  globalThis.document = {\n    getElementById() { return {dataset: {}}; },\n  };\n  globalThis.window = {\n    setPage(page) { state.page = page; },\n  };\n\n  const runtime = installNavigationStability({getState: () => state});\n  globalThis.window.setPage('算法列表');\n\n  assert.deepEqual(new Set(cleared), new Set([101, 202]));\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  cleanup();\n});\n""", 'update navigation legacy timer test')
write(path, text)

path = 'tests/frontend/poll-registry.test.mjs'
text = read(path)
text = replace_once(text,
"""test('legacy page timers are adopted and references are cleared when navigating away', () => {\n  const state = {\n    jobPollTimer: 1,\n    source422Timer: 2,\n    auto422Timer: 3,\n  };\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = id => cleared.push(id);\n  globalThis.window = {\n    __videoFramePollTimer: 4,\n    __prelabelPollTimer: 5,\n  };\n\n  const runtime = installPollRegistry({getState: () => state});\n  runtime.beforeNavigate('数据集');\n\n  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2, 3, 4, 5]);\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n  assert.equal(state.auto422Timer, null);\n  assert.equal(globalThis.window.__videoFramePollTimer, null);\n  assert.equal(globalThis.window.__prelabelPollTimer, null);\n  assert.deepEqual(runtime.snapshot(), []);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n""",
"""test('remaining legacy page timers are adopted and references are cleared when navigating away', () => {\n  const state = {\n    jobPollTimer: 1,\n    source422Timer: 2,\n  };\n  const cleared = [];\n  const originalClearInterval = globalThis.clearInterval;\n  globalThis.clearInterval = id => cleared.push(id);\n  globalThis.window = {};\n\n  const runtime = installPollRegistry({getState: () => state});\n  runtime.beforeNavigate('数据集');\n\n  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2]);\n  assert.equal(state.jobPollTimer, null);\n  assert.equal(state.source422Timer, null);\n  assert.deepEqual(runtime.snapshot(), []);\n\n  runtime.destroy();\n  globalThis.clearInterval = originalClearInterval;\n  delete globalThis.window;\n});\n""", 'update PollRegistry legacy adoption test')
text = replace_once(text, """    auto422Timer: null,\n""", "", 'remove auto422 from training fixture')
# There are two additional fixtures with the same line; retire them deterministically.
for index in range(2):
    text = replace_once(text, """    auto422Timer: null,\n""", "", f'remove auto422 fixture {index+2}')
text = replace_once(text, """    __videoFramePollTimer: 199,\n""", "", 'remove retired video fixture')
text = replace_once(text, """  assert.ok(clearedIntervals.includes(199), 'legacy v33 video interval should be retired');\n""", "", 'remove retired video expectation')
write(path, text)

for product in ('static/app.js', 'static/modules/poll-registry.js', 'static/modules/navigation-stability.js'):
    src = read(product)
    for token in ('auto422Timer', '__videoFramePollTimer', '__prelabelPollTimer'):
        if token in src:
            raise SystemExit(f'{product}: retired legacy timer token remains: {token}')

if '_oldSetupPollV33' in read('static/app.js'):
    raise SystemExit('v33 setupPagePolling compatibility wrapper remains')

print('retired legacy AutoLabel/video/prelabel timer compatibility')
