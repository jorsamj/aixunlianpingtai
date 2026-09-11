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

test('shadowed early storage render wrapper cannot return', () => {
  assert.equal(app.includes('previousRender61'), false);
  assert.equal(
    app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}previousRender61()};"),
    false,
  );
});

test('final storage render owner remains the sole storage route wrapper', () => {
  assert.equal(app.includes('const finalRender=render;'), true);
  assert.equal(
    app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61();return}finalRender()};"),
    true,
  );
});

test('fully shadowed render423 route wrapper cannot return', () => {
  assert.equal(app.includes('render423Base'), false);
  assert.equal(
    app.includes("if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();return}"),
    false,
  );
});

test('later algorithm/training owners and direct training polling remain', () => {
  assert.equal(app.includes('const renderBase428=render;'), true);
  assert.equal(app.includes('const oldRender412=render;'), true);
  assert.equal(app.includes('window.renderTraining425=window.renderTraining424=window.renderTraining423=function()'), true);
  assert.equal(app.includes('window.PollRegistryRuntime?.replaceTrainingJobTimer?.()};'), true);
});
