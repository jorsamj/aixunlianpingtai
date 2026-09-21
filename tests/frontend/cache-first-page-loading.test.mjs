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
  const startup = block('window.__clInit=function()', 'const oldTop=renderTop');
  assert.doesNotMatch(startup, /await window\.refreshCurrentPage413/);
  assert.match(startup, /state\.uiReady=true;render\(\)/);
});

test('extras do not duplicate jobs or model configs already carried by snapshot', () => {
  const extras = block('async function extras412', 'window.loadPageExtras413=extras412');
  assert.doesNotMatch(extras, /\/jobs/);
  assert.doesNotMatch(extras, /modelConfigs|model-configs/);
});
