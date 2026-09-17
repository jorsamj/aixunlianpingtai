import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function sliceFrom(startToken, endToken) {
  const start = app.indexOf(startToken);
  assert.ok(start >= 0, `missing ${startToken}`);
  const end = app.indexOf(endToken, start + startToken.length);
  assert.ok(end > start, `missing end token ${endToken}`);
  return app.slice(start, end);
}

const modelDelete = sliceFrom('window.deleteModelConfigV35=async function(id){', 'window.testModelConfigV35=async function(id)');
const promptSave = sliceFrom("window.savePromptTemplateV35=async function(id=''){", 'window.deletePromptTemplateV35=async function(id)');
const promptDelete = sliceFrom('window.deletePromptTemplateV35=async function(id){', '// ---------- Auto labeling ----------');

test('live model-config delete owns a local state removal with no global refresh', () => {
  assert.match(modelDelete, /method:'DELETE'/);
  assert.match(modelDelete, /state\.modelConfigs=.*filter/);
  assert.equal(modelDelete.includes('loadAll()'), false);
  assert.equal(modelDelete.includes('loadRelated()'), false);
});

test('live prompt save uses authoritative mutation result and local upsert', () => {
  assert.match(promptSave, /const item=await safe\(api/);
  assert.match(promptSave, /state\.promptTemplates/);
  assert.match(promptSave, /findIndex/);
  assert.equal(promptSave.includes('loadAll()'), false);
  assert.equal(promptSave.includes('loadRelated()'), false);
});

test('live prompt delete owns a local state removal with no global refresh', () => {
  assert.match(promptDelete, /method:'DELETE'/);
  assert.match(promptDelete, /state\.promptTemplates=.*filter/);
  assert.equal(promptDelete.includes('loadAll()'), false);
  assert.equal(promptDelete.includes('loadRelated()'), false);
});

test('final model configuration renderer still reaches the migrated mutation owners', () => {
  const finalRenderer = app.slice(app.lastIndexOf('window.renderModelConfigPageV35=function()'));
  assert.match(finalRenderer, /deleteModelConfigV35/);
  assert.equal(app.includes('onclick="savePromptTemplateV35('), true);
  assert.equal(app.includes('onclick="deletePromptTemplateV35('), true);
});
