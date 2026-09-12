from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'static/app.js'
INDEX=ROOT/'static/index.html'
BROWSER=ROOT/'tests/browser/navigation-stability.spec.mjs'
UNIT=ROOT/'tests/frontend/paddle-resource-refresh-owner.test.mjs'

app=APP.read_text(encoding='utf-8')
final_marker="  window.detectPaddle=async function(){\n    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'检测中'); state.resourceBusy=true;"
if app.count(final_marker)!=1:
    raise SystemExit(f'R20d final detectPaddle marker count={app.count(final_marker)}')
helper="""  async function refreshPaddleTrainingTargets20d(){
    const opts=await api(`/api/training_options?project_id=${pid()}`);
    state.targets=opts?.targets||[];
    return state.targets;
  }
"""
app=app.replace(final_marker,helper+final_marker,1)
old_manual="const cur='训练资源'; await loadAll(); state.page=cur; render(); toast('飞桨环境已启用');"
new_manual="await refreshPaddleTrainingTargets20d(); state.page='训练资源'; render(); toast('飞桨环境已启用');"
if app.count(old_manual)!=1:
    raise SystemExit(f'R20d manual full-refresh anchor count={app.count(old_manual)}')
app=app.replace(old_manual,new_manual,1)
old_quick="state.page='训练资源'; await loadAll(); render(); toast('已启用飞桨环境');"
new_quick="await refreshPaddleTrainingTargets20d(); state.page='训练资源'; render(); toast('已启用飞桨环境');"
if app.count(old_quick)!=1:
    raise SystemExit(f'R20d quick full-refresh anchor count={app.count(old_quick)}')
app=app.replace(old_quick,new_quick,1)
if old_manual in app or old_quick in app:
    raise SystemExit('R20d final paddle loadAll refresh survived')
APP.write_text(app,encoding='utf-8')

idx=INDEX.read_text(encoding='utf-8')
old_cache='/static/app.js?v=42.25.79'
new_cache='/static/app.js?v=42.25.80'
if idx.count(old_cache)!=1:
    raise SystemExit(f'R20d app cache anchor count={idx.count(old_cache)}')
INDEX.write_text(idx.replace(old_cache,new_cache,1),encoding='utf-8')

b=BROWSER.read_text(encoding='utf-8')
start=b.index("test('paddle environment activation keeps manual and quick-detect behavior'")
tail=b[start:]
anchor="""  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');

  const paddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();"""
replacement="""  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');

  const projectId = await page.evaluate(() => state.project?.id || '');
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.route(/\\/api\\/training_options(?:\\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'local_paddle',
        name: 'R20d 飞桨环境',
        framework: 'paddle',
        type: 'local',
        version: '3.0.0',
        status: 'ready',
        python_path: '/opt/paddle/bin/python',
        paddledet_dir: '/opt/PaddleDetection',
        paddlex_dir: '/opt/PaddleX',
        algorithms: [],
        base_models: [],
      }]}),
    });
  });

  const paddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();"""
if tail.count(anchor)!=1:
    raise SystemExit(f'R20d browser setup anchor count={tail.count(anchor)}')
tail=tail.replace(anchor,replacement,1)
anchor2="""  expect(selectBodies.at(-1)).toMatchObject({
    name: '自动飞桨',
    python_path: '/opt/paddle/bin/python',
    paddledet_dir: '/opt/PaddleDetection',
    paddlex_dir: '/opt/PaddleX',
  });
  expect(pageErrors).toEqual([]);"""
replacement2="""  expect(selectBodies.at(-1)).toMatchObject({
    name: '自动飞桨',
    python_path: '/opt/paddle/bin/python',
    paddledet_dir: '/opt/PaddleDetection',
    paddlex_dir: '/opt/PaddleX',
  });
  await expect.poll(async () => page.evaluate(() => state.targets.find(x => x.id === 'local_paddle')?.name || '')).toBe('R20d 飞桨环境');
  const relevant = actionRequests.filter(row => row.includes('/api/paddle_env/') || row.includes('/api/training_options') || row.includes('/bootstrap/snapshot'));
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/select'))).toHaveLength(2);
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/test'))).toHaveLength(1);
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/detect'))).toHaveLength(1);
  expect(relevant.filter(row => row === `GET /api/training_options?project_id=${projectId}`)).toHaveLength(2);
  expect(relevant.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);"""
if tail.count(anchor2)!=1:
    raise SystemExit(f'R20d browser result anchor count={tail.count(anchor2)}')
tail=tail.replace(anchor2,replacement2,1)
BROWSER.write_text(b[:start]+tail,encoding='utf-8')

UNIT.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const manualStart = app.lastIndexOf("window.detectPaddle=async function(){");
const quickStart = app.lastIndexOf("window.quickPaddleDetect=async function(){");
assert.ok(manualStart >= 0 && quickStart > manualStart);
const manual = app.slice(manualStart, quickStart);
const quick = app.slice(quickStart, app.indexOf('\n  };', quickStart) + 5);

test('final paddle activation owners use scoped training-target refresh', () => {
  assert.equal(app.match(/async function refreshPaddleTrainingTargets20d\(\)/g)?.length, 1);
  assert.match(app, /refreshPaddleTrainingTargets20d[\s\S]*\/api\/training_options\?project_id=\$\{pid\(\)\}/);
  assert.match(manual, /await refreshPaddleTrainingTargets20d\(\)/);
  assert.match(quick, /await refreshPaddleTrainingTargets20d\(\)/);
});

test('final paddle activation owners do not invoke global loadAll refresh', () => {
  assert.equal(manual.includes('await loadAll()'), false);
  assert.equal(quick.includes('await loadAll()'), false);
  assert.equal(app.includes("const cur='训练资源'; await loadAll(); state.page=cur; render(); toast('飞桨环境已启用')"), false);
  assert.equal(app.includes("state.page='训练资源'; await loadAll(); render(); toast('已启用飞桨环境')"), false);
});
""",encoding='utf-8')

if (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()!='42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20d paddle activation refresh migrated to training_options-only ownership')
