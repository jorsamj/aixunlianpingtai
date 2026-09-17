import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('historical auto-label page alias is canonicalized at restore boundary', () => {
  assert.equal(
    app.includes("const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;"),
    true,
  );
  assert.equal(
    app.includes("if(restoredPage && (RENDER_MAP()[restoredPage]||restoredPage==='自动标注及清洗')) state.page=restoredPage;"),
    true,
  );
});

test('render chain cannot mutate legacy auto-label route state', () => {
  assert.equal(
    app.includes("if(state.page==='自动标注')state.page='自动标注及清洗'"),
    false,
  );
});
