import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
const start=source.indexOf('  window.runBenchBatch64=async function('),end=source.indexOf('  window.markBenchReview64=',start);
for(const mode of ['a','compare'])test(`stop subsequent work preserves the completed A result in ${mode} mode`,async()=>{
 let resolve;const first=new Promise(yes=>resolve=yes),state={benchFiles64:[{name:'first.bmp'}]},button={isConnected:true},patches=[];let submissions=0;
 const window={benchPredictOne:async()=>{submissions++;return first;}};
 vm.runInNewContext(source.slice(start,end),{window,state,crypto:globalThis.crypto,clearCreationVerification64(){},saveCreationMetadata64(){},pid:()=> 'p',selectedModel64:side=>({version_id:side}),renderBenchBatch64(){if(state.benchBatch64?.results)patches.push(state.benchBatch64.results[0].status)},patchBenchRow64(){patches.push(state.benchBatch64.results[0].status)},summary64(){},toast(){},document:{getElementById:id=>id==='benchMode64'?{value:mode}:id==='benchConf'?{value:'.25'}:id==='benchRun64'?button:{value:'0'}}});
 const running=window.runBenchBatch64();assert.equal(submissions,1);state.benchBatch64.cancelled=true;resolve({task_id:'persisted-A',r:{detections:[]}});await running;
 const run=state.benchBatch64,row=run.results[0];assert.equal(row.a.task_id,'persisted-A');assert.equal(row.status,mode==='a'?'done':'partial');assert.equal(run.failed,0);assert.equal(submissions,1);assert.equal(run.completed,mode==='a'?1:0);assert.ok(patches.includes(row.status));assert.equal(button.disabled,false);
});
