import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import ts from '../../frontend/node_modules/typescript/lib/typescript.js';
import {createTrainingDraft} from '../../static/modules/training-draft.js';
let serial=0;
const asDataModule=(source,name)=>{
 const code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
 return 'data:text/javascript;base64,'+Buffer.from(code+'\n//# sourceURL='+name+'\n//'+serial++).toString('base64');
};
async function api(request){
 globalThis.__nativeTrainingRequest=request;
 const transport='const request=(...args)=>globalThis.__nativeTrainingRequest(...args);';
 const iteration=readFileSync('frontend/src/api/training-iteration.ts','utf8')
   .replace("import {request} from '../app/http';",transport);
 let source=readFileSync('frontend/src/app/training-api.ts','utf8')
   .replace("import {request} from './http';",transport)
   .replace("'../api/training-iteration'",JSON.stringify(asDataModule(iteration,'training-iteration-under-test.mjs')));
 source=source.replaceAll('../../../static/modules/',pathToFileURL(resolve('static/modules')).href+'/');
 return import(asDataModule(source,'native-training-api-under-test.mjs'));
}
function fixture(){
 const values=new Map();globalThis.sessionStorage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
 const revision={repository_revision:1,annotation_revision:1,usage_revision:1,negative_pool_revision:1,negative_confirmation_revision:1};
 const asset={id:'a',source_type:'local',versions:[]};let posts=0,unknown=false,recovery=false,body;
 const request=async(url,options={})=>{
  if(url.includes('/train/start')){posts++;body=JSON.parse(options.body);if(unknown)throw Object.assign(new Error('lost response'),{httpStatus:503});return {ok:true,task:task(body.task_id)}}
  if(url.includes('/tasks/')){if(!recovery)throw Object.assign(new Error('not yet visible'),{httpStatus:404});return {ok:true,task:task(new URL(url,'http://localhost').pathname.split('/').at(-1))}}
  if(url.endsWith('/algorithms/a'))return {ok:true,algorithm:asset};
  if(url.includes('/revision'))return revision;
  if(url.endsWith('/selection-summary'))return {...revision,requested_count:2,matched_count:2,positive_label_codes:['smoke'],selection_validation:{...revision,requested_count:2,eligible_count:2,excluded_count:0,unknown_count:0}};
  if(url.endsWith('/compatibility'))return {compatible:true,issue_count:0,issue_counts:{},material_revision:1,annotation_revision:1};
  throw new Error('unexpected request '+url);
 };
 function task(id){return {task_id:id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',project_id:'p',algorithm_id:'a'}}
 globalThis.fetch=async(url,options)=>{try{return new Response(JSON.stringify(await request(String(url),options)),{status:200})}catch(e){return new Response(JSON.stringify({detail:e.message}),{status:e.httpStatus||503})}};
 const engine={key:'yolo_detect'},target={id:'cpu',status:'ready',framework:'ultralytics',type:'local',algorithms:[engine],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]};
 const options={projectId:'p',asset,target,engine,devices:[{id:'cpu',available:true}],draft:createTrainingDraft({algorithmId:'a',materialIds:['one','two'],newLabelCodes:['smoke'],config:{model:'yolo11n.pt'},resource:{device:'cpu'}}),trainSummary:{...revision},trainRevision:revision,stillCurrent:()=>true};
 return {request,options,get posts(){return posts},get body(){return body},set unknown(v){unknown=v},set recovery(v){recovery=v},values};
}
test('native create uses canonical full defaults and verifies durable task identity',async()=>{
 const f=fixture(),service=await api(f.request);const task=await service.submitNativeTraining(f.options);
 assert.match(task.task_id,/^train_[0-9a-f]{32}$/);assert.equal(f.posts,1);assert.equal(f.body.training_mode,'full');assert.equal(f.body.epochs,150);assert.equal(f.body.validation_percent,20);assert.equal(f.body.experiment_percent,20);assert.equal(f.body.gpu_policy,'exclusive');assert.deepEqual(f.body.train_labels,['smoke']);assert.equal(service.pendingTrainingCreation('p'),null);
});
test('unknown create survives module restart and can only reconcile with GET',async()=>{
 const f=fixture();f.unknown=true;let service=await api(f.request);await assert.rejects(service.submitNativeTraining(f.options),/待核验/);assert.equal(f.posts,1);const original=service.pendingTrainingCreation('p');assert.ok(original);
 service=await api(f.request);assert.equal(service.pendingTrainingCreation('p').taskId,original.taskId);assert.equal(service.pendingTrainingCreation('q'),null);await assert.rejects(service.submitNativeTraining(f.options),/尚未确认/);assert.equal(f.posts,1);f.recovery=true;assert.equal((await service.recoverNativeTraining('p')).task_id,original.taskId);assert.equal(service.pendingTrainingCreation('p'),null);assert.equal(f.posts,1);
});
test('a changed draft or unavailable target never reaches task POST',async()=>{
 const f=fixture(),service=await api(f.request);await assert.rejects(service.submitNativeTraining({...f.options,stillCurrent:()=>false}),/已变化/);await assert.rejects(service.submitNativeTraining({...f.options,target:{...f.options.target,status:'offline'}}),/资源已变化/);assert.equal(f.posts,0);
});

test('a frozen 22015-image selection stays a bounded reference and requires explicit background confirmation',async()=>{
 const f=fixture();const original=f.request;const request=(url,options)=>url.endsWith('/selection-summary')?Promise.resolve({repository_revision:1,annotation_revision:1,requested_count:22015,matched_count:22015,selection_reference:true,positive_label_codes:['smoke']}):original(url,options);
 const service=await api(request);const draft=createTrainingDraft({...f.options.draft,materialIds:[],trainSelectionRef:'frozen-receipt',trainSelectionCount:22015});
 await assert.rejects(service.submitNativeTraining({...f.options,draft}),/明确确认/);assert.equal(f.posts,0);
 await service.submitNativeTraining({...f.options,draft,backgroundConfirmed:true});assert.deepEqual(f.body.train_image_ids,[]);assert.equal(f.body.train_selection_ref,'frozen-receipt');assert.equal(f.body.admission_mode,'background');assert.ok(JSON.stringify(f.body).length<5000);
});
test('unpersistable task identity and formal compatibility conflicts cannot POST',async()=>{
 const f=fixture(),service=await api(f.request);globalThis.sessionStorage.setItem=()=>{throw new Error('storage unavailable')};await assert.rejects(service.submitNativeTraining(f.options),/storage unavailable/);assert.equal(f.posts,0);
 const g=fixture(),blocked=await api((url,options)=>url.endsWith('/compatibility')?Promise.resolve({compatible:false,issue_count:1,issue_counts:{conflicting_gt:1},material_revision:1,annotation_revision:1}):g.request(url,options));await assert.rejects(blocked.submitNativeTraining({...g.options,backgroundConfirmed:true}),/不符合|素材问题|其他素材/);assert.equal(g.posts,0);
});

test('confirmed permission rejection clears receipt while nested in-progress keeps it',async()=>{
 const f=fixture();let service=await api(f.request);globalThis.fetch=async()=>new Response(JSON.stringify({detail:'denied'}),{status:403});await assert.rejects(service.submitNativeTraining(f.options),/denied/);assert.equal(service.pendingTrainingCreation('p'),null);
 const g=fixture();service=await api(g.request);globalThis.fetch=async()=>new Response(JSON.stringify({detail:{code:'TRAINING_CREATE_IN_PROGRESS',message:'still processing'}}),{status:409});await assert.rejects(service.submitNativeTraining(g.options),/待核验/);assert.ok(service.pendingTrainingCreation('p'));
});

test('audited duplicate exclusions keep original scope and reject stale evidence',async()=>{
 const f=fixture(),service=await api(f.request),review={review_kind:'EXPLICIT_SELECTION_ADJUSTMENT',original_train_image_ids:['one','two','excluded'],original_test_image_ids:[],excluded_image_ids:['excluded'],material_revision:1,annotation_revision:1};
 await service.submitNativeTraining({...f.options,draft:createTrainingDraft({...f.options.draft,duplicateReview:review})});assert.deepEqual(f.body.duplicate_review,review);
 const g=fixture(),fresh=await api(g.request);await assert.rejects(fresh.submitNativeTraining({...g.options,draft:createTrainingDraft({...g.options.draft,duplicateReview:{...review,material_revision:0}})}),/排除的证据已变化/);assert.equal(g.posts,0);
});
