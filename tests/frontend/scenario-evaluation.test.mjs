import test from 'node:test';
import * as evidence from '../../static/modules/scenario-evaluation.js';
import assert from 'node:assert/strict';
import {eligibleScenarioModels,latestScenarioModel,evaluationTruth,scenarioMetric,visibleEvidenceBoxes,sampleIssueKinds} from '../../static/modules/scenario-evaluation.js';
const sha='a'.repeat(64),scope={binding_level:'bundle_verified',test_image_count:5,scope_id:'b'.repeat(64),content_digest:'c'.repeat(64),ground_truth_digest:'d'.repeat(64),label_schema_digest:'e'.repeat(64),evaluation_input_digest:'f'.repeat(64),training_input_policy:'sha256_disjoint'};
const model={model_source:'algorithm_version',algorithm_id:'a',version_id:'v2',scenario_eligible:true,training_task_id:'task2',model_sha256:sha,model_size:25,created_at:'2026-10-22'};
const evaluation={image_count:5,evaluation_protocol_id:'9'.repeat(64),status:'succeeded',evaluation_id:'1'.repeat(64),task_id:'task2',snapshot_id:'snapshot2',dataset_revision_id:'2'.repeat(64),model_sha256:sha,benchmark_scope:scope,metrics:{precision:0.7},per_class:[],error_samples:[]};
test('scenario selectors reject builtin, filename-only, converted and missing durable identity even if one flag is forged',()=>{
 const rows=[model,{...model,model_source:'builtin'},{...model,scenario_eligible:false,path:'best.pt'},{...model,model_source:'deployment_artifact'},{...model,training_task_id:''},{...model,model_sha256:''},{...model,model_size:0}];
 assert.deepEqual(eligibleScenarioModels(rows),[model]);
});
test('latest successful version is stable by server creation time, strictly scoped to algorithm',()=>{
 const old={...model,version_id:'v1',created_at:'2026-10-21'},other={...model,algorithm_id:'other',created_at:'2026-10-23'};
 assert.equal(latestScenarioModel([old,other,model],'a').version_id,'v2');
 assert.equal(latestScenarioModel([model],'missing'),null);
});
test('independent evaluation requires task, model, frozen benchmark and report identities; errors never become zero metrics',()=>{
 assert.equal(evaluationTruth(evaluation,model).trusted,true);
 for(const patch of [{evaluation_protocol_id:''},{image_count:0},{status:'failed'},{evaluation_id:''},{task_id:'another'},{model_sha256:'b'.repeat(64)},{snapshot_id:''},{benchmark_scope:{...scope,binding_level:'legacy'}}])assert.equal(evaluationTruth({...evaluation,...patch},model).trusted,false);
 assert.equal(scenarioMetric(null),'未记录');assert.equal(scenarioMetric(0),'0.0%');assert.equal(scenarioMetric(NaN),'未记录');
 assert.equal(scenarioMetric(.5,{covered:false}),'未覆盖');
});
test('box filters use actual evidence with explicit confidence, preserve zero and do not generate missing values',()=>{
 const rows=[{label:'fire',box:[1,2,4,6],confidence:0},{label:'smoke',box:[2,3,5,7],confidence:.8},{label:'fire',box:[3,3,6,8]}];
 assert.equal(visibleEvidenceBoxes(rows,{label:'fire',confidence:0,prediction:true}).length,1);
 assert.equal(visibleEvidenceBoxes(rows,{confidence:.5,prediction:true}).length,1);
 assert.equal(visibleEvidenceBoxes(rows,{label:'fire',prediction:false}).length,2);
});
test('only confirmed report evidence supports error filters; raw predictions cannot invent TP FP FN',()=>{
 assert.deepEqual(sampleIssueKinds({detections:[{confidence:.2}]}),[]);
 assert.deepEqual(sampleIssueKinds({fp_count:1,fn_count:2}),['fp','fn']);
 assert.deepEqual(sampleIssueKinds({classification_error_count:1,localization_error_count:1,low_confidence_count:1}),[]);
});

const gt=(patch={})=>({class_id:0,label:'person',box:[0,0,10,10],matched:false,...patch});
const pred=(patch={})=>({...gt(),confidence:.8,...patch});
const sample=(patch={})=>({image:'one.jpg',gt_boxes:[gt()],pred_boxes:[pred()],...patch});
test('wrong-class filters require actual class-agnostic protocol cells for this image',()=>{
 const matrix={protocol:'confidence_first_class_agnostic_iou_0.5',cells:[{actual:0,predicted:1,images:['one.jpg'],count:1}]};
 assert.ok(sampleIssueKinds(sample(),{evaluation:{confusion_matrix:matrix}}).includes('wrong_class'));
 for(const bad of [{...matrix,protocol:'other'},{...matrix,cells:[{actual:null,predicted:1,images:['one.jpg']}]},{...matrix,cells:[{actual:0,predicted:0,images:['one.jpg']}]},{...matrix,cells:[{actual:0,predicted:1,images:['another.jpg']}]}])assert.equal(sampleIssueKinds(sample(),{evaluation:{confusion_matrix:bad}}).includes('wrong_class'),false);
});
test('low confidence reads explicit prediction values and preserves zero while ignoring missing invalid scores',()=>{
 for(const value of [0,.1,.499])assert.ok(sampleIssueKinds(sample({pred_boxes:[pred({confidence:value})]})).includes('low_confidence'));
 for(const value of [undefined,null,'',false,-.1,.5,1,NaN,Infinity])assert.equal(sampleIssueKinds(sample({pred_boxes:[pred({confidence:value})]})).includes('low_confidence'),false);
 assert.ok(sampleIssueKinds(sample({pred_boxes:[pred({confidence:.6})]}),{lowConfidenceThreshold:.7}).includes('low_confidence'));
});
test('localization is an observed unmatched same-class geometric clue, never a synthesized error count',()=>{
 const row=sample({pred_boxes:[pred({box:[5,0,15,10]})],boxes_truncated:true}),detail=evidence.sampleEvidenceDiagnostics(row);
 assert.ok(detail.kinds.includes('localization'));assert.equal(detail.localizationCandidates.length,1);assert.equal(detail.localizationCandidates[0].iou,1/3);assert.match(detail.localizationLabel,/定位待复核/);assert.match(detail.localizationLabel,/非正式错误指标/);assert.equal(detail.boxesTruncated,true);assert.equal('localization_error_count' in row,false);
});
test('localization excludes no-overlap, exact threshold, matched, unknown-match and invalid geometry',()=>{
 for(const box of [pred({box:[10,0,20,10]}),pred({box:[0,0,5,10]}),pred({box:[5,0,15,10],matched:true}),pred({box:[5,0,15,10],matched:undefined}),pred({box:[5,0,5,10]}),pred({box:[NaN,0,15,10]})])assert.equal(sampleIssueKinds(sample({pred_boxes:[box]})).includes('localization'),false);
});
test('formal class IDs take precedence and conflicting code/class identities cannot imply localization',()=>{
 for(const box of [pred({class_id:1,box:[5,0,15,10]}),pred({label:'smoke',box:[5,0,15,10]}),pred({class_id:'bad',box:[5,0,15,10]})])assert.equal(sampleIssueKinds(sample({pred_boxes:[box]})).includes('localization'),false);
 const codeOnly=sample({gt_boxes:[gt({class_id:undefined})],pred_boxes:[pred({class_id:undefined,box:[5,0,15,10]})]});assert.ok(sampleIssueKinds(codeOnly).includes('localization'));
 assert.equal(sampleIssueKinds(sample({gt_boxes:[gt({class_id:undefined,label:'人员'})],pred_boxes:[pred({class_id:undefined,label:'人员',box:[5,0,15,10]})]})).includes('localization'),false);
});
test('true positive linking uses original matched flags and raw quick predictions cannot acquire formal metrics',()=>{
 const row=sample({gt_boxes:[gt({matched:true})],pred_boxes:[pred({matched:true})]}),detail=evidence.sampleEvidenceDiagnostics(row);
 assert.ok(detail.kinds.includes('tp'));assert.deepEqual(detail.truePositivePredictionIndexes,[0]);assert.deepEqual(detail.truePositiveGroundTruthIndexes,[0]);
 assert.deepEqual(sampleIssueKinds({detections:[{...pred(),matched:true}],fp_count:1,fn_count:1}),[]);
 assert.equal(sampleIssueKinds(sample()).includes('tp'),false);
});
test('frozen A/B image identity requires ID SHA and original dimensions, never a matching filename',()=>{
 const a={image:'same.jpg',image_id:'id',image_content_sha256:'a'.repeat(64),image_width:640,image_height:480};
 assert.equal(evidence.sameFrozenSample(a,{...a,image:'renamed.jpg'}),true);
 for(const patch of [{image_id:'other'},{image_content_sha256:'b'.repeat(64)},{image_width:480},{image_height:640},{image_id:''},{image_content_sha256:''},{image_width:0},{image_height:NaN}])assert.equal(evidence.sameFrozenSample(a,{...a,...patch}),false);
 assert.equal(evidence.sameFrozenSample({image:'same.jpg'},{image:'same.jpg'}),false);
});
test('diagnostics never mutate frozen boxes counts or evaluation objects',()=>{
 const row=sample({pred_boxes:[pred({box:[5,0,15,10],confidence:.3})],fp_count:2,fn_count:1}),input=JSON.stringify({row,evaluation});evidence.sampleEvidenceDiagnostics(row,{evaluation});assert.equal(JSON.stringify({row,evaluation}),input);
});

test('explicit classId zero filters duplicate label codes by stable class identity',()=>{
 const rows=[{class_id:0,label:'person',box:[0,0,2,2]},{class_id:1,label:'person',box:[0,0,2,2]},{label:'person',box:[0,0,2,2]}];
 assert.deepEqual(visibleEvidenceBoxes(rows,{classId:0}),[rows[0]]);assert.deepEqual(visibleEvidenceBoxes(rows,{classId:'0'}),[rows[0]]);assert.deepEqual(visibleEvidenceBoxes(rows,{classId:null}),rows);assert.deepEqual(visibleEvidenceBoxes(rows,{classId:undefined}),rows);assert.deepEqual(visibleEvidenceBoxes(rows,{classId:'invalid'}),[]);
});

test('truncated evidence keeps observed clues without inventing missing false negatives',()=>{
 const row=sample({boxes_truncated:true,pred_boxes:[pred({box:[5,0,15,10],confidence:.2})]}),kinds=sampleIssueKinds(row);
 assert.ok(kinds.includes('localization'));assert.ok(kinds.includes('low_confidence'));assert.equal(kinds.includes('fp'),false);assert.equal(kinds.includes('fn'),false);
});
test('code-only fallback rejects an observed label shared by conflicting class identities',()=>{
 const row=sample({gt_boxes:[gt({class_id:undefined})],pred_boxes:[pred({class_id:undefined,box:[5,0,15,10]}),pred({class_id:0,box:[30,0,40,10]}),pred({class_id:1,box:[50,0,60,10]})]});
 assert.equal(sampleIssueKinds(row).includes('localization'),false);
});
