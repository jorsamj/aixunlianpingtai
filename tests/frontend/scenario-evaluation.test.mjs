import test from 'node:test';
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
 assert.deepEqual(sampleIssueKinds({classification_error_count:1,localization_error_count:1,low_confidence_count:1}),['wrong_class','localization','low_confidence']);
});
