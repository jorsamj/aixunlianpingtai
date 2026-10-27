import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {withRequestDeadline} from '../../static/modules/api.js';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('/* Persistent deployment tests:');
const code=source.slice(start,source.indexOf('/* Activate the storage UI',start));
function setup(replies,envs=[{framework:'ultralytics',status:'ready'}],poll,uploadEvents=[],deadline=fn=>fn()){
 const calls=[],updates=[],window={PlatformCore:{withRequestDeadline:deadline,taskPoller:{waitForTaskTerminal:async opts=>{updates.push(opts.initialTask);opts.onUpdate(opts.initialTask);return {id:'task-one',status:'SUCCEEDED'};}}}};
 if(poll)window.PlatformCore.taskPoller.waitForTaskTerminal=poll;
 const api=async(url,options)=>{calls.push({url,options});if(options?.onUploadProgress)for(const bytes of uploadEvents)options.onUploadProgress(bytes);const reply=replies.shift();if(reply instanceof Error)throw reply;return reply;};
 vm.runInNewContext(code,{window,api,state:{inferenceEnvs:envs},pid:()=> 'p',document:{getElementById:()=>null},FormData,crypto:globalThis.crypto});
 return {predict:(select,file,conf,meta)=>window.benchPredictOne(select,file,conf,{model_scope:'scenario',batch_id:'batch-one',...meta}),rawPredict:window.benchPredictOne,calls,updates};
}
const model={path:'model.pt',framework:'ultralytics'};
test('refresh without File recovers a validated staged input using the original creation identity',async()=>{
 const a=setup([{creation_state:'NOT_CREATED',staged_input_available:true,input_image_url:'/staged-original'},{id:'task-one',status:'QUEUED',phase:'PREPARING_MODEL'},{result:{detections:[]}}]);
 const result=await a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'staged-original',recover_creation:true});
 assert.equal(result.task_id,'task-one');assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,1);
 assert.match(a.calls[1].url,/deployment-test-creations\/staged-original\/recover$/);assert.equal(a.calls[1].options.body,undefined);
 assert.equal(a.calls.some(call=>call.url.endsWith('/deployment-tests')&&call.options?.method==='POST'),false);assert.equal(a.updates[0].id,'task-one');
});
test('real 30s task-load and result deadlines preserve the created task for recovery without another POST',async t=>{
 t.mock.timers.enable({apis:['setTimeout']});
 for(const phase of ['load','result']){
 const poll=phase==='load'?async options=>{const task=await options.load();options.onUpdate(task);return task;}:undefined;
 const replies=[{id:'task-one',status:'QUEUED'},new Promise(()=>{})];if(phase==='load')replies.push({id:'task-one',status:'SUCCEEDED'});replies.push({result:{detections:[]}});
 const a=setup(replies,undefined,poll,[],withRequestDeadline);
 const pending=a.predict('A',new Blob(['image']),.25,{model,creation_id:'created-before-timeout'});
 for(let turn=0;turn<12&&a.calls.length<2;turn++)await Promise.resolve();
 assert.equal(a.calls.length,2);assert.match(a.calls[1].url,/deployment-tests\/task-one$/);
 t.mock.timers.tick(31000);
 await assert.rejects(pending,error=>error.creationUncertain&&error.task_id==='task-one'&&error.creation_id==='created-before-timeout'&&error.code==='REQUEST_TIMEOUT');
 assert.equal(a.calls[1].options.signal.aborted,true);
 const restored=await a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'created-before-timeout',initial_task:{id:'task-one',status:'QUEUED'}});
 assert.equal(restored.task_id,'task-one');assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,1);
 }
});
test('stopping during an uncertain lookup suppresses a late NOT_CREATED resubmission',async()=>{
 const a=setup([{creation_state:'NOT_CREATED'}]);
 await assert.rejects(a.predict('A',new Blob(['image']),.25,{model,creation_id:'stopped-original',recover_creation:true,should_create:()=>false}),error=>error.httpStatus===400);
 assert.equal(a.calls.length,1);assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,0);
});
test('automatic creation verification has five bounded original-owner attempts and clears stale callbacks',async()=>{
 const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8'),start=source.indexOf('  function clearCreationVerification64(');
 assert.ok(start>=0,'bounded verification must be owned by the existing workbench');
 const code=source.slice(start,source.indexOf('  function saveCreationMetadata64(',start)),entries=new Map(),delays=[],calls=[];
 const run={id:'batch-original',outcomeUncertain:true,running:false,results:[{creationIds:{A:'side-original'}}]},context={creationVerifyKey64:'',creationVerifyGeneration64:0,batch64:()=>run,pid:()=> 'p',state:{page:'质量中心'},document:{querySelector:()=>({})},window:{PollRegistryRuntime:{clear:key=>entries.delete(key),startTimeout:(key,owners,callback,delay)=>{entries.set(key,callback);delays.push(delay);assert.deepEqual([...owners],['质量中心']);}}}};
 vm.createContext(context);vm.runInContext(code+'globalThis.schedule=scheduleCreationVerification64;globalThis.clear=clearCreationVerification64;',context);
 context.window.runBenchBatch64=async(recover,automatic)=>{calls.push({recover,automatic,id:run.results[0].creationIds.A});run.running=true;await Promise.resolve();run.running=false;context.schedule(run,'p');};
 context.schedule(run,'p');context.schedule(run,'p');assert.equal(entries.size,1);
 for(let index=0;index<5;index++){const [key,callback]=entries.entries().next().value;entries.delete(key);await callback();}
 assert.deepEqual(delays,[1000,2000,4000,8000,15000]);assert.equal(calls.length,5);assert.equal(entries.size,0);assert.ok(calls.every(call=>call.recover&&call.automatic&&call.id==='side-original'));
 run.autoVerifyAttempts=0;context.schedule(run,'p');const stale=entries.values().next().value;run.autoVerifyStopped=true;context.clear();await stale();context.schedule(run,'p');assert.equal(entries.size,0);assert.equal(calls.length,5);
 run.autoVerifyStopped=false;run.running=true;context.schedule(run,'p');assert.equal(entries.size,0);run.running=false;
 context.schedule(run,'p');const [oldKey,oldProjectCallback]=entries.entries().next().value;entries.delete(oldKey);context.pid=()=> 'other-project';await oldProjectCallback();assert.equal(calls.length,5);
 run.outcomeUncertain=false;context.schedule(run,'p');assert.equal(entries.size,0);
 assert.match(source,/function deactivate64\(\)\{[^\n]*clearCreationVerification64/);
});
test('real default 30s deadline recovers accepted creation without a second POST',async t=>{
 assert.match(readFileSync(new URL('../../static/modules/api.js',import.meta.url),'utf8'),/timeoutMs\s*=\s*30000/);
 t.mock.timers.enable({apis:['setTimeout']});
 const a=setup([new Promise(()=>{}),{creation_state:'CREATED',task:{id:'task-one',status:'QUEUED',phase:'PREPARING_MODEL'}},{result:{detections:[]}}],undefined,undefined,[],withRequestDeadline);
 const pending=a.predict('A',new Blob(['image']),.25,{model,creation_id:'deadline-original'});
 await Promise.resolve();await Promise.resolve();
 assert.equal(a.calls.length,1);assert.equal(a.calls[0].options.signal.aborted,false);
 t.mock.timers.tick(31000);
 const result=await pending;
 assert.equal(result.task_id,'task-one');assert.equal(a.calls[0].options.signal.aborted,true);
 assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,1);
 assert.match(a.calls[1].url,/deployment-test-creations\/deadline-original$/);
 assert.equal(a.updates[0].id,'task-one');assert.equal(a.updates[0].phase,'PREPARING_MODEL');
});
test('actual upload byte events distinguish transport from task creation before acceptance',async()=>{
 const a=setup([{id:'task-one',status:'QUEUED'},{result:{}}],undefined,undefined,[{loaded:4,total:8},{loaded:8,total:8}]),events=[];
 await a.predict('A',new Blob(['image']),.25,{model,onProgress:task=>events.push(task)});
 assert.equal(events[0].id,null);assert.equal(events[0].phase,'UPLOADING_IMAGE');assert.match(events[0].current_item,/4.*8/);
 assert.equal(events[1].id,null);assert.equal(events[1].phase,'CREATING_TASK');assert.equal(events[2].id,'task-one');
});
test('durable batch aggregates expected sides and never counts cancellation as success',()=>{
 const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
 const code=source.slice(source.indexOf('  function durableSide64('),source.indexOf('  window.renderDetectionBatchHistory64='));
 const context={crypto:globalThis.crypto};vm.createContext(context);vm.runInContext(code+'globalThis.restore=batchFromDurable64;',context);
 const a={status:'SUCCEEDED',task_id:'a',detections:[],model};
 const missing=context.restore({batch_id:'missing',items:[{index:0,expected_sides:['A','B'],models:{A:a}}]});
 assert.equal(missing.mode,'compare');assert.equal(missing.results[0].status,'partial');assert.equal(missing.success,0);
 const stopped=context.restore({batch_id:'stopped',items:[{index:0,expected_sides:['A'],models:{A:{status:'CANCELLED',task_id:'cancel-a'}}}]});
 assert.equal(stopped.results[0].status,'cancelled');assert.equal(stopped.success,0);
 const partial=context.restore({batch_id:'partial',items:[{index:0,expected_sides:['A','B'],models:{A:a,B:{status:'CANCELLED',task_id:'cancel-b'}}}]});
 assert.equal(partial.results[0].status,'partial');assert.equal(partial.success,0);
 const noResult=context.restore({batch_id:'no-result',items:[{index:0,expected_sides:['A'],models:{A:{status:'SUCCEEDED',task_id:'missing-result'}}}]});
 assert.equal(noResult.success,0);assert.equal(noResult.results[0].status,'not_submitted');
});
test('scenario poll uses mapped deployment details while legacy retains generic tasks',async()=>{
 const poll=async options=>{const task=await options.load();options.onUpdate(task);return task;};
 const a=setup([{id:'task-one',status:'QUEUED'},{id:'task-one',status:'SUCCEEDED',phase:'GENERATING_RESULT',preparation:{status:'SUCCEEDED'}},{result:{}}],undefined,poll);
 let phase='';await a.predict('A',new Blob(['image']),.25,{model,onProgress:task=>{phase=task.phase;}});
 assert.match(a.calls[1].url,/\/api\/v61\/projects\/p\/deployment-tests\/task-one$/);assert.equal(phase,'GENERATING_RESULT');
 const b=setup([{id:'task-one',status:'QUEUED'},{id:'task-one',status:'SUCCEEDED'},{result:{}}],undefined,poll);
 await b.rawPredict('A',new Blob(['image']),.25,{model});assert.match(b.calls[1].url,/\/api\/v62\/projects\/p\/tasks\/task-one$/);
});
test('summary counts submitted and real phases once per image, never local running',()=>{
 const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
 const summary=source.slice(source.indexOf('  function summary64(){'),source.indexOf('  function updateScenarioProgress64('));
 const box={innerHTML:''},run={total:4,results:[{status:'running'}, {sideTasks:{A:{id:'a',status:'QUEUED'},B:{id:'b',status:'QUEUED'}}},{sideTasks:{A:{id:'c',status:'QUEUED',phase:'PREPARING_MODEL'}}},{sideTasks:{A:{id:'d',status:'RUNNING',phase:'INFERENCING'},B:{id:'e',status:'QUEUED'}}}]};
 vm.runInNewContext(summary+'summary64();',{batch64:()=>run,document:{getElementById:()=>box},esc:x=>x});
 assert.match(box.innerHTML,/已提交图片<\/span><b>3<\/b>/);assert.match(box.innerHTML,/排队图片<\/span><b>1<\/b>/);assert.match(box.innerHTML,/准备图片<\/span><b>1<\/b>/);assert.match(box.innerHTML,/检测中图片<\/span><b>1<\/b>/);
});
test('legacy non-scenario POST stays non-idempotent and never blindly resends after transport failure',async()=>{
 const a=setup([new Error('timeout'),{creation_state:'NOT_CREATED'}]);
 await assert.rejects(a.rawPredict('A',new Blob(['image']),.25,{model,creation_id:'ignored-for-legacy'}),error=>error.creationUncertain);
 assert.equal(a.calls.length,1);assert.equal(a.calls[0].options.method,'POST');assert.equal(a.calls[0].options.body.has('creation_id'),false);
});
test('lost creation response resolves the stable creation identity and attaches original task',async()=>{
 const {predict,calls,updates}=setup([new Error('timeout'),{creation_state:'CREATED',task_id:'task-one',task:{id:'task-one',status:'QUEUED',phase:'PREPARING_MODEL'}},{result:{detections:[]}}]);
 const result=await predict('A',new Blob(['image']),.25,{model,creation_id:'stable-one'});
 assert.equal(result.task_id,'task-one');assert.equal(calls[0].options.body.get('creation_id'),'stable-one');assert.match(calls[1].url,/deployment-test-creations\/stable-one$/);assert.equal(updates[0].phase,'PREPARING_MODEL');
});
test('NOT_CREATED permits safe resend with same identity; unknown lookup never resends',async()=>{
 const a=setup([new Error('timeout'),{creation_state:'NOT_CREATED'},{id:'task-one',status:'QUEUED'},{result:{}}]);
 await a.predict('A',new Blob(['image']),.25,{model,creation_id:'same-id'});
 assert.equal(a.calls[2].options.body.get('creation_id'),'same-id');
 const b=setup([new Error('timeout'),new Error('offline')]);
 await assert.rejects(b.predict('A',new Blob(['image']),.25,{model,creation_id:'same-id'}),error=>error.creationUncertain&&error.creation_id==='same-id');
 assert.equal(b.calls.filter(call=>call.options?.method==='POST').length,1);
});
test('refresh recovery attaches existing task without retaining an original File',async()=>{
 const a=setup([{creation_state:'CREATED',task:{id:'task-one',status:'QUEUED'}},{result:{}}]);
 await a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'kept-id',recover_creation:true});
 assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,0);
});
test('CREATING remains queryable without another upload',async()=>{
 const a=setup([{creation_state:'CREATING'}]);
 await assert.rejects(a.predict('A',new Blob(['image']),.25,{model,creation_id:'kept-id',recover_creation:true}),error=>error.creationUncertain);
 assert.equal(a.calls.length,1);
});
test('existing task recovery does not require a currently ready Runtime',async()=>{
 const a=setup([{creation_state:'CREATED',task:{id:'task-one',status:'QUEUED'}},{result:{}}],[]);
 await a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'kept-id',recover_creation:true});
 assert.equal(a.calls.filter(call=>call.options?.method==='POST').length,0);
});
test('explicit task retry attaches the returned original task without uploading',async()=>{
 const a=setup([{result:{}}],[]);
 const result=await a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'kept-id',initial_task:{id:'task-one',status:'QUEUED'}});
 assert.equal(result.task_id,'task-one');assert.equal(a.calls.length,1);assert.match(a.calls[0].url,/deployment-tests\/task-one$/);
});
test('poll transport failure preserves known task identity for recovery',async()=>{
 const a=setup([],[],async()=>{throw new Error('offline');});
 await assert.rejects(a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'kept-id',initial_task:{id:'task-one',status:'QUEUED'}}),error=>error.creationUncertain&&error.task_id==='task-one'&&error.creation_id==='kept-id');
 assert.equal(a.calls.length,0);
});
test('real failure stays explicit and carries the original task for manual retry',async()=>{
 const a=setup([],[],async()=>({id:'task-one',status:'FAILED',error:'preparation failed'}));
 await assert.rejects(a.predict('A',{name:'original.bmp'},.25,{model,creation_id:'kept-id',initial_task:{id:'task-one',status:'QUEUED'}}),error=>!error.creationUncertain&&error.task_id==='task-one'&&error.task_status==='FAILED');
 assert.equal(a.calls.length,0);
});
