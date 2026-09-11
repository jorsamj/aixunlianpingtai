import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('fully shadowed v42.9 render wrapper cannot return', () => {
  assert.equal(app.includes('oldRender429'), false);
  assert.equal(
    app.includes("render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='数据集'){renderNav();renderTop();renderSummary();renderDatasets424();return}oldRender429()};"),
    false,
  );
});

test('later stable renderer remains the algorithm/data routing owner', () => {
  assert.equal(app.includes('const oldRender412=render;'), true);
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
});
