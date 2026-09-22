import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

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
  assert.match(startup, /state\.uiReady=true;render\(\)/);
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

  const finalAutoStart = source.lastIndexOf('window.renderOps427=function()');
  const finalAutoEnd = source.indexOf('\n\n  function candidateOverlay', finalAutoStart);
  assert.ok(finalAutoStart >= 0 && finalAutoEnd > finalAutoStart);
  const finalAuto = source.slice(finalAutoStart, finalAutoEnd);
  assert.match(finalAuto, /renderAiTaskPage60\(\{loading:!hasSnapshot\}\)/);
  assert.ok(finalAuto.indexOf('renderAiTaskPage60') < finalAuto.indexOf('refreshAnnotationTasks60()'));

  const clean = block('function renderCleanOps427()', '\n\n  // ----- model config: prompt lives with model -----');
  assert.match(clean, /document\.getElementById\('view'\)\.innerHTML/);
  assert.match(clean, /refreshCleanOps427Delta/);
  assert.doesNotMatch(clean, /await loadOps427\(\)/);
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
  const testEnd = source.indexOf('window.renderTest=window.renderTestCore30;', testStart);
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
