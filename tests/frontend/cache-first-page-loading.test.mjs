import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

function block(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.notEqual(from, -1, `missing start marker: ${start}`);
  assert.notEqual(to, -1, `missing end marker: ${end}`);
  return source.slice(from, to);
}

test('ordinary core loading uses cached snapshot and explicit refresh owns refresh=true', () => {
  const core = block('window.loadCore412=async function', 'async function pollAnnotationIndex412');
  assert.match(core, /window\.loadCore412=async function\(\{authoritative=false\}=\{\}\)/);
  assert.match(core, /snapshot\$\{authoritative\?'\?refresh=true':''\}/);
  assert.doesNotMatch(core, /preferred_project_id/);
  assert.doesNotMatch(core, /snapshot\?refresh=true/);
  assert.match(source, /loadCore412\(\{authoritative:true\}\)/);
  assert.match(core, /state\.modelConfigs=snapshot\.model_configs\|\|\[\]/);
});

test('startup paints cached snapshot without awaiting a second broad refresh', () => {
  const startup = block('window.__clInit=function()', 'const TOP_CRUMB413=Object.freeze');
  assert.doesNotMatch(startup, /await window\.refreshCurrentPage413/);
  assert.match(startup, /state\.uiReady=true;render\(\);state\.__startupCanonicalPainted=true/);
});

test('extras do not duplicate jobs or model configs already carried by snapshot', () => {
  const extras = block('async function extras412', 'window.loadPageExtras413=extras412');
  assert.doesNotMatch(extras, /\/jobs/);
  assert.doesNotMatch(extras, /modelConfigs|model-configs/);
});


test('frequently revisited operational pages paint before focused revalidation', () => {
  const sources = block('window.renderSources422=function()', '\n  window.refreshSources422=refreshSources422;');
  assert.doesNotMatch(sources, /async function\(\)\{await loadSourcesOnly422/);
  assert.ok(sources.indexOf("document.getElementById('view').innerHTML") < sources.indexOf('loadSourcesOnly422()'));
  assert.match(sources, /SOURCE422_CACHE_TTL_MS/);

  const video = block('window.renderVideo424=function()', '\n  window.createVideoTask424=function()');
  assert.ok(video.indexOf("document.getElementById('view').innerHTML") < video.indexOf('refreshVideo424Delta()'));
  assert.match(video, /data-video-loading/);
  assert.match(source, /const VIDEO424_PAGE_ENTRY_REUSE_MS=5000/);
  assert.match(video, /reuseRecent=hasSnapshot&&age>=0&&age<VIDEO424_PAGE_ENTRY_REUSE_MS/);
  assert.match(video, /if\(!reuseRecent\)void window\.refreshVideo424Delta\(\)/);

  const finalAutoStart = source.lastIndexOf('window.renderOps427=function()');
  const finalAutoEnd = source.indexOf('\n\n  function candidateOverlay', finalAutoStart);
  assert.ok(finalAutoStart >= 0 && finalAutoEnd > finalAutoStart);
  const finalAuto = source.slice(finalAutoStart, finalAutoEnd);
  assert.match(finalAuto, /renderAiTaskPage60\(\{loading:!hasSnapshot\}\)/);
  assert.ok(finalAuto.indexOf('renderAiTaskPage60') < finalAuto.indexOf('refreshAnnotationTasks60()'));
  assert.match(source, /const AI_TASK_PAGE_ENTRY_REUSE_MS=5000/);
  assert.match(finalAuto, /if\(hasSnapshot&&age>=0&&age<AI_TASK_PAGE_ENTRY_REUSE_MS\)return/);

  const clean = block('function renderCleanOps427()', '\n\n  // ----- model config: prompt lives with model -----');
  assert.match(clean, /document\.getElementById\('view'\)\.innerHTML/);
  assert.match(clean, /refreshCleanOps427Delta/);
  assert.match(source, /const CLEAN427_PAGE_ENTRY_REUSE_MS=5000/);
  assert.match(clean, /reuseRecent=state\.clean427LoadedAt>0&&age>=0&&age<CLEAN427_PAGE_ENTRY_REUSE_MS/);
  assert.match(clean, /if\(!reuseRecent\)void window\.refreshCleanOps427Delta\?\.\(\)/);
  assert.doesNotMatch(clean, /await loadOps427\(\)/);
});


test('clean task focused refresh dedupes inflight reads and records a reusable snapshot', () => {
  const refresh = block('window.refreshCleanOps427Delta=function()', '\n  function renderCleanOps427()');
  assert.match(refresh, /if\(state\.clean427RefreshPromise\)return state\.clean427RefreshPromise/);
  assert.match(refresh, /state\.clean427LoadedAt=Date\.now\(\)/);
  assert.match(refresh, /state\.clean427RefreshPromise=task/);
  assert.match(refresh, /state\.clean427RefreshPromise===task/);
});


test('test publish feedback panel paints cached rows before TTL revalidation', () => {
  assert.match(source, /const ONLINE_FEEDBACK_CACHE_TTL_MS=60\*1000/);
  assert.match(source, /state\.onlineFeedback63ProjectId===feedbackProjectId&&state\.onlineFeedback63LoadedAt>0/);
  assert.match(source, /const feedbackRows=hasFeedbackSnapshot\?feedbackRows63\(\):/);
  assert.match(source, /loadOnlineFeedback63\(\{force:true\}\)">刷新/);
  assert.match(source, /if\(!hasFeedbackSnapshot\|\|feedbackAge<0\|\|feedbackAge>=ONLINE_FEEDBACK_CACHE_TTL_MS\)void loadOnlineFeedback63\(\)/);
  assert.match(source, /if\(!force&&sameProject&&state\.onlineFeedback63LoadedAt>0&&age>=0&&age<ONLINE_FEEDBACK_CACHE_TTL_MS\)/);
  assert.match(source, /state\.onlineFeedback63RefreshPromise&&state\.onlineFeedback63RefreshProjectId===projectId/);
});


test('test publish manual refresh is page-scoped instead of using broad loadAll', () => {
  const testStart = source.indexOf('window.renderTestCore30=function renderTestCore30()');
  const testEnd = source.indexOf('window.renderTestLegacy30=window.renderTestCore30;', testStart);
  assert.ok(testStart >= 0 && testEnd > testStart);
  const testPage = source.slice(testStart, testEnd);
  assert.match(testPage, /onclick="refreshTestPageDataV3\(\)">刷新环境\/模型<\/button>/);
  assert.doesNotMatch(testPage, /loadAll\(\)\.then\(render\)/);

  const refreshStart = source.indexOf('window.refreshTestPageDataV3=async function()');
  const refreshEnd = source.indexOf('\n  window.refreshCurrentPage413=', refreshStart);
  assert.ok(refreshStart >= 0 && refreshEnd > refreshStart);
  const refresh = source.slice(refreshStart, refreshEnd);
  assert.match(refresh, /await extras412\('测试发布'\)/);
  assert.match(refresh, /state\.page===page&&page==='测试发布'/);
  assert.doesNotMatch(refresh, /loadAll\(/);
  assert.doesNotMatch(refresh, /loadCore412\(/);
  assert.doesNotMatch(refresh, /loadRelated\(/);
});


test('detection bench receives focused model and inference extras on navigation and manual refresh', () => {
  assert.match(main, /PAGE_EXTRAS_OWNERS = new Set\([^\n]+检测台/);

  const extras = block('async function extras412', 'window.loadPageExtras413=extras412');
  assert.match(extras, /\['测试发布','部署测试','检测台'\]\.includes\(page\)/);
  assert.match(extras, /\/api\/v12\/projects\/\$\{id\}\/test_models/);
  assert.match(extras, /\/api\/v16\/inference_envs/);

  const benchStart = source.indexOf('renderDetectBench = window.renderDetectBench = function()');
  const benchEnd = source.indexOf('\n  window.predictCore30 = async function()', benchStart);
  assert.ok(benchStart >= 0 && benchEnd > benchStart);
  const bench = source.slice(benchStart, benchEnd);
  assert.match(bench, /onclick="refreshDetectionBenchDataV3\(\)">刷新模型\/环境<\/button>/);
  assert.doesNotMatch(bench, /loadAll\(\)\.then\(render\)/);

  const refreshStart = source.indexOf('window.refreshDetectionBenchDataV3=async function()');
  const refreshEnd = source.indexOf('\n  window.refreshCurrentPage413=', refreshStart);
  assert.ok(refreshStart >= 0 && refreshEnd > refreshStart);
  const refresh = source.slice(refreshStart, refreshEnd);
  assert.match(refresh, /await extras412\('检测台'\)/);
  assert.match(refresh, /window\.renderDetectBench\?\.\(\)/);
  assert.doesNotMatch(refresh, /loadAll\(/);
  assert.doesNotMatch(refresh, /loadCore412\(/);
  assert.doesNotMatch(refresh, /loadRelated\(/);
});


test('training page revisit paints cached jobs before a non-forced focused revalidation', () => {
  const start = main.indexOf('function refreshCurrentPageOwner(page)');
  const end = main.indexOf('const navigationStabilityRuntime', start);
  assert.ok(start >= 0 && end > start);
  const owner = main.slice(start, end);
  assert.match(owner, /trainingTaskRuntime\.refresh\(\{render: true, force: false, source: 'page-owner'\}\)/);
  assert.doesNotMatch(owner, /trainingTaskRuntime\.refresh\(\{render: true, force: true, source: 'page-owner'\}\)/);
});


test('normal navigation is synchronous once startup data is ready', () => {
  const start = main.indexOf('waitForNavigationReady: () => {');
  const end = main.indexOf('\n  beforeInvokeNavigation:', start);
  assert.ok(start >= 0 && end > start);
  const readiness = main.slice(start, end);
  assert.match(readiness, /if \(!state\.uiReady && window\.__v53InitPromise\) return window\.__v53InitPromise/);
  assert.match(readiness, /return null/);
  assert.doesNotMatch(readiness, /async|await/);
});


test('ordinary page navigation patches chrome state without rebuilding the sidebar', () => {
  const start = main.indexOf('function renderNavigationChrome()');
  const end = main.indexOf('\n\nfunction applyPostRenderNormalization', start);
  assert.ok(start >= 0 && end > start);
  const chrome = main.slice(start, end);
  assert.match(chrome, /querySelectorAll\('\.nav-btn'\)/);
  assert.match(chrome, /classList\.toggle\('active', label === currentPage\)/);
  assert.match(chrome, /nav\.querySelector\('\.nav-project-v'\)/);
  assert.match(chrome, /if \(!nav \|\| !buttons\.length\)/);
  assert.equal((chrome.match(/window\.renderNav\?\.\(\)/g) || []).length, 1);
});
