import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('annotation and cleaning task details use direct canonical routing', () => {
  assert.equal((app.match(/window\.showTaskProgress427=/g) || []).length, 1);
  for (const token of [
    'const showTaskBase429=window.showTaskProgress427;',
    'const previousShowTask=window.showTaskProgress427;',
  ]) assert.equal(app.includes(token), false, token);
  assert.match(app, /window\.showTaskProgressCore427=async function\(type,id\)/);
  assert.match(app, /window\.showCleanTaskProgress429=async function\(id\)/);
  assert.match(app, /window\.showTaskProgress427=function showTaskProgressCanonical60\(type,id\)/);
});

test('cleaning result detail uses explicit core and one public owner', () => {
  assert.equal(app.includes('const baseCleanDetail412=window.cleanDetail429;'), false);
  assert.equal((app.match(/window\.cleanDetail429=/g) || []).length, 1);
  assert.match(app, /window\.cleanDetailCore429=async function\(id\)/);
  assert.match(app, /window\.decorateCleanDetailSelection412=function\(\)/);
  assert.match(app, /window\.cleanDetail429=async function cleanDetailCanonical429\(id\)/);
});

test('v60 AI tasks never fall through the legacy v47 progress modal', () => {
  const start = app.lastIndexOf('Persistent v60 AI annotation UI');
  const block = app.slice(start);
  assert.match(block, /if\(type==='label'\)return showAiTask60\(id\)/);
  assert.match(block, /if\(type==='clean'\)return window\.showCleanTaskProgress429\?\.\(id\)/);
});


test('canonical AI creation selects a saved model config and never exposes a temporary detect URL', () => {
  const createStart = app.indexOf('window.createAiLabelCore429=function');
  const createEnd = app.indexOf('// ---------- training from processed', createStart);
  assert.ok(createStart >= 0 && createEnd > createStart);
  const createBlock = app.slice(createStart, createEnd);
  assert.match(createBlock, /id="ai429Model"/);
  assert.match(createBlock, /任务创建时冻结/);
  assert.match(createBlock, /不支持临时检测接口/);
  assert.doesNotMatch(createBlock, /id="preUrl"|id="preModelCfg"/);

  const submitStart = app.indexOf('window.submitAiLabel429=async function');
  const submitEnd = app.indexOf('function taskRow', submitStart);
  const submitBlock = app.slice(submitStart, submitEnd);
  assert.match(submitBlock, /getElementById\('ai429Model'\)/);
  assert.match(submitBlock, /model_config_id:modelConfigId/);
  assert.doesNotMatch(submitBlock, /find\(item=>item\.default_for_annotation\)/);
});

test('legacy v35 auto-label modal delegates to the v60 CandidateStore flow', () => {
  const start = app.indexOf('window.openAutoLabelModal=async function');
  const end = app.indexOf('window.applyPrePromptTplV35=function', start);
  assert.ok(start >= 0 && end > start);
  const block = app.slice(start, end);
  assert.match(block, /window\.createAiLabel429/);
  assert.doesNotMatch(block, /id="preUrl"|id="preModelCfg"/);
});
