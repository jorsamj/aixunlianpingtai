import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const owner = app.match(/window\.saveServer=async\(\)=>\{[^\n]+\};/)?.[0] || '';

test('training server save has one final scoped-refresh owner', () => {
  assert.equal(app.split('window.saveServer=').length - 1, 1);
  assert.notEqual(owner, '');
  assert.match(owner, /\/api\/train_servers/);
  assert.match(owner, /\/api\/training_options\?project_id=/);
  assert.match(owner, /if\(opts\)state\.targets=opts\.targets\|\|\[\];render\(\);toast\('已保存服务器'\)/);
});

test('training server save cannot return to global reload', () => {
  assert.equal(owner.includes("await reload()"), false);
  assert.equal(owner.includes("loadAll()"), false);
  assert.equal(owner.includes("loadRelated()"), false);
  assert.equal(owner.includes("const opts=await safe(api(`/api/training_options?project_id=${pid()}`))"), true);
});

test('training server save fences stale mutation completion before modal, fetch, and render effects', () => {
  assert.equal(owner.includes('NavigationStability?.action?.(state.page)'), true);
  const postIndex = owner.indexOf("await safe(api('/api/train_servers'");
  const firstFenceIndex = owner.indexOf('if(!saved||(action&&!action.isCurrent()))return;');
  const closeIndex = owner.indexOf('closeModal();');
  const optionsIndex = owner.indexOf('const opts=await safe(api(`/api/training_options');
  const secondFenceIndex = owner.indexOf('if(action&&!action.isCurrent())return;', firstFenceIndex + 1);
  const renderIndex = owner.indexOf('render();');

  assert.ok(postIndex >= 0);
  assert.ok(firstFenceIndex > postIndex, 'first stale fence must run after the POST settles');
  assert.ok(closeIndex > firstFenceIndex, 'stale completion must be rejected before closeModal');
  assert.ok(optionsIndex > closeIndex, 'training_options remains a scoped post-save refresh');
  assert.ok(secondFenceIndex > optionsIndex, 'second stale fence must protect state/render after refresh');
  assert.ok(renderIndex > secondFenceIndex, 'render must remain behind the second stale fence');
});
