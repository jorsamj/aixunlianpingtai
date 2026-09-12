import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('enhancePageV37 compatibility helper cannot return', () => {
  assert.equal(app.includes('function enhancePageV37'), false);
  assert.equal(app.includes('requestAnimationFrame(enhancePageV37)'), false);
  assert.equal(app.includes('enhancePageV37();const first='), false);
});

test('cleanup owns table wrapping and 使用建议 cleanup semantics', () => {
  assert.equal(app.includes("if(root.matches?.('table.table'))wrapTable(root);"), true);
  assert.equal(app.includes("root.querySelectorAll('table.table').forEach(wrapTable);"), true);
  assert.equal(app.includes("['接入方式','系统原则','一条主流程','快速入口','使用建议'].includes(t)"), true);
});

test('V37 wrappers retain only still-live non-normalization semantics', () => {
  assert.equal(app.includes('const baseRenderV37=render;'), true);
  assert.equal(app.includes("render=function(){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};baseRenderV37()};"), true);
  assert.equal(app.includes('const baseModalV37=modal;'), true);
  assert.equal(app.includes("requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})"), true);
});
