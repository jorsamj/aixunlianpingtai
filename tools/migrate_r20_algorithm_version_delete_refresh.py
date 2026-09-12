from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
BROWSER = ROOT / 'tests/browser/algorithm-list-performance.spec.mjs'
UNIT = ROOT / 'tests/frontend/algorithm-version-refresh-owner.test.mjs'

old = "window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));closeModal();await reload();toast('已删除版本')};"
new = "window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));closeModal();const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('算法列表刷新模块未加载，请刷新页面后重试');return}await runtime.refresh({render:true});toast('已删除版本')};"

app = APP.read_text(encoding='utf-8')
if app.count(old) != 1:
    raise SystemExit(f'R20 expected exactly 1 live delVersion owner, got {app.count(old)}')
app = app.replace(old, new, 1)
if app.count('window.delVersion=') != 1:
    raise SystemExit(f'R20 delVersion owner count={app.count("window.delVersion=")}')
if old in app:
    raise SystemExit('R20 reload-backed delVersion survived')
APP.write_text(app, encoding='utf-8')

idx = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.76'
new_cache = '/static/app.js?v=42.25.77'
if idx.count(old_cache) != 1:
    raise SystemExit(f'R20 app cache anchor count={idx.count(old_cache)}')
INDEX.write_text(idx.replace(old_cache, new_cache, 1), encoding='utf-8')

b = BROWSER.read_text(encoding='utf-8')
anchor = "  expect(requests.some(row => row === `DELETE /api/v12/projects/${projectId}/algorithms/algo-version-delete/versions/version-delete-1`)).toBe(true);\n  expect(pageErrors).toEqual([]);"
replacement = "  expect(requests.sort()).toEqual([\n    `DELETE /api/v12/projects/${projectId}/algorithms/algo-version-delete/versions/version-delete-1`,\n    `GET /api/projects/${projectId}/jobs`,\n    `GET /api/v12/projects/${projectId}/algorithms`,\n  ].sort());\n  expect(pageErrors).toEqual([]);"
if b.count(anchor) != 1:
    raise SystemExit(f'R20 browser request-anchor count={b.count(anchor)}')
BROWSER.write_text(b.replace(anchor, replacement, 1), encoding='utf-8')

UNIT.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));closeModal();const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('算法列表刷新模块未加载，请刷新页面后重试');return}await runtime.refresh({render:true});toast('已删除版本')};";

test('algorithm version deletion has one final owner', () => {
  assert.equal(app.split('window.delVersion=').length - 1, 1);
  assert.equal(app.includes(owner), true);
});

test('algorithm version deletion cannot return to global reload', () => {
  assert.equal(app.includes("closeModal();await reload();toast('已删除版本')"), false);
  assert.equal(app.includes("await runtime.refresh({render:true});toast('已删除版本')"), true);
});
""", encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20 algorithm version deletion migrated to focused refresh')
