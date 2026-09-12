from pathlib import Path
import re

APP = Path('static/app.js')
INDEX = Path('static/index.html')
FRONTEND_TEST = Path('tests/frontend/legacy-algorithm-crud-owner.test.mjs')
BROWSER_TEST = Path('tests/browser/algorithm-crud-owner.spec.mjs')

if Path('VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION.txt must remain 42.24.0')

app = APP.read_text(encoding='utf-8')
original = app

# R20h-1: replace the original full algorithm renderer + obsolete CRUD globals with a
# bounded compatibility render symbol. Historical render maps still evaluate the
# renderAlgorithms binding for non-algorithm pages, so the symbol stays until those
# maps are retired in a later generation cleanup.
start_marker = 'function renderAlgorithms(){'
end_marker = 'window.delVersion='
start = app.find(start_marker)
end = app.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('base algorithm CRUD block anchors not found')
base_block = app[start:end]
for required in (
    'window.newAlgorithm=',
    'window.saveAlgorithm=',
    'window.editAlgorithm=',
    'window.saveEditAlgorithm=',
    'window.delAlgorithm=',
    'window.viewAlgorithm=',
    'window.showReport=',
    'await reload()',
):
    if required not in base_block:
        raise SystemExit(f'base algorithm block no longer matches expected legacy owner: {required}')
app = app[:start] + 'function renderAlgorithms(){return window.renderAlgorithms423?.()}\n' + app[end:]

# R20h-2: v30 supplied another obsolete algorithm renderer that only pointed at the
# now-retired CRUD globals. Keep the rest of v30 intact.
pattern = re.compile(
    r'  const oldRenderAlgorithms = window\.renderAlgorithms;\n'
    r'  window\.renderAlgorithms=function\(\)\{.*?\n  \};\n'
    r'(?=  render=function\(\)\{)',
    re.S,
)
app, count = pattern.subn('', app, count=1)
if count != 1:
    raise SystemExit(f'expected one v30 algorithm renderer override, got {count}')

# R20h-3: v42.2 algorithm page generation is shadowed by the final oldRender412
# routing contract, which directly renders renderAlgorithms423 for 算法列表. Remove
# that self-contained generation but retain the live v42.2 source-management code.
start_marker = '  function renderAlgorithmCards422(){'
end_marker = '  // -------- Sources --------'
start = app.find(start_marker)
end = app.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit('v42.2 algorithm generation anchors not found')
v422_block = app[start:end]
for required in ('window.renderAlgorithms422=', 'window.openNewAlgorithm422=', 'window.saveNewAlgorithm422='):
    if required not in v422_block:
        raise SystemExit(f'v42.2 algorithm block missing expected token: {required}')
app = app[:start] + app[end:]
route_line = "    if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms422();return}\n"
if app.count(route_line) != 1:
    raise SystemExit(f'expected one v42.2 algorithm route branch, got {app.count(route_line)}')
app = app.replace(route_line, '', 1)

# Permanent semantic proof: final algorithm routing and CRUD owners must already exist.
required_live = (
    "if(state.page==='算法列表'){renderAlgorithms423();return}",
    'window.openNewAlgorithm423=function()',
    'window.saveNewAlgorithm414=async function()',
    'window.editAlgorithm423=function(id)',
    'window.saveEditAlgorithm414=async id=>',
    'window.delAlgorithm=async id=>',
    'data-action="algorithm.create"',
    "onclick=\"editAlgorithm423('",
    "onclick=\"viewAlgorithm429('",
)
for token in required_live:
    if token not in app:
        raise SystemExit(f'current algorithm owner missing before migration: {token}')

retired = (
    'window.newAlgorithm=',
    'window.saveAlgorithm=',
    'window.editAlgorithm=',
    'window.saveEditAlgorithm=',
    'window.viewAlgorithm=',
    'window.showReport=',
    'const oldRenderAlgorithms = window.renderAlgorithms;',
    'function renderAlgorithmCards422(){',
    'window.renderAlgorithms422=',
    'window.openNewAlgorithm422=',
    'window.saveNewAlgorithm422=',
    "renderAlgorithms422();return",
)
for token in retired:
    if token in app:
        raise SystemExit(f'legacy algorithm owner survived migration: {token}')

if app == original:
    raise SystemExit('migration produced no app.js change')
APP.write_text(app, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
old_cache = '<script src="/static/app.js?v=42.25.83"></script>'
new_cache = '<script src="/static/app.js?v=42.25.84"></script>'
if index.count(old_cache) != 1:
    raise SystemExit('expected app.js cache marker 42.25.83 exactly once')
INDEX.write_text(index.replace(old_cache, new_cache, 1), encoding='utf-8')

FRONTEND_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const main = fs.readFileSync('static/main.mjs', 'utf8');

const retired = [
  'window.newAlgorithm=',
  'window.saveAlgorithm=',
  'window.editAlgorithm=',
  'window.saveEditAlgorithm=',
  'window.viewAlgorithm=',
  'window.showReport=',
  'const oldRenderAlgorithms = window.renderAlgorithms;',
  'function renderAlgorithmCards422(){',
  'window.renderAlgorithms422=',
  'window.openNewAlgorithm422=',
  'window.saveNewAlgorithm422=',
  "renderAlgorithms422();return",
];

test('legacy algorithm CRUD and shadowed renderer owners stay retired', () => {
  for (const token of retired) {
    assert.equal(app.includes(token), false, `retired algorithm owner reintroduced: ${token}`);
  }
});

test('current algorithm page is fenced to stable renderer and semantic create action', () => {
  assert.match(app, /if\(state\.page==='算法列表'\)\{renderAlgorithms423\(\);return\}/);
  assert.match(app, /function renderAlgorithms\(\)\{return window\.renderAlgorithms423\?\.\(\)\}/);
  assert.match(app, /data-action="algorithm\.create"/);
  assert.match(main, /registerAction\('algorithm\.create',[\s\S]*?window\.openNewAlgorithm423\(\)/);
});

test('stable algorithm mutations patch authoritative local state without broad reload', () => {
  const createStart = app.indexOf('window.saveNewAlgorithm414=async function()');
  const editStart = app.indexOf('window.saveEditAlgorithm414=async id=>');
  const deleteStart = app.indexOf('window.delAlgorithm=async id=>', editStart);
  assert.ok(createStart >= 0 && editStart > createStart && deleteStart > editStart);
  const createBlock = app.slice(createStart, editStart);
  const editBlock = app.slice(editStart, deleteStart);
  const deleteEnd = app.indexOf('// ---------- training iteration', deleteStart);
  assert.ok(deleteEnd > deleteStart);
  const deleteBlock = app.slice(deleteStart, deleteEnd);
  for (const [name, block] of [['create', createBlock], ['edit', editBlock], ['delete', deleteBlock]]) {
    assert.equal(block.includes('await reload()'), false, `${name} must not use reload()`);
    assert.equal(block.includes('await loadAll()'), false, `${name} must not use loadAll()`);
    assert.equal(block.includes('await loadRelated()'), false, `${name} must not use loadRelated()`);
  }
  assert.match(createBlock, /state\.algorithms=\[item,/);
  assert.match(editBlock, /state\.algorithms\[i\]=item/);
  assert.match(deleteBlock, /state\.algorithms=\(state\.algorithms\|\|\[\]\)\.filter/);
});
''', encoding='utf-8')

BROWSER_TEST.write_text(r'''import {test, expect} from '@playwright/test';

test('algorithm create edit delete uses authoritative local state without broad refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412)).toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({algorithm: {
        id: 'algo-r20h-crud',
        name: 'R20h 创建算法',
        remark: 'create local state',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }}),
    });
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-r20h-crud`, async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({algorithm: {
          id: 'algo-r20h-crud',
          name: 'R20h 已编辑算法',
          remark: 'edit local state',
          industry: '测试',
          algorithm_type: 'yolo_ultralytics',
          versions: [],
        }}),
      });
    }
    if (route.request().method() === 'DELETE') {
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
    }
    return route.continue();
  });

  await page.locator('[data-action="algorithm.create"]').click();
  await expect(page.locator('#alg414Name')).toBeVisible();
  await page.locator('#alg414Name').fill('R20h 创建算法');
  await page.locator('#alg414Industry').fill('测试');
  await page.locator('#alg414Remark').fill('create local state');
  await page.locator('#alg414Save').click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 创建算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(true);

  const card = page.locator('.alg428-card').filter({hasText: 'R20h 创建算法'});
  await card.getByRole('button', {name: '编辑'}).click();
  await expect(page.locator('#alg414EditName')).toHaveValue('R20h 创建算法');
  await page.locator('#alg414EditName').fill('R20h 已编辑算法');
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 已编辑算法');

  page.once('dialog', dialog => dialog.accept());
  const editedCard = page.locator('.alg428-card').filter({hasText: 'R20h 已编辑算法'});
  await editedCard.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#alg412List')).not.toContainText('R20h 已编辑算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(false);

  const expected = [
    `POST /api/v12/projects/${projectId}/algorithms`,
    `PUT /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
    `DELETE /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
  ];
  for (const row of expected) expect(requests.filter(x => x === row)).toEqual([row]);

  const unexpected = requests.filter(row => !expected.includes(row));
  expect(unexpected).toEqual([]);
  expect(pageErrors).toEqual([]);
});
''', encoding='utf-8')

print(f'R20h migrated legacy algorithm CRUD owners; app.js {len(original)} -> {len(app)} bytes')
