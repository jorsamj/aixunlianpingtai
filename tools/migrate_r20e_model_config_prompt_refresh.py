from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static/app.js'
INDEX = ROOT / 'static/index.html'
BROWSER = ROOT / 'tests/browser/navigation-stability.spec.mjs'
UNIT = ROOT / 'tests/frontend/model-config-prompt-refresh-owner.test.mjs'
VERSION = ROOT / 'VERSION.txt'

app = APP.read_text(encoding='utf-8')

old_model_delete = "window.deleteModelConfigV35=async function(id){if(!confirm('确认删除这个模型配置？'))return;await safe(api(`/api/v35/model-configs/${id}`,{method:'DELETE'}));await loadAll();render();toast('已删除')};"
new_model_delete = "window.deleteModelConfigV35=async function(id){if(!confirm('确认删除这个模型配置？'))return;const r=await safe(api(`/api/v35/model-configs/${id}`,{method:'DELETE'}));if(!r?.ok)return;state.modelConfigs=(state.modelConfigs||[]).filter(x=>String(x.id)!==String(id));render();toast('已删除')};"
if app.count(old_model_delete) != 1:
    raise SystemExit(f'R20e model delete anchor count={app.count(old_model_delete)}')
app = app.replace(old_model_delete, new_model_delete, 1)

old_prompt_save_tail = """    await safe(api(id?`/api/v35/prompt-templates/${id}`:'/api/v35/prompt-templates',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    closeModal();await loadAll();render();toast('已保存模型标注模板');
  };
  window.deletePromptTemplateV35=async function(id){if(!confirm('确认删除这个模板？'))return;await safe(api(`/api/v35/prompt-templates/${id}`,{method:'DELETE'}));await loadAll();render();toast('已删除')};"""
new_prompt_save_tail = """    const item=await safe(api(id?`/api/v35/prompt-templates/${id}`:'/api/v35/prompt-templates',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    if(!item?.id)return;
    const current=state.promptTemplates||[],idx=current.findIndex(x=>String(x.id)===String(item.id));
    if(idx>=0){state.promptTemplates=[...current];state.promptTemplates[idx]=item}else state.promptTemplates=[item,...current];
    closeModal();render();toast('已保存模型标注模板');
  };
  window.deletePromptTemplateV35=async function(id){if(!confirm('确认删除这个模板？'))return;const r=await safe(api(`/api/v35/prompt-templates/${id}`,{method:'DELETE'}));if(!r?.ok)return;state.promptTemplates=(state.promptTemplates||[]).filter(x=>String(x.id)!==String(id));render();toast('已删除')};"""
if app.count(old_prompt_save_tail) != 1:
    raise SystemExit(f'R20e prompt mutation anchor count={app.count(old_prompt_save_tail)}')
app = app.replace(old_prompt_save_tail, new_prompt_save_tail, 1)

for forbidden in [
    "window.deleteModelConfigV35=async function(id){if(!confirm('确认删除这个模型配置？'))return;await safe(api(`/api/v35/model-configs/${id}`,{method:'DELETE'}));await loadAll();render();toast('已删除')};",
    "closeModal();await loadAll();render();toast('已保存模型标注模板')",
    "await safe(api(`/api/v35/prompt-templates/${id}`,{method:'DELETE'}));await loadAll();render();toast('已删除')",
]:
    if forbidden in app:
        raise SystemExit(f'R20e retired full-refresh mutation survived: {forbidden[:70]}')
APP.write_text(app, encoding='utf-8')

idx = INDEX.read_text(encoding='utf-8')
old_cache = '/static/app.js?v=42.25.80'
new_cache = '/static/app.js?v=42.25.81'
if idx.count(old_cache) != 1:
    raise SystemExit(f'R20e app cache anchor count={idx.count(old_cache)}')
INDEX.write_text(idx.replace(old_cache, new_cache, 1), encoding='utf-8')

b = BROWSER.read_text(encoding='utf-8')

# Model-config delete: record only action-time API traffic and forbid reload GETs.
anchor = """  await expect(page.locator('#view')).toContainText('R20e 模型配置');

  await page.getByRole('button', {name: '删除'}).first().click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 模型配置');
  expect(pageErrors).toEqual([]);"""
replacement = """  await expect(page.locator('#view')).toContainText('R20e 模型配置');

  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.getByRole('button', {name: '删除'}).first().click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 模型配置');
  expect(actionRequests.filter(row => row === 'DELETE /api/v35/model-configs/cfg-r20e')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);"""
if b.count(anchor) != 1:
    raise SystemExit(f'R20e model delete browser anchor count={b.count(anchor)}')
b = b.replace(anchor, replacement, 1)

# Prompt save: authoritative POST result must patch state immediately with no reload GET.
anchor = """  await page.locator('#ptPrompt').fill('detect fire and return bbox json');
  await page.getByRole('button', {name: '保存模板'}).click();
  await expect(page.locator('#toast')).toContainText('已保存模型标注模板');
  await expect(page.locator('#view')).toContainText('R20e 新提示词');
  expect(pageErrors).toEqual([]);"""
replacement = """  await page.locator('#ptPrompt').fill('detect fire and return bbox json');
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.getByRole('button', {name: '保存模板'}).click();
  await expect(page.locator('#toast')).toContainText('已保存模型标注模板');
  await expect(page.locator('#view')).toContainText('R20e 新提示词');
  await expect.poll(async () => page.evaluate(() => state.promptTemplates.find(x => x.id === 'tpl-r20e-new')?.name || '')).toBe('R20e 新提示词');
  expect(actionRequests.filter(row => row === 'POST /api/v35/prompt-templates')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/prompt-templates'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);"""
if b.count(anchor) != 1:
    raise SystemExit(f'R20e prompt save browser anchor count={b.count(anchor)}')
b = b.replace(anchor, replacement, 1)

# Prompt delete: local removal must be immediate and must not reload unrelated data.
anchor = """  const row = page.locator('tr').filter({hasText: 'R20e 旧提示词'});
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 旧提示词');
  expect(pageErrors).toEqual([]);"""
replacement = """  const row = page.locator('tr').filter({hasText: 'R20e 旧提示词'});
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 旧提示词');
  await expect.poll(async () => page.evaluate(() => state.promptTemplates.some(x => x.id === 'tpl-r20e-old'))).toBe(false);
  expect(actionRequests.filter(row => row === 'DELETE /api/v35/prompt-templates/tpl-r20e-old')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/prompt-templates'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);"""
if b.count(anchor) != 1:
    raise SystemExit(f'R20e prompt delete browser anchor count={b.count(anchor)}')
b = b.replace(anchor, replacement, 1)
BROWSER.write_text(b, encoding='utf-8')

UNIT.write_text(r"""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function sliceFrom(startToken, endToken) {
  const start = app.indexOf(startToken);
  assert.ok(start >= 0, `missing ${startToken}`);
  const end = app.indexOf(endToken, start + startToken.length);
  assert.ok(end > start, `missing end token ${endToken}`);
  return app.slice(start, end);
}

const modelDelete = sliceFrom('window.deleteModelConfigV35=async function(id){', 'window.testModelConfigV35=async function(id)');
const promptSave = sliceFrom("window.savePromptTemplateV35=async function(id=''){", 'window.deletePromptTemplateV35=async function(id)');
const promptDelete = sliceFrom('window.deletePromptTemplateV35=async function(id){', '// ---------- Auto labeling ----------');

test('live model-config delete owns a local state removal with no global refresh', () => {
  assert.match(modelDelete, /method:'DELETE'/);
  assert.match(modelDelete, /state\.modelConfigs=.*filter/);
  assert.equal(modelDelete.includes('loadAll()'), false);
  assert.equal(modelDelete.includes('loadRelated()'), false);
});

test('live prompt save uses authoritative mutation result and local upsert', () => {
  assert.match(promptSave, /const item=await safe\(api/);
  assert.match(promptSave, /state\.promptTemplates/);
  assert.match(promptSave, /findIndex/);
  assert.equal(promptSave.includes('loadAll()'), false);
  assert.equal(promptSave.includes('loadRelated()'), false);
});

test('live prompt delete owns a local state removal with no global refresh', () => {
  assert.match(promptDelete, /method:'DELETE'/);
  assert.match(promptDelete, /state\.promptTemplates=.*filter/);
  assert.equal(promptDelete.includes('loadAll()'), false);
  assert.equal(promptDelete.includes('loadRelated()'), false);
});

test('final model configuration renderer still reaches the migrated mutation owners', () => {
  const finalRenderer = app.slice(app.lastIndexOf('window.renderModelConfigPageV35=function()'));
  assert.match(finalRenderer, /deleteModelConfigV35/);
  assert.match(app, /onclick=\\"savePromptTemplateV35\('/);
  assert.match(app, /onclick=\\"deletePromptTemplateV35\('/);
});
""", encoding='utf-8')

if VERSION.read_text(encoding='utf-8').strip() != '42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20e model-config/prompt mutations migrated to authoritative local state ownership')
