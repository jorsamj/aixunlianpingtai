import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('final AI annotation owner uses durable v60 candidate review flow', () => {
  const legacyV33 = source.lastIndexOf('/api/v33/projects/${pid()}/prelabel-tasks');
  const legacyV35 = source.lastIndexOf('/api/v35/projects/${pid()}/prelabel-tasks');
  const finalSubmit = source.lastIndexOf('window.submitAiLabel429=async function(ids=[])');
  assert.ok(finalSubmit > legacyV33, 'final submit owner must load after v33 compatibility code');
  assert.ok(finalSubmit > legacyV35, 'final submit owner must load after v35 compatibility code');

  const submitEnd = source.indexOf('\n\n  function taskRow', finalSubmit);
  assert.ok(submitEnd > finalSubmit, 'final v60 submit block must remain bounded');
  const finalSubmitBody = source.slice(finalSubmit, submitEnd);
  assert.match(finalSubmitBody, /const task=await api\(taskApi\(\),/);
  assert.doesNotMatch(finalSubmitBody, /\/api\/v3[35]\/projects/);

  const finalRender = source.lastIndexOf('window.renderOps427=async function()');
  const legacyRender = source.lastIndexOf('window.renderAutoLabel422=async function()');
  assert.ok(finalRender > legacyRender, 'v60 task list must remain the final auto-label page owner');
  assert.match(source.slice(finalRender), /AI自动标注/);
  assert.match(source.slice(finalRender), /候选结果不会自动写入正式标注/);
});

test('final label management page owner is the alias-aware schema manager', () => {
  const legacyManager = source.lastIndexOf('window.manageLabels=');
  const finalRoute = source.lastIndexOf(
    "if(state.page==='标签管理'){renderNav();renderTop();renderSummary();renderLabelManagement414();return}"
  );
  assert.ok(finalRoute > legacyManager, 'final 标签管理 route must bypass the legacy modal manager');
  assert.match(source, /id="label414Aliases"/);
  assert.match(source, /自动预选后仍需人工确认/);
});
