import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('pre-v42.4 severed setPage wrappers cannot return', () => {
  for (const token of ['oldSetV39', 'oldSet42', 'set422Base']) {
    assert.equal(app.includes(token), false, `${token} must remain retired`);
  }
});

test('later navigation owners remain after pre-v42.4 cleanup', () => {
  assert.equal(
    app.includes('window.setPage=function(p){state.page=p;render()};try{setPage=window.setPage}catch(e){}'),
    true,
    'v42.4 direct reset must remain',
  );
  assert.equal(app.includes('const setPageReady414=window.setPage;'), true, 'startup readiness owner must remain');
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true, 'V417 sidebar owner must remain');
  assert.equal(
    app.includes("window.setPage=function(p){state.page=p==='自动标注'?'自动标注及清洗':p;render()};"),
    true,
    'later auto-label route owner must remain',
  );
});
