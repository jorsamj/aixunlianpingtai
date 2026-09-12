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

test('renderBase428 keeps only its live training route branch', () => {
  assert.equal(
    app.includes("render=function(){if(state.page==='算法列表'){renderNav();renderTop();renderSummary();renderAlgorithms423();return}if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    false,
  );
  assert.equal(
    app.includes("render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    true,
  );
});

test('oldRender412 remains the sole outer algorithm-list route owner', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
});

test('legacy auto-label render route owners cannot return', () => {
  assert.equal(
    app.includes("if(state.page==='自动标注'){renderNav();renderTop();renderSummary();renderAutoLabel422();return}"),
    false,
  );
  assert.equal(
    app.includes("if(state.page==='自动标注'){renderAutoLabel424();return}"),
    false,
  );
});

test('canonical auto-label cleanup render route remains live', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}"),
    true,
  );
});

test('shadowed renderBase424 algorithm/data/training branches cannot return', () => {
  const retired = `  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='数据集'){renderDatasets424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    if(state.page==='训练任务'){renderTraining424();return}
    // v42.3 pages retain their own final implementations
    if(state.page==='算法列表'){renderAlgorithms423();return}
    // call previous render for deploy/test/config pages, but it will redraw nav/top; acceptable
    renderBase424();
  };`;
  assert.equal(app.includes(retired), false);
});

test('renderBase424 keeps only its live quality and video route branches', () => {
  const live = `  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    // algorithm/data/training routes are owned by later stable wrappers.
    renderBase424();
  };`;
  assert.equal(app.includes(live), true);
  assert.equal(app.includes("if(state.page==='质量中心'){renderQualityCenter424();return}"), true);
  assert.equal(app.includes("if(state.page==='视频切帧'){renderVideo424();return}"), true);
});

test('later owners remain authoritative for renderBase424 retired routes', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};"),
    true,
  );
  assert.equal(
    app.includes("render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};"),
    true,
  );
});

test('legacy AutoLabel424 self-refresh timer cannot return', () => {
  assert.equal(
    app.includes("if(state.prelabel424.some(t=>['queued','running'].includes(t.status)))setTimeout(()=>{if(state.page==='自动标注')renderAutoLabel424()},1800)"),
    false,
  );
  assert.equal(app.includes("state.page==='自动标注'"), false);
});

test('canonical AutoLabel render route remains the only page-state route', () => {
  assert.equal(
    app.includes("render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()}"),
    true,
  );
});
