import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  excludeTrainingMaterialFromDraft,
  installTrainingMaterialSummaryRuntime,
  trainingCompatibilitySignature,
  trainingMaterialSelectionSignature,
  updateTrainingGovernanceSelection,
  renderGtConflictEvidence,
  renderTrainingSampleRoles,
  removeResolvedTrainingMaterials,
} from '../../static/modules/training-material-summary-runtime.js';
import {resolveClientTrainingLabels} from '../../static/modules/training-labels.js';

test('shared GT evidence distinguishes unknown cause and null metrics without trusting HTML', () => {
  const html=renderGtConflictEvidence({observations:['COORDINATE_DIFFERENCE'],root_cause_status:'UNDETERMINED',
    iou_summary:{matched_count:0,min:null,max_pixel_delta:null}}, [{image_id:'a',filename:'<img onerror=bad()>',
    annotation_scope:['<script>'],boxes:[],content_sha256:'same'}]);
  assert.match(html,/根因待核验/);
  assert.match(html,/坐标不同/);
  assert.match(html,/未核验/);
  assert.ok(!html.includes('<img onerror=bad()>'));
  assert.match(html,/不会自动覆盖GT/);
});

test('governance selection retains cross-page choices and all-filtered exclusions without hydrating 99 pages', () => {
  let selected = updateTrainingGovernanceSelection(null, {mode:'page', ids:['a','b'], key:'project/filter/rev', total:2376});
  selected = updateTrainingGovernanceSelection(selected, {mode:'page', ids:['c'], key:'project/filter/rev', total:2376});
  assert.deepEqual(selected.image_ids, ['a','b','c']);
  selected = updateTrainingGovernanceSelection(selected, {mode:'all', key:'project/filter/rev', total:2376});
  selected = updateTrainingGovernanceSelection(selected, {mode:'toggle', id:'c', checked:false, key:'project/filter/rev', total:2376});
  assert.equal(selected.count, 2375);
  assert.equal(selected.all_filtered, true);
  assert.deepEqual(selected.image_ids, []);
  assert.deepEqual(selected.excluded_image_ids, ['c']);
  assert.equal(JSON.stringify(selected).length < 250, true);
  assert.equal(updateTrainingGovernanceSelection(selected, {mode:'read', key:'other-project/filter/rev', total:1}).count, 0);
  assert.equal(updateTrainingGovernanceSelection(selected, {mode:'read', key:'project/filter/new-rev', total:2376}).count, 0);
});

test('selection signature is stable and duplicate independent', () => {
  assert.equal(
    trainingMaterialSelectionSignature(['b', 'a', 'b']),
    trainingMaterialSelectionSignature(['a', 'b']),
  );
});

test('all issues selection is distinct from current filtered selection across pages',()=>{
  const selected=updateTrainingGovernanceSelection(null,{mode:'issues',key:'p/rev',total:3,allTotal:38});
  assert.equal(selected.all_issues,true);assert.equal(selected.all_filtered,false);assert.equal(selected.count,38);
  const next=updateTrainingGovernanceSelection(selected,{mode:'toggle',id:'bad',checked:false,key:'p/rev',total:3,allTotal:38});
  assert.equal(next.count,37);assert.deepEqual(next.excluded_image_ids,['bad']);
});

test('resolved draft removal deduplicates actual IDs and clears stale review without editing other fields',()=>{
  const draft={algorithmId:'alg',materialIds:['a','b','c'],testMaterialIds:['t'],config:{epochs:100},duplicateReview:{old:true}};
  const patch=removeResolvedTrainingMaterials({update:value=>value},draft,['b','b','missing']);
  assert.deepEqual(patch.materialIds,['a','c']);assert.deepEqual(patch.testMaterialIds,['t']);assert.equal(patch.duplicateReview,null);
  assert.equal('config' in patch,false);assert.equal('algorithmId' in patch,false);
});

test('explicit exclusion keeps one revision-bound adjustment audit for every issue type',()=>{
  const draft={materialIds:['a','b','c'],testMaterialIds:['t']};
  const next=removeResolvedTrainingMaterials({update:value=>value},draft,['b','b'],{material_revision:12,annotation_revision:8});
  assert.equal(next.duplicateReview.review_kind,'EXPLICIT_SELECTION_ADJUSTMENT');
  assert.deepEqual(next.duplicateReview.original_train_image_ids,['a','b','c']);assert.deepEqual(next.duplicateReview.excluded_image_ids,['b']);
  const last=removeResolvedTrainingMaterials({update:value=>value},next,['t'],{material_revision:12,annotation_revision:8});
  assert.deepEqual(last.duplicateReview.original_test_image_ids,['t']);assert.deepEqual(last.duplicateReview.excluded_image_ids,['b','t']);
});

test('duplicate exclusions preserve explicit original scope and canonical revisions without deleting materials', () => {
  const draft={materialIds:['a','b','c'],testMaterialIds:[]};
  const truth={material_revision:12,annotation_revision:7,items:[{image_id:'b',issue_type:'duplicate_annotation_conflict'}]};
  const result=excludeTrainingMaterialFromDraft({update:patch=>patch},draft,'b',truth);
  assert.deepEqual(result.materialIds,['a','c']);
  assert.deepEqual(result.duplicateReview,{original_train_image_ids:['a','b','c'],original_test_image_ids:[],excluded_image_ids:['b'],material_revision:12,annotation_revision:7});
});

test('task compatibility signature changes with labels and selected material truth', () => {
  const base = {
    algorithmId: 'alg-1', materialIds: ['b', 'a'], testMaterialIds: [],
    splitMode: 'random_test_from_training_pool', newLabelCodes: ['fire'],
    config: {model: 'yolo11n.pt'}, experimentPercent: 20, validationPercent: 20,
  };
  assert.equal(
    trainingCompatibilitySignature(base),
    trainingCompatibilitySignature({...base, materialIds: ['a', 'b']}),
  );
  assert.notEqual(
    trainingCompatibilitySignature(base),
    trainingCompatibilitySignature({...base, newLabelCodes: ['fire', 'smoke']}),
  );
});

test('excluding an issue only updates the current training draft', () => {
  const updates = [];
  const draft = {materialIds: ['bad', 'good'], testMaterialIds: ['test']};
  const result = excludeTrainingMaterialFromDraft(
    {update: patch => { updates.push(patch); return patch; }},
    draft,
    'bad',
  );
  assert.deepEqual(result, {materialIds: ['good'], testMaterialIds: ['test']});
  assert.deepEqual(updates, [result]);
});

test('server available codes override a partial local material page', () => {
  const view = resolveClientTrainingLabels({
    materials: [{id: 'selected-1', labels: ['smoke']}],
    selectedIds: ['selected-1', 'selected-outside-page'],
    labelCatalog: [{code: 'smoke'}, {code: 'person'}],
    algorithm: {versions: []},
    requestedCodes: ['smoke', 'person'],
    availableCodes: ['smoke', 'person'],
  });
  assert.deepEqual(view.available, ['smoke', 'person']);
  assert.deepEqual(view.requested, ['smoke', 'person']);
});

test('training page full-pool hydration is explicitly disabled and summary runtime owns server truth', () => {
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  const summaryRuntime = readFileSync(new URL('../../static/modules/training-material-summary-runtime.js', import.meta.url), 'utf8');
  const labelsRuntime = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

  assert.doesNotMatch(main, /FULL_MATERIAL_PAGES/);
  assert.match(main, /installTrainingMaterialSummaryRuntime/);
  assert.match(main, /materialSummaryRuntime: trainingMaterialSummaryRuntime/);
  assert.match(summaryRuntime, /training-materials\/selection-summary/);
  assert.match(summaryRuntime, /training-materials\/compatibility/);
  assert.match(summaryRuntime, /PlatformCore\?\.pagination\?\.mountPagination/);
  assert.match(summaryRuntime, /page: compatibilityPage/);
  assert.match(summaryRuntime, /page_size: pageSize/);
  assert.match(summaryRuntime, /onPageChange:/);
  assert.match(summaryRuntime, /onPageSizeChange:/);
  assert.doesNotMatch(summaryRuntime, /onclick="TrainingMaterialSummaryRuntime\.loadIssuePage[^>]*>上一页/);
  assert.match(summaryRuntime, /去补审/);
  assert.match(summaryRuntime, /排除本次训练/);
  assert.match(summaryRuntime, /fullPoolHydration: false/);
  assert.match(summaryRuntime, /selectable_total/);
  assert.match(summaryRuntime, /pending_annotation_count/);
  assert.match(summaryRuntime, /正式标注/);
  assert.doesNotMatch(summaryRuntime, /可直接训练/);
  assert.match(summaryRuntime, /待标注/);
  assert.match(labelsRuntime, /materialSummaryRuntime\.summaryReadyFor/);
  assert.match(labelsRuntime, /materialSummaryRuntime\?\.invalidate\?\.\(\)/);
  assert.match(labelsRuntime, /正在读取训练标签/);
  assert.match(summaryRuntime, /function invalidate\(\)/);
  assert.match(summaryRuntime, /currentSignature = null/);
  assert.match(summaryRuntime, /summary = null/);
  assert.match(app, /invalidateTrainingMaterialSummaryAfterLabelMutation414/);
  assert.match(app, /runtime\?\.refresh\?\.\(ids,\{force:true\}\)/);
});


test('unchanged compatibility decoration does not feed a body MutationObserver loop',async()=>{
  let html='',writes=0;
  const row={dataset:{},querySelector:()=>null,get innerHTML(){return html},set innerHTML(value){html=value;writes++}};
  globalThis.window={};globalThis.document={body:{},getElementById:()=>null,querySelector:selector=>selector==='.train429-data-summary'?{querySelector:()=>row}:null,querySelectorAll:()=>[]};
  const runtime=installTrainingMaterialSummaryRuntime({getState:()=>({}),projectId:()=>'',trainingDraftRuntime:{materialIds:()=>[],current:()=>null}});
  try{runtime.decorateTrainingCreateUi();runtime.decorateTrainingCreateUi();await new Promise(resolve=>setImmediate(resolve));assert.equal(writes,1,'same snapshot must not keep replacing its own observed children')}
  finally{runtime.destroy();delete globalThis.window;delete globalThis.document;}
});


test('a failed compatibility request renders retryable failure instead of a permanent checking summary',async()=>{
  let html='',writes=0;const row={dataset:{},querySelector:()=>null,get innerHTML(){return html},set innerHTML(value){html=value.replaceAll('data-training-compatibility-open>','data-training-compatibility-open="">');writes++}};
  const draft={algorithmId:'a',materialIds:['a','b'],newLabelCodes:['smoke']};
  globalThis.window={};globalThis.document={body:{},getElementById:()=>null,querySelector:selector=>selector==='.train429-data-summary'?{querySelector:()=>row}:null,querySelectorAll:()=>[]};
  const runtime=installTrainingMaterialSummaryRuntime({getState:()=>({trainingDraft:draft}),projectId:()=> 'p',trainingDraftRuntime:{materialIds:()=>draft.materialIds,current:()=>draft},fetchImpl:async()=>{throw new Error('isolated unavailable')}});
  try{await new Promise(resolve=>setImmediate(resolve));runtime.decorateTrainingCreateUi();assert.match(html,/点击开始训练后检查/);assert.equal(runtime.compatibilityFor().ready,false);await runtime.refreshCompatibility({force:true});runtime.decorateTrainingCreateUi();assert.match(html,/失败|重试/);assert.doesNotMatch(html,/检查中/);const before=writes;runtime.decorateTrainingCreateUi();assert.equal(writes,before,'DOM attribute serialization must not trigger repeated identical renders')}finally{runtime.destroy();delete globalThis.window;delete globalThis.document}
});

test('pending selection summary and stalled compatibility body both release loading with a deadline',async()=>{
  const previous={window:globalThis.window,document:globalThis.document};
  const draft={algorithmId:'a',materialIds:['a','b'],newLabelCodes:['smoke']},messages=[];
  globalThis.window={};globalThis.document={body:{},getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[]};
  const runtime=installTrainingMaterialSummaryRuntime({getState:()=>({trainingDraft:draft}),projectId:()=> 'p',requestTimeoutMs:15,
    trainingDraftRuntime:{materialIds:()=>draft.materialIds,current:()=>draft},notify:message=>messages.push(message),
    fetchImpl:async url=>url.endsWith('selection-summary')?new Promise(()=>{}):{ok:true,json:()=>new Promise(()=>{})}});
  try{await runtime.refreshCompatibility({force:true});await new Promise(resolve=>setTimeout(resolve,45));assert.equal(runtime.state().loading,false);assert.equal(runtime.compatibilityFor().loading,false);assert.match(messages.join(' '),/超时/)}
  finally{runtime.destroy();Object.assign(globalThis,previous)}
});

test('sample role summary distinguishes task labels and warns without dropping negatives',()=>{
 const html=renderTrainingSampleRoles({effective_label_codes:['vest'],sample_role_counts:{positive:500,confirmed_negative:3000,pending_negative:200,pending_review:2}});
 assert.match(html,/vest/);assert.match(html,/正样本 500/);assert.match(html,/已确认负样本 3000/);assert.match(html,/待确认负样本 200/);assert.match(html,/2 张素材需修复/);assert.match(html,/比例/);
 assert.equal(renderTrainingSampleRoles({label_codes:['person']}),'');
});
