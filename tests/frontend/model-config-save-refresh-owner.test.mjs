import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('static/app.js', 'utf8');
const saveStartMarker = "  window.saveVisionModelM4=async function(id=''){";
const saveEndMarker = '\n  window.testModelConfigV35=async function(id){';
const saveStart = app.indexOf(saveStartMarker);
const saveEnd = app.indexOf(saveEndMarker, saveStart);
assert.ok(saveStart >= 0 && saveEnd > saveStart, 'live saveVisionModelM4 owner must remain addressable');
const owner = app.slice(saveStart, saveEnd);

test('live model config save owner uses authoritative mutation result without broad related refresh', () => {
  assert.equal((app.match(/window\.saveVisionModelM4=async function/g) || []).length, 1);
  assert.match(owner, /const saved=await api\(/);
  assert.match(owner, /if\(saved\?\.id\)/);
  assert.match(owner, /state\.modelConfigs=i>=0\?rows\.map\(\(x,n\)=>n===i\?saved:x\):\[saved,\.\.\.rows\]/);
  assert.doesNotMatch(owner, /loadRelated\s*\(/);
  assert.doesNotMatch(owner, /loadAll\s*\(/);
});

test('M4 captures the vision modal as the final model-config owner', () => {
  const m4Start = app.indexOf('M4: real vision providers, reviewable boxes, explicit targets');
  const m4Open = app.indexOf('window.openModelConfigModalV35=function', m4Start);
  const capture = app.indexOf('window.__m4OpenModelConfig=window.openModelConfigModalV35;', m4Open);
  assert.ok(m4Start >= 0 && m4Open > m4Start && capture > m4Open);
  const region = app.slice(m4Open, capture);
  assert.match(region, /onclick=\"saveVisionModelM4\('\$\{id\}'\)\"/);
});

test('M4 final activation restores the captured modal without any shadowed function owner', () => {
  const capture = app.indexOf('window.__m4OpenModelConfig=window.openModelConfigModalV35;');
  const activation = app.indexOf('M4 final activation: later compatibility layers must not replace these contracts.');
  const laterFunctionOwner = app.indexOf('window.openModelConfigModalV35=function', capture + 1);
  assert.ok(capture >= 0 && activation > capture);
  assert.equal(laterFunctionOwner, -1, 'retired compatibility modal generations must stay absent after the M4 capture');
  const activationRegion = app.slice(activation, activation + 1200);
  assert.match(activationRegion, /if\(window\.__m4OpenModelConfig\)window\.openModelConfigModalV35=window\.__m4OpenModelConfig/);
});
