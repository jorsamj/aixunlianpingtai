import test from 'node:test';
import assert from 'node:assert/strict';
import {
  cancelAiTask, fetchAiTaskDetail, fetchAiTaskFailures, recoverAiTaskReview, retryAiTask,
} from '../../frontend/src/api/ai-task-actions.ts';

const signal=()=>new AbortController().signal;
const json=(body,status=200)=>new Response(JSON.stringify(body),
  {status,headers:{'content-type':'application/json'}});
function capture(respond){
  const calls=[];const original=globalThis.fetch;
  globalThis.fetch=async (url,options={})=>{
    calls.push({url:String(url),method:options.method||'GET',body:options.body??null,headers:options.headers||{}});
    return respond(String(url),options);
  };
  return {calls,restore(){globalThis.fetch=original}};
}

test('AI task write owner keeps the original v60 URLs, methods and retry body',async()=>{
  const {calls,restore}=capture(()=>json({id:'t',project_id:'p'}));
  try{
    await cancelAiTask('p','t',signal());
    await retryAiTask('p','t',signal());
    await retryAiTask('p','t',signal(),['img-1','img-2']);
    await recoverAiTaskReview('p','t',signal());
    assert.equal(new URL(calls[0].url,'https://local').pathname,'/api/v60/projects/p/annotation-tasks/t/cancel');
    assert.equal(calls[0].method,'POST');
    assert.equal(new URL(calls[1].url,'https://local').pathname,'/api/v60/projects/p/annotation-tasks/t/retry');
    assert.equal(calls[1].method,'POST');
    assert.equal(calls[1].body,null,'whole-task retry keeps the legacy empty body');
    assert.deepEqual(JSON.parse(String(calls[2].body)),{image_ids:['img-1','img-2']});
    assert.equal(new URL(calls[3].url,'https://local').pathname,
      '/api/v60/projects/p/annotation-tasks/t/review-completed');
    assert.equal(calls[3].method,'POST');
  }finally{restore()}
});

test('AI task detail and failure readers stay on reader_view endpoints',async()=>{
  const {calls,restore}=capture(url=>url.includes('/candidates?')
    ?json({ok:true,project_id:'p',task_id:'t',items:[],next_cursor:null,total:0,review_revision:1})
    :json({ok:true,project_id:'p',task:{id:'t',project_id:'p',status:'FAILED'}}));
  try{
    const task=await fetchAiTaskDetail('p','t',signal());
    assert.equal(task.id,'t');
    const failures=await fetchAiTaskFailures('p','t',signal());
    assert.equal(failures.task_id,'t');
    const detailUrl=new URL(calls[0].url,'https://local'),failureUrl=new URL(calls[1].url,'https://local');
    assert.equal(detailUrl.pathname,'/api/v60/projects/p/annotation-tasks/t');
    assert.equal(detailUrl.searchParams.get('reader_view'),'true');
    assert.equal(failureUrl.pathname,'/api/v60/projects/p/annotation-tasks/t/candidates');
    assert.equal(failureUrl.searchParams.get('reader_view'),'true');
    assert.equal(failureUrl.searchParams.get('filter'),'failed');
    assert.equal(failureUrl.searchParams.get('limit'),'12');
    assert.equal(failureUrl.searchParams.get('cursor'),null);
    await fetchAiTaskFailures('p','t',signal(),'c1');
    assert.equal(new URL(calls[2].url,'https://local').searchParams.get('cursor'),'c1');
  }finally{restore()}
});

test('AI task owner refuses foreign identities and surfaces readable HTTP errors',async()=>{
  let restore=()=>{};
  try{
    ({restore}=capture(()=>json({id:'t',project_id:'q'})));
    await assert.rejects(()=>cancelAiTask('p','t',signal()),/回执身份不一致/);
    restore();
    ({restore}=capture(()=>json({ok:true,project_id:'p',task:{id:'t',project_id:'q'}})));
    await assert.rejects(()=>fetchAiTaskDetail('p','t',signal()),/详情身份不一致/);
    restore();
    ({restore}=capture(()=>json({ok:true,project_id:'p',task_id:'t',
      items:[{image_id:'a',status:'success'}],next_cursor:null,total:1,review_revision:1})));
    await assert.rejects(()=>fetchAiTaskFailures('p','t',signal()),/失败分页身份不一致/);
    restore();
    ({restore}=capture(()=>json({detail:'仅未审核、尚未完成的 AI 标注任务可以继续生成'},409)));
    const error=await cancelAiTask('p','t',signal()).then(()=>null,value=>value);
    assert.equal(error?.httpStatus,409);
    assert.match(String(error?.message),/仅未审核/);
  }finally{restore()}
});

test('AI task requests are cancellable before dispatch',async()=>{
  let fetched=0;const original=globalThis.fetch;
  globalThis.fetch=async ()=>{fetched+=1;return json({})};
  try{
    const controller=new AbortController();controller.abort();
    await assert.rejects(()=>cancelAiTask('p','t',controller.signal),
      error=>error?.name==='AbortError');
    assert.equal(fetched,0,'cancel-aborted requests must not be dispatched');
  }finally{globalThis.fetch=original}
});
