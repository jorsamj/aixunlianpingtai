import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const navigation = fs.readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');

test('pre-v42.4 severed setPage wrappers cannot return', () => {
  for (const token of ['oldSetV39', 'oldSet42', 'set422Base']) {
    assert.equal(app.includes(token), false, `${token} must remain retired`);
  }
});

test('pre-v42.7 direct setPage owners cannot return after persistence moved to final navigation', () => {
  assert.equal(
    app.includes('window.setPage=function(p){state.page=p;render()};'),
    false,
    'plain v35/v42.4 direct setPage owners must remain retired',
  );
  assert.equal(
    app.includes('window.setPage=function(p){\n    state.page=p;\n    saveUiState();\n    render();\n  };'),
    false,
    'v34 persistence setPage owner must remain retired',
  );
});

test('v42.7 direct route owner cannot return after alias normalization moved to final navigation', () => {
  assert.equal(
    app.includes("window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};try{setPage=window.setPage}catch(e){}"),
    false,
    'v42.7 direct auto-label route owner must remain retired',
  );
  assert.equal(navigation.includes('export function normalizeNavigationPage(page)'), true, 'semantic page normalizer must remain');
  assert.equal(navigation.includes("requested === '自动标注' ? '自动标注及清洗' : requested"), true, 'legacy auto-label alias must remain canonicalized');
});

test('classic startup readiness owner cannot return after readiness moved to final navigation', () => {
  assert.equal(app.includes('setPageReady414'), false, 'classic startup readiness owner must remain retired');
  assert.equal(navigation.includes('waitForNavigationReady'), true, 'final navigation must own startup readiness');
});

test('V417 sidebar owner cannot return after sidebar cleanup moved to final navigation', () => {
  assert.equal(app.includes('baseSetPage417'), false, 'classic V417 sidebar owner must remain retired');
  assert.equal(navigation.includes('beforeInvokeNavigation'), true, 'final navigation must retain the sidebar cleanup hook');
});
