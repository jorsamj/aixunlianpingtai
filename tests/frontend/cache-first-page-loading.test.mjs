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
