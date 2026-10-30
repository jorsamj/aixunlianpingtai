import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8').replace(/\r\n/g, '\n');

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

  const finalPage = source.lastIndexOf('function renderAiTaskPage60');
  const finalRender = source.lastIndexOf('window.renderOps427=function()');
  const legacyRender = source.lastIndexOf('window.renderAutoLabel422=async function()');
  assert.ok(finalPage > legacyRender, 'v60 task shell must load after legacy auto-label pages');
  assert.ok(finalRender > finalPage, 'v60 task list must remain the final auto-label page owner');
  assert.match(source.slice(finalPage, finalRender), /AI自动标注/);
  assert.match(source.slice(finalRender), /候选结果不会自动写入正式标注/);
  assert.equal((source.match(/window\.showTaskProgress427=/g) || []).length, 1);
  assert.equal(source.includes('const showTaskBase429=window.showTaskProgress427;'), false);
  assert.equal(source.includes('const previousShowTask=window.showTaskProgress427;'), false);
  assert.match(source, /window\.showTaskProgressCore427=async function\(type,id\)/);
  assert.match(source, /window\.showCleanTaskProgress429=async function\(id\)/);
  assert.match(source, /window\.showTaskProgress427=function showTaskProgressCanonical60\(type,id\)/);
});

test('AI create dialog uses one canonical owner with explicit decorators', () => {
  assert.equal((source.match(/window\.createAiLabel429=/g) || []).length, 1);
  assert.equal((source.match(/window\.createAiLabel427=/g) || []).length, 1);
  assert.equal((source.match(/window\.aiRefSelect412=/g) || []).length, 1);
  for (const token of [
    'const baseCreateAi417=window.createAiLabel429;',
    'const baseCreateAi412=window.createAiLabel429;',
    'const baseSelectReference417=window.aiRefSelect412;',
  ]) assert.equal(source.includes(token), false, token);
  assert.match(source, /window\.createAiLabelCore429=function\(opts=\{\}\)/);
  assert.match(source, /window\.decorateAiReferenceLabels417=function\(\)/);
  assert.match(source, /window\.decorateAiReferenceBulk412=function\(\)/);
  assert.match(source, /window\.createAiLabel429=function createAiLabelCanonical429\(opts=\{\}\)/);
  const canonicalStart = source.indexOf('window.createAiLabel429=function createAiLabelCanonical429(opts={})');
  const canonicalEnd = source.indexOf('window.createAiLabel427=window.createAiLabel429;', canonicalStart);
  const canonical = source.slice(canonicalStart, canonicalEnd);
  assert.doesNotMatch(canonical, /ensureFullPool/);
  assert.match(canonical, /window\.createAiLabelCore429\?\.\(opts\)/);
  assert.match(canonical, /hydrateAiCreate429\?\.\(/);
  assert.match(source, /window\.aiRefSelect412=function aiRefSelectCanonical412\(mode\)/);
});

test('final label management page owner is the alias-aware schema manager', () => {
  assert.match(source, /window\.manageLabels=\(\)=>\{closeModal\(\);setPage\('标签管理'\)\};/);
  assert.doesNotMatch(source, /state\.page==='标签管理'.*renderLabelManagement414/);
  assert.match(main, /\['标签管理', 'renderLabelManagement414'\]/);
  assert.match(main, /navigationStabilityRuntime\.registerPageOwner\(page/);
  assert.match(source, /id="label414Aliases"/);
  assert.match(source, /不会用于导入时自动选择或推荐平台标签/);
});
test('AI review can explicitly create a canonical label but Ground Truth still commits through review mapping', () => {
  const reviewStart = source.lastIndexOf('function renderAiLabelMapping60()');
  const reviewEnd = source.indexOf('/* Persistent deployment tests:', reviewStart);
  assert.ok(reviewStart > 0 && reviewEnd > reviewStart);
  const review = source.slice(reviewStart, reviewEnd);
  assert.match(review, /openInlineLabelCreate414\('ai'/);
  assert.match(review, /const label_mapping=Object\.fromEntries/);
  assert.match(review, /\/decisions/);
  assert.doesNotMatch(review, /create_labels/);
  assert.match(source, /候选结果不会自动写入正式标注/);
});



test('retired AI submit compatibility entrypoint delegates to the v60 owner', () => {
  const marker = source.lastIndexOf('Persistent v60 AI annotation UI');
  const end = source.indexOf('/* Explicit canonical-label creation used by import/rescan/ZIP/AI confirmation.', marker);
  const finalLayer = source.slice(marker, end);
  assert.match(finalLayer, /window\.submitAiLabel427=\(ids=\[\]\)=>window\.submitAiLabel429\(ids\)/);
  assert.doesNotMatch(finalLayer, /\/api\/v47\/projects\/.*ai-label-tasks/);
  assert.match(finalLayer, /const task=await api\(taskApi\(\),/);
});


test('retired v47 AI review clients are absent from the production frontend', () => {
  assert.doesNotMatch(source, /\/api\/v47\/projects\/\$\{pid\(\)\}\/ai-label-tasks/);
  for (const token of [
    'reviewAiLabelLegacy427',
    'confirmAiLabelLegacy4271',
    'submitAiLabelLegacy429_1',
    'confirmAiLabelLegacy4272',
    'reviewAiLabelM4',
    '__m4ReviewCandidates',
    'candidateBoxM4',
    'toggleAiConfirm427',
    'v427AiConfirm',
  ]) assert.equal(source.includes(token), false, token);
  assert.match(source, /window\.submitAiLabel427=\(ids=\[\]\)=>window\.submitAiLabel429\(ids\)/);
  assert.match(source, /window\.reviewAiLabel427=async function\(id\)/);
  assert.match(source, /window\.confirmAiLabel427=id=>completeAiReview60\('partial'\)/);
});


test('AI task creation never resolves display names or aliases into canonical labels', () => {
  const helperStart = source.lastIndexOf('function explicitCanonicalAiLabelText(value)');
  const submitStart = source.lastIndexOf('window.submitAiLabel429=async function(ids=[])');
  assert.ok(helperStart > 0 && submitStart > helperStart);
  const helper = source.slice(helperStart, submitStart);
  assert.match(helper, /label\?\.code/);
  assert.match(helper, /const unknown=parts\.filter\(value=>!allowed\.has\(value\)\)/);
  assert.doesNotMatch(helper, /display_name|aliases|alias/);
  const submitEnd = source.indexOf('\n\n  function taskRow', submitStart);
  const submit = source.slice(submitStart, submitEnd);
  assert.match(submit, /if\(submit\?\.disabled\)return false/);
  assert.match(submit, /labels_text:parsed\.text/);
  assert.match(submit, /prompt_template_id:/);
  assert.match(submit, /prompt_override:/);
  assert.match(submit, /只接受当前有效的平台标签 code/);
  assert.match(source, /中文名、别名、历史 alias 不会自动转换/);
  assert.doesNotMatch(source, /function normalizedLabelText\(/);
});

test('AI create requires an effective-configuration review before its only durable POST', () => {
  assert.match(source, /id="ai429Confirmation"/);
  assert.match(source, /function renderAiCreateConfirmation429\(body\)/);
  const confirmationStart = source.lastIndexOf('function renderAiCreateConfirmation429(body)');
  const confirmationEnd = source.indexOf('\n  window.submitAiLabel429=async function(ids=[])', confirmationStart);
  const confirmation = source.slice(confirmationStart, confirmationEnd);
  assert.match(confirmation, /window\.PlatformCore\.materials\.labelDisplay/);
  assert.doesNotMatch(confirmation, /aiCreateLabelName429/);
  assert.match(source, /function aiCreateInvalidateConfirmation429\(\)/);
  const start = source.lastIndexOf('window.submitAiLabel429=async function(ids=[])');
  const end = source.indexOf('\n\n  function taskRow', start);
  const submit = source.slice(start, end);
  assert.match(submit, /const snapshot=JSON\.stringify\(body\)/);
  assert.match(submit, /if\(draft\.confirmationSnapshot!==snapshot\)/);
  assert.match(submit, /renderAiCreateConfirmation429\(body\)/);
  assert.ok(submit.indexOf('renderAiCreateConfirmation429(body)') < submit.indexOf('const task=await api(taskApi(),'));
  assert.match(submit, /catch\(error\)\{draft\.confirmationSnapshot='';return toast\('本次配置概览渲染失败/);
  assert.match(submit, /if\(draft\.submitting\)return false/);
  assert.match(submit, /draft\.submitting=true/);
  assert.match(submit, /if\(!current\(\)\)return true/);
  assert.match(submit, /ownerRoot=document\.querySelector/);
  assert.match(submit, /ownerRoot\?\.isConnected/);
  assert.doesNotMatch(submit, /aiCreateIsCurrent429|aiCreateLabelName429/);
});

test('AI create owns cancellation of obsolete fetches and timers in the existing modal lifecycle', () => {
  assert.match(source, /window\.beforeCloseAiCreate429\?\.\(layer\)/);
  const start=source.indexOf('function disposeAiCreateRequests429(draft)');
  const end=source.indexOf('function aiCreateLabelName429',start);
  const dispose=source.slice(start,end);
  assert.ok(start>0&&end>start);
  for(const name of ['materialController','referenceController','bulkController','hydrationController','previewController']){
    assert.match(dispose,new RegExp(name));
  }
  assert.match(dispose,/state\.ai429Create=null/);
  const material=source.slice(source.indexOf('window.loadAiCreateMaterials429=function'),source.indexOf('window.searchAiCreateMaterials429=function'));
  assert.match(material,/draft\.materialController\?\.abort\(\)/);
  assert.match(material,/signal:controller\.signal/);
  const references=source.slice(source.indexOf('window.loadAiCreateReferences429=async function'),source.indexOf('window.aiCreateReferenceOpened429'));
  assert.match(references,/draft\.referenceController\?\.abort\(\)/);
  assert.match(references,/signal:controller\.signal/);
  const hydration=source.slice(source.indexOf('window.hydrateAiCreate429=async function'),source.indexOf('window.createAiLabelCore429'));
  assert.match(hydration,/draft\.hydrationController\?\.abort\(\)/);
  assert.match(hydration,/signal:controller\.signal/);
});


test('AI review commit temporarily owns polling without racing the task list poller', () => {
  const start = source.lastIndexOf('window.completeAiReview60=async mode=>');
  const end = source.indexOf('// Retired UI entrypoints remain only as compatibility aliases.', start);
  assert.ok(start > 0 && end > start);
  const block = source.slice(start, end);
  assert.match(block, /ai-review-commit:/);
  assert.match(block, /waitForTaskTerminal/);
  assert.match(block, /AutoLabelPollRuntime\?\.deactivate/);
  assert.match(block, /AutoLabelPollRuntime\?\.activate/);
  assert.match(block, /pauseListPoll&&state\.page===ownerPage/);
  assert.doesNotMatch(block, /createTaskPoller/);
});

test('AI task detail polling is modal-scoped and PollRegistry-owned', () => {
  const start = source.lastIndexOf('function stopAiTaskDetail60');
  const end = source.indexOf('function explicitCanonicalAiLabelText', start);
  assert.ok(start > 0 && end > start);
  const block = source.slice(start, end);
  assert.match(block, /ai-task-detail:/);
  assert.match(block, /waitForTaskTerminal/);
  assert.match(block, /registry:window\.PollRegistryRuntime/);
  assert.match(block, /beforeCloseAiTask60/);
  assert.match(block, /AutoLabelPollRuntime\?\.deactivate/);
  assert.match(block, /AutoLabelPollRuntime\?\.activate/);
  assert.doesNotMatch(block, /createTaskPoller/);
  assert.doesNotMatch(source, /state\.ai60Pollers/);
  assert.match(source, /beforeCloseAiTask60\?\.\(top\)/);
  assert.match(source, /ai60Bar" style="transform:scaleX\(0\)/);
  assert.doesNotMatch(block, /bar\.style\.width=.*view\.percent/);
  const rowStart = source.indexOf('function taskRow(task)', end);
  const rowEnd = source.indexOf('function renderAiTaskRows60', rowStart);
  const rowBlock = source.slice(rowStart, rowEnd);
  assert.match(rowBlock, /transform:scaleX/);
  assert.doesNotMatch(rowBlock, /style="width:/);
});
