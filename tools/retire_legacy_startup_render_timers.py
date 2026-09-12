from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/startup-render-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

legacy_timers = [
    "  setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},80);\n",
    "  setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},100);\n",
    "  setTimeout(()=>{if(state?.project){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};render()}},120);\n",
]
for timer in legacy_timers:
    if app.count(timer) != 1:
        raise SystemExit(f'expected exactly one legacy startup timer: {timer!r}; found {app.count(timer)}')
    app = app.replace(timer, '', 1)

for token in (
    'queueMicrotask(()=>{if(window.__clInit)window.__clInit()});',
    'window.__clInit=function(){if(window.__v53InitPromise)return window.__v53InitPromise;',
    "setTimeout(()=>{renderTop();cleanup(document);},100);",
):
    if token not in app:
        raise SystemExit(f'required final startup/cleanup contract missing: {token}')

for retired in legacy_timers:
    if retired.strip() in app:
        raise SystemExit(f'legacy startup timer remains: {retired.strip()}')

old_cache = '/static/app.js?v=42.25.71'
new_cache = '/static/app.js?v=42.25.72'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one {old_cache}, found {index.count(old_cache)}')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const legacyStartupTimers = [
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},80);",
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},100);",
  "setTimeout(()=>{if(state?.project){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};render()}},120);",
];

test('legacy v35/v36/v37 startup render timers cannot return', () => {
  for (const timer of legacyStartupTimers) assert.equal(app.includes(timer), false);
});

test('startup dispatch remains owned by the final __clInit path', () => {
  assert.equal(app.includes('queueMicrotask(()=>{if(window.__clInit)window.__clInit()});'), true);
  assert.equal(app.includes('window.__clInit=function(){if(window.__v53InitPromise)return window.__v53InitPromise;'), true);
});

test('bounded cleanup timer is not confused with retired startup renders', () => {
  assert.equal(app.includes("setTimeout(()=>{renderTop();cleanup(document);},100);"), true);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('retired v35/v36/v37 startup render timers; final __clInit remains startup owner')
