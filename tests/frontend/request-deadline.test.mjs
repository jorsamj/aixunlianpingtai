import test from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../../static/modules/api.js';

test('deadline settles a permanently pending operation and aborts its signal',async()=>{
  let signal;
  await assert.rejects(api.withRequestDeadline(s=>{signal=s;return new Promise(()=>{})},{timeoutMs:5,label:'读取转换配置'}),error=>{
    assert.equal(error.code,'REQUEST_TIMEOUT');
    assert.equal(error.outcome,'READ_TIMEOUT');
    assert.match(error.message,/读取未完成/);
    assert.doesNotMatch(error.message,/提交结果/);
    return true;
  });
  assert.equal(signal.aborted,true);
});
test('mutation deadline is UNKNOWN, never a confirmed rejection',async()=>{
  await assert.rejects(api.withRequestDeadline(()=>new Promise(()=>{}),
    {timeoutMs:5,label:'训练创建',mutation:true}),error=>{
    assert.equal(error.code,'REQUEST_TIMEOUT');
    assert.equal(error.outcome,'UNKNOWN');
    assert.match(error.message,/勿直接重复提交/);
    return true;
  });
});
test('deadline covers decoding and preserves successful and HTTP error results',async()=>{
  assert.equal(await api.withRequestDeadline(async()=>42,{timeoutMs:50}),42);
  const error=Object.assign(new Error('HTTP 409'),{code:'HTTP_409'});
  await assert.rejects(api.withRequestDeadline(async()=>{throw error},{timeoutMs:50}),e=>e===error);
});
test('caller abort settles an operation even if fetch ignores its signal',async()=>{
  const controller=new AbortController();
  const pending=api.withRequestDeadline(()=>new Promise(()=>{}),{timeoutMs:1000,signal:controller.signal});
  controller.abort();
  await assert.rejects(pending,{name:'AbortError'});
});


test('ZIP inventory and status reads propagate finite cancellation without inventing a job',async()=>{
 const {listZipJobs,getZipJob}=await import('../../static/modules/zip-import-runtime.js');
 const signals=[];
 const fetchImpl=async(_url,{signal})=>{signals.push(signal);return Response.json({id:'known',items:[{id:'known'}]});};
 assert.deepEqual(await listZipJobs('p',{fetchImpl}),[{id:'known'}]);
 assert.equal((await getZipJob('p','known',{fetchImpl})).id,'known');
 assert.ok(signals.every(signal=>signal instanceof AbortSignal));
});
