import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('historical render assignment chain is physically retired', () => {
  assert.doesNotMatch(app, /\brender\s*=\s*function\b/);
});

test('historical render-chain aliases are physically retired', () => {
  for (const token of [
    'oldRenderV39', 'oldRender42', 'render422Base', 'renderBase424',
    'renderBase427', 'renderBase428', 'oldRender412', 'render414Base', 'finalRender',
    'oldEnsureWorkspace', 'oldDashboard42',
  ]) assert.equal(app.includes(token), false, token);
});

test('algorithm and dataset navigation are canonical owners', () => {
  assert.match(main, /registerPageOwner\('算法列表'/);
  assert.match(main, /registerPageOwner\('数据集'/);
});

test('shadowed v424 and v425 training-task renderers are physically retired', () => {
  assert.equal(app.includes('window.renderTraining424=function(){'), false);
  assert.equal(app.includes('window.renderTraining424=window.renderTraining425=function(){'), false);
  assert.match(app, /window\.renderTraining425=window\.renderTraining424=window\.renderTraining423=function\(\)/);
});

test('training navigation is a canonical owner', () => {
  assert.match(main, /registerPageOwner\('训练任务'/);
  assert.match(app, /window\.renderTraining425=window\.renderTraining424=window\.renderTraining423=function\(\)/);
});

test('auto-label cleanup navigation is a canonical owner', () => {
  assert.match(main, /registerPageOwner\('自动标注及清洗'/);
  assert.doesNotMatch(app, /state\.page==='自动标注'\).*renderAutoLabel/);
});


test('auto-label and cleaning tabs dispatch to direct owners without previous renderer capture', () => {
  assert.match(app, /window\.renderCleanOps427=renderCleanOps427/);
  assert.match(app, /return window\.renderCleanOps427\?\.\(\)/);
  assert.equal(app.includes('const previousRenderOps=window.renderOps427;'), false);
  assert.equal(app.includes('return previousRenderOps?.()'), false);
});


test('shadowed storage dataset renderer is physically retired', () => {
  assert.equal(app.includes('const previousDatasetRender61=window.renderDatasets424;'), false);
  assert.equal(app.includes('const _baseRenderDatasetsV33=renderDatasets;'), false);
  assert.equal(app.includes('autoLabelBtnV33'), false);
});

test('dataset keeps one physical page renderer owner', () => {
  assert.equal((app.match(/window\.renderDatasets424\s*=\s*function/g) || []).length, 1);
  assert.match(app, /function datasetScope412\(\)/);
});

test('dataset usability layer installs a decoration hook instead of wrapping the canonical renderer', () => {
  assert.equal(app.includes('const baseRenderDataset417=window.renderDatasets424;'), false);
  assert.match(app, /window\.decorateDatasetUsability417=function\(\)/);
  const start = app.indexOf('function datasetScope412()');
  const end = app.indexOf('window.setData412Tab=', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /window\.decorateDatasetUsability417\?\.\(\)/);
});

test('dataset label controls are a direct decoration hook instead of renderer layers', () => {
  assert.equal(app.includes('const baseData414=window.renderDatasets424;'), false);
  assert.equal(app.includes('const baseRenderDatasets427=window.renderDatasets424;'), false);
  assert.match(app, /window\.decorateDatasetControls414=function\(\)/);
  const start = app.indexOf('function datasetScope412()');
  const end = app.indexOf('window.setData412Tab=', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /window\.decorateDatasetControls414\?\.\(\)/);
});

test('dataset storage and feedback filters live in the canonical v412 data query and owner', () => {
  assert.equal(app.includes('const finalDataset=window.renderDatasets424;'), false);
  const start = app.indexOf('function datasetScope412()');
  const end = app.indexOf('window.setData412Tab=', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /state\.materialSourceFilter61/);
  assert.match(owner, /state\.iterationFeedbackOnly63&&feedbackIds\.size/);
  assert.match(owner, /window\.dataRows412=dataRows412/);
  assert.match(owner, /id="materialSource61"/);
  assert.match(owner, /storage61-badge/);
  assert.match(owner, /window\.decorateDatasetControls414\?\.\(\)/);
  assert.match(owner, /window\.renderSupplementDataBanner63\?\.\(\)/);
});

test('dataset feedback banner is a post-render hook instead of another renderer wrapper', () => {
  assert.match(app, /window\.renderSupplementDataBanner63=renderSupplementDataBanner63/);
  assert.match(app, /window\.renderSupplementDataBanner63\?\.\(\)/);
  assert.match(app, /state\.iterationFeedbackOnly63&&feedbackIds\.size/);
  assert.match(app, /feedbackIds\.has\(String\(row\.id\)\)/);
  assert.equal(app.includes('const datasetRenderFeedback63=window.renderDatasets424;'), false);
});

test('video navigation is a canonical owner', () => {
  assert.match(main, /registerPageOwner\('视频切帧'/);
});

test('quality-center navigation is a canonical window owner', () => {
  assert.match(main, /\['质量中心', 'renderQualityCenter424'\]/);
});

test('material-source navigation no longer depends on a legacy wrapper', () => {
  assert.match(main, /\['素材接入', 'renderSources422'\]/);
});

test('storage navigation is a canonical owner', () => {
  assert.match(main, /\['存储配置', 'renderStorageSources61'\]/);
  assert.equal(app.includes('const previousNav61=renderNav;'), false);
  assert.equal(app.includes('data-storage-nav="1"'), false);
});

test('deployment pages are canonical owners', () => {
  for (const [page, renderer] of [
    ['部署转换', 'renderDeployCenter'],
    ['部署产物', 'renderDeployArtifacts'],
    ['部署资源', 'renderDeployResources'],
    ['部署插件', 'renderDeployPluginsV41'],
  ]) assert.ok(main.includes(`['${page}', '${renderer}']`));
});

test('test and detection pages are canonical owners', () => {
  assert.match(main, /\['测试发布', 'renderTest'\]/);
  assert.match(main, /\['检测台', 'renderDetectBench'\]/);
});

test('shadowed test and detection page renderers are physically retired', () => {
  assert.equal(app.includes('window.renderDetectBench = function(){'), false);
  assert.equal(app.includes('renderTest = window.renderTest = function(){'), false);
  assert.match(app, /renderDetectBench = window\.renderDetectBench = function\(\)/);
  assert.match(app, /renderTest=window\.renderTest=function renderTestCanonical63\(\)/);
});

test('detection result rendering uses an explicit core helper and one final owner', () => {
  assert.match(app, /window\.renderDetectionResultCore31 = function renderDetectionResultCore31\(r,title\)/);
  assert.match(app, /window\.renderDetectionResult=window\.renderDetectionResultCore31/);
  assert.match(app, /window\.renderDetectionResult=function renderDetectionResultCanonical61\(result,title\)/);
  assert.match(app, /window\.renderDetectionResultCore31\?\.\(result,title\)/);
  assert.equal(app.includes('const oldRenderDetectionResult = window.renderDetectionResult;'), false);
  assert.equal(app.includes('const previousResult=window.renderDetectionResult;'), false);
});


test('test publish page resolves through a named core helper and one canonical final owner', () => {
  assert.match(app, /window\.renderTestCore30=function renderTestCore30\(\)/);
  assert.match(app, /renderTest=window\.renderTest=function renderTestCanonical63\(\)/);
  assert.match(app, /window\.renderTestCore30\?\.\(\)/);
  assert.equal(app.includes('const oldRenderTest = window.renderTest;'), false);
  assert.equal(app.includes('const previousRenderTest63=renderTest;'), false);
  assert.equal(app.includes('previousRenderTest63();'), false);
});

test('shadowed model-config page owner and v35 render map are physically retired', () => {
  assert.equal(app.includes('const v35RenderMap=()=>({'), false);
  assert.equal((app.match(/window\.renderModelConfigPageV35\s*=\s*function/g) || []).length, 1);
  assert.doesNotMatch(app, /request_mode\|\|'json_base64'.*renderModelConfigPageV35/s);
});

test('configuration pages are canonical owners', () => {
  assert.match(main, /\['标签管理', 'renderLabelManagement414'\]/);
  assert.match(main, /\['模型配置', 'renderModelConfigPageV35'\]/);
  assert.match(main, /\['训练资源', 'renderResources'\]/);
});


test('shadowed training-resource page renderers are physically retired', () => {
  assert.equal((app.match(/\bfunction renderResources\(\)\s*\{/g) || []).length, 1);
  assert.match(app, /window\.renderResourceBasePage=renderResources/);
});

test('training resource page composes an explicit base owner instead of wrapping the previous renderer', () => {
  assert.match(app, /window\.renderResourceBasePage=renderResources/);
  assert.equal(app.includes('previousRenderResources'), false);
});

test('platform and component pages keep dedicated owners', () => {
  assert.match(main, /registerPageOwner\('平台对接'/);
  assert.match(main, /registerPageOwner\('组件检测'/);
});

test('service-node runtime owns its page directly', () => {
  assert.match(main, /installServiceNodeRuntime\(\{notify\}\)/);
});

test('post-render normalization moved out of the legacy wrapper chain', () => {
  assert.equal(app.includes("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))"), false);
  assert.match(main, /PostRenderNormalizationRuntime\?\.apply\?\./);
});

test('active global render calls route through the canonical bridge', () => {
  assert.match(main, /function renderCanonicalOwner\(page/);
  assert.match(main, /window\.render = function canonicalRenderBridge\(\)/);
  assert.match(main, /source: 'compat-render'/);
  assert.match(main, /source: 'startup-owner'/);
});

test('canonical page map is the single normal navigation registry', () => {
  assert.match(main, /const canonicalWindowPageRenderers = new Map/);
  assert.match(main, /navigationStabilityRuntime\.registerPageOwner\(page/);
  assert.doesNotMatch(app, /Final route override|Final routing: do not fall back|route \+ page alias/);
});


test('navigation chrome resolves to direct final owners without wrapper chaining', () => {
  assert.match(app, /renderTop=function renderTopCanonical413\(\)/);
  for (const token of ['oldRenderTopV36', 'oldTop42', 'baseTop=renderTop', 'top422=renderTop', 'baseTop424=renderTop', 'nav426=renderNav', 'top426=renderTop', 'top412=renderTop']) {
    assert.equal(app.includes(token), false, token);
  }
  assert.equal(app.includes("const oldTop=renderTop;renderTop=function(){oldTop();const v=document.getElementById('versionBadge')"), false);
  assert.equal(app.includes('const finalNav=renderNav;'), false);

  const navStart = app.indexOf('const icon414=');
  const navEnd = app.indexOf('window.renderLabelManagement414=', navStart);
  assert.ok(navStart >= 0 && navEnd > navStart);
  const finalNavOwner = app.slice(navStart, navEnd);
  assert.match(finalNavOwner, /存储配置:'▣'/);
  assert.match(finalNavOwner, /\{title:'资源配置',items:\['模型配置','训练资源','部署资源','存储配置'\]\}/);
});
