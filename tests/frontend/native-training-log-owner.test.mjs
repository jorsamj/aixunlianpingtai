import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {requestText} from '../../frontend/src/app/http.ts';

const text=(body,status=200,headers={'content-type':'text/plain'})=>new Response(body,{status,headers});
function capture(respond){
  const calls=[];const original=globalThis.fetch;
  globalThis.fetch=async (url,options={})=>{
    calls.push({url:String(url),headers:options.headers||{},signal:options.signal});
    return respond(String(url),options);
  };
  return {calls,restore(){globalThis.fetch=original}};
}

test('training log reads go through the shared text request owner',async()=>{
  const {calls,restore}=capture(()=>text('epoch 1 loss 0.5'));
  try{
    const controller=new AbortController();
    const body=await requestText('/api/projects/p/jobs/job-1/log',{signal:controller.signal});
    assert.equal(body,'epoch 1 loss 0.5');
    assert.equal(calls[0].url,'/api/projects/p/jobs/job-1/log');
    assert.equal(calls[0].headers.Accept,'text/plain');
    assert.ok(calls[0].signal instanceof AbortSignal,'fetch must receive an abortable signal');
  }finally{restore()}
});

test('training log text errors stay readable and keep the HTTP status',async()=>{
  let restore=()=>{};
  try{
    ({restore}=capture(()=>text('日志文件读取失败',500)));
    const error=await requestText('/api/projects/p/jobs/job-1/log').then(()=>null,value=>value);
    assert.equal(error?.httpStatus,500);
    assert.match(String(error?.message),/日志文件读取失败/);
    restore();
    ({restore}=capture(()=>text(JSON.stringify({detail:'训练任务不存在'}),404,{'content-type':'application/json'})));
    const missing=await requestText('/api/projects/p/jobs/job-1/log').then(()=>null,value=>value);
    assert.equal(missing?.httpStatus,404);
    assert.match(String(missing?.message),/训练任务不存在/);
  }finally{restore()}
});

test('cancelled training log reads are not dispatched',async()=>{
  let fetched=0;const original=globalThis.fetch;
  globalThis.fetch=async ()=>{fetched+=1;return text('')};
  try{
    const controller=new AbortController();controller.abort();
    await assert.rejects(()=>requestText('/api/projects/p/jobs/job-1/log',{signal:controller.signal}),
      error=>error?.name==='AbortError');
    assert.equal(fetched,0);
  }finally{globalThis.fetch=original}
});

test('native training page owns its log read and lifecycle writes explicitly',async()=>{
  const source=await readFile(new URL('../../frontend/src/app/TrainingTasks.vue',import.meta.url),'utf8');
  assert.match(source,/import \{request,requestText\} from '\.\/http';/);
  assert.doesNotMatch(source,/withRequestDeadline/, 'log must not bypass the shared http owner');
  assert.doesNotMatch(source,/\bfetch\(/, 'training page must not issue bare fetch calls');
  assert.match(source,/requestText\(\s*`\/api\/projects\/\$\{encodeURIComponent\(projectId\)\}\/jobs\/\$\{encodeURIComponent\(id\)\}\/log`,{signal}/);
  assert.match(source,/function mutationSignal\(\)/);
  assert.match(source,/mutationController\?\.abort\(\);\s+mutationController=new AbortController\(\)/);
  assert.match(source,/onBeforeUnmount\(\(\)=>\{alive=false;controller\.abort\(\);mutationController\?\.abort\(\)/);
  assert.match(source,/pollController\?\.abort\(\);\s+pollController=new AbortController\(\)/);
  // Real backend-supported lifecycle actions only, gated by the legacy projection.
  assert.match(source,/trainingBatchActionEligible\(task\.value,'pause'\)/);
  assert.match(source,/trainingBatchActionEligible\(task\.value,'resume'\)/);
  assert.match(source,/trainingDisplayStatus\(task\.value\)/);
  assert.match(source,/trainingBatchActionEligible\(task\.value,'delete'\)/);
  assert.match(source,/runTrainingLifecycleAction\(projectId,id,action,signal\)/);
  assert.match(source,/deleteTrainingTaskRecord\(projectId,id,signal\)/);
  assert.match(source,/确认删除这条已结束训练任务记录/);
  // The old complete-training-entry link stays available.
  assert.match(source,/原完整训练任务页/);
  assert.match(source,/bridge\(''\)/);
});
