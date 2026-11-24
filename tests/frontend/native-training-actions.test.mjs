import test from 'node:test';
import assert from 'node:assert/strict';
import {deleteTrainingTaskRecord,runTrainingLifecycleAction} from '../../frontend/src/api/training-actions.ts';
import {trainingBatchActionEligible} from '../../static/modules/training-task-runtime.js';
import {trainingDisplayStatus} from '../../static/modules/task-runtime-truth.js';

const signal=()=>new AbortController().signal;
const json=(body,status=200)=>new Response(JSON.stringify(body),
  {status,headers:{'content-type':'application/json'}});
function capture(respond){
  const calls=[];const original=globalThis.fetch;
  globalThis.fetch=async (url,options={})=>{
    calls.push({url:String(url),method:options.method||'GET',body:options.body??null});
    return respond(String(url),options);
  };
  return {calls,restore(){globalThis.fetch=original}};
}

test('training lifecycle owner posts the real v48 pause/resume/promote endpoints',async()=>{
  const {calls,restore}=capture(()=>json({status:'paused'}));
  try{
    await runTrainingLifecycleAction('p','job-1','pause',signal());
    await runTrainingLifecycleAction('p','job-1','resume',signal());
    await runTrainingLifecycleAction('p','job-1','promote',signal());
    assert.deepEqual(calls.map(call=>[new URL(call.url,'https://local').pathname,call.method]),[
      ['/api/v48/projects/p/jobs/job-1/pause','POST'],
      ['/api/v48/projects/p/jobs/job-1/resume','POST'],
      ['/api/v48/projects/p/jobs/job-1/promote','POST'],
    ]);
    assert.deepEqual(calls.map(call=>call.body),[null,null,null]);
  }finally{restore()}
});

test('training record delete uses the v12 DELETE endpoint and requires an ok receipt',async()=>{
  const {calls,restore}=capture(()=>json({ok:true}));
  try{
    await deleteTrainingTaskRecord('p','job-1',signal());
    assert.equal(new URL(calls[0].url,'https://local').pathname,'/api/v12/projects/p/jobs/job-1');
    assert.equal(calls[0].method,'DELETE');
  }finally{restore()}
  const invalid=capture(()=>json({ok:false}));
  try{
    await assert.rejects(()=>deleteTrainingTaskRecord('p','job-1',signal()),/删除任务回执不完整/);
  }finally{invalid.restore()}
  const rejected=capture(()=>json({detail:'训练任务已经结束，不能再次停止'},409));
  try{
    const conflict=await deleteTrainingTaskRecord('p','job-1',signal()).then(()=>null,value=>value);
    assert.equal(conflict?.httpStatus,409);
  }finally{rejected.restore()}
  const failure=capture(()=>json({detail:'训练任务已经结束，不能再次停止'},409));
  try{
    const error=await runTrainingLifecycleAction('p','job-1','pause',signal())
      .then(()=>null,value=>value);
    assert.equal(error?.httpStatus,409);
    assert.match(String(error?.message),/已经结束/);
  }finally{failure.restore()}
});

test('native training actions reuse the original task-wall eligibility projection',()=>{
  assert.equal(trainingDisplayStatus({status:'RUNNING',phase:'training'}),'running');
  assert.equal(trainingDisplayStatus({status:'PAUSED',phase:'paused'}),'paused');
  assert.equal(trainingBatchActionEligible({status:'RUNNING'},'pause'),true);
  assert.equal(trainingBatchActionEligible({status:'PAUSED'},'pause'),false);
  assert.equal(trainingBatchActionEligible({status:'PAUSED'},'resume'),true);
  assert.equal(trainingBatchActionEligible({status:'RUNNING'},'resume'),false);
  assert.equal(trainingBatchActionEligible({status:'QUEUED'},'delete'),false);
  assert.equal(trainingBatchActionEligible({status:'RUNNING'},'delete'),false);
  assert.equal(trainingBatchActionEligible({status:'SUCCEEDED'},'delete'),true);
  assert.equal(trainingBatchActionEligible({status:'FAILED'},'delete'),true);
});
