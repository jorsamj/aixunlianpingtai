from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
BROWSER = ROOT / 'tests/browser/navigation-stability.spec.mjs'
UNIT = ROOT / 'tests/frontend/training-server-refresh-owner.test.mjs'

old = "window.saveServer=async()=>{await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));closeModal();await reload();toast('已保存服务器')};"
new = "window.saveServer=async()=>{await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};"

app = APP.read_text(encoding='utf-8')
if app.count(old) != 1:
    raise SystemExit(f'R20c expected exactly 1 live reload-backed saveServer owner, got {app.count(old)}')
app = app.replace(old, new, 1)
if app.count('window.saveServer=') != 1:
    raise SystemExit(f'R20c saveServer owner count={app.count("window.saveServer=")}')
if old in app or "closeModal();await reload();toast('已保存服务器')" in app:
    raise SystemExit('R20c reload-backed saveServer survived')
APP.write_text(app, encoding='utf-8')

idx = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.78'
new_cache = '/static/app.js?v=42.25.79'
if idx.count(old_cache) != 1:
    raise SystemExit(f'R20c app cache anchor count={idx.count(old_cache)}')
INDEX.write_text(idx.replace(old_cache, new_cache, 1), encoding='utf-8')

b = BROWSER.read_text(encoding='utf-8')
anchor = """  await page.locator('#sname').fill('R20c训练服务器');
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);"""
replacement = """  await page.locator('#sname').fill('R20c训练服务器');
  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  await page.route(`**/api/training_options?project_id=${encoded}`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'server-r20c',
        name: 'R20c训练服务器',
        type: 'server',
        framework: 'ultralytics',
        status: 'ready',
        version: 'remote',
        algorithms: [],
        base_models: [],
      }]}),
    });
  });
  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);"""
if b.count(anchor) != 1:
    raise SystemExit(f'R20c browser click anchor count={b.count(anchor)}')
b = b.replace(anchor, replacement, 1)

anchor2 = """  expect(submittedBody).toEqual({
    name: 'R20c训练服务器',
    base_url: 'http://127.0.0.1:18020',
  });
  expect(pageErrors).toEqual([]);"""
replacement2 = """  expect(submittedBody).toEqual({
    name: 'R20c训练服务器',
    base_url: 'http://127.0.0.1:18020',
  });
  await expect.poll(async () => page.evaluate(() => state.targets.find(x => x.id === 'server-r20c')?.name || null)).toBe('R20c训练服务器');
  await expect(page.locator('.resource-grid')).toContainText('R20c训练服务器');
  const ownedRequests = requests.filter(row => row.includes('/api/train_servers') || row.includes('/api/training_options') || row.includes('/bootstrap/snapshot'));
  expect(ownedRequests).toEqual([
    'POST /api/train_servers',
    `GET /api/training_options?project_id=${projectId}`,
  ]);
  expect(pageErrors).toEqual([]);"""
if b.count(anchor2) != 1:
    raise SystemExit(f'R20c browser result anchor count={b.count(anchor2)}')
BROWSER.write_text(b.replace(anchor2, replacement2, 1), encoding='utf-8')

UNIT.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.saveServer=async()=>{await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};";

test('training server save has one final scoped-refresh owner', () => {
  assert.equal(app.split('window.saveServer=').length - 1, 1);
  assert.equal(app.includes(owner), true);
});

test('training server save cannot return to global reload', () => {
  assert.equal(app.includes("closeModal();await reload();toast('已保存服务器')"), false);
  assert.equal(app.includes("const opts=await safe(api(`/api/training_options?project_id=${pid()}`))"), true);
  assert.equal(app.includes("if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')"), true);
});
""", encoding='utf-8')

if (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20c training server save migrated from page reload to training_options-only refresh')
