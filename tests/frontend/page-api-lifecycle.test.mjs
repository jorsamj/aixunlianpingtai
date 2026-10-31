import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PageRequestScope, isPageNavigationCancelled} from '../../static/modules/page-request-scope.js';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('const api=(url,opt={})=>{');
const end=source.indexOf('// Shared request identity for ordinary image uploads',start);
assert.ok(start>=0&&end>start,'test the real generic app API owner');

function makeApi(scope){
  const runtime={runPageRead:(url,opt,operation)=>scope.runPageRead(url,opt,operation)};
  return new Function('window','fetch','FormData','preparePlainUpload411','finishPlainUpload411',
    source.slice(start,end)+'\nreturn api;')(
      {PageRequestScopeRuntime:runtime},scope.fetch.bind(scope),FormData,()=>null,()=>{},
    );
}

async function flushBody(){
  for(let n=0;n<6;n++)await Promise.resolve();
}

test('page GET retires while a response body ignores AbortSignal',async()=>{
  let finishBody,reading=false;
  const scope=new PageRequestScope({page:'质量中心',fetchImpl:async()=>({
    ok:true,headers:{get:()=> 'application/json'},
    json:()=>{reading=true;return new Promise(resolve=>{finishBody=resolve})},
  })});
  const api=makeApi(scope);
  let finalized=0;
  const request=api('/api/v44/projects/p/quality-center').finally(()=>{finalized++});
  await flushBody();
  assert.equal(reading,true,'response headers have already resolved');
  scope.navigate('算法列表');
  await assert.rejects(request,isPageNavigationCancelled);
  assert.equal(finalized,1);
  finishBody({stale:true});
  assert.equal(scope.page,'算法列表');
});

test('new A owner may read normally after a retired response body',async()=>{
  const bodies=[];
  const scope=new PageRequestScope({page:'A',fetchImpl:async()=>({
    ok:true,headers:{get:()=> 'application/json'},
    json:()=>new Promise(resolve=>bodies.push(resolve)),
  })});
  const api=makeApi(scope);
  const old=api('/api/demo');
  await flushBody();
  scope.navigate('B');scope.navigate('A');
  const latest=api('/api/demo');
  await flushBody();
  assert.equal(bodies.length,2);
  bodies[1]({id:'current-A'});
  assert.deepEqual(await latest,{id:'current-A'});
  bodies[0]({id:'retired-A'});
  await assert.rejects(old,isPageNavigationCancelled);
});

test('caller signal, bootstrap and mutation response bodies retain their own owner',async()=>{
  const bodies=[];
  const scope=new PageRequestScope({page:'A',fetchImpl:async(_url,init={})=>({
    ok:true,headers:{get:()=> 'application/json'},
    json:()=>new Promise(resolve=>bodies.push({resolve,signal:init.signal})),
  })});
  const api=makeApi(scope);
  const caller=new AbortController();
  const requests=[
    api('/api/custom',{signal:caller.signal}),
    api('/api/v53/bootstrap/snapshot'),
    api('/api/projects/p/train/start',{method:'POST',body:'{}'}),
  ];
  await flushBody();
  assert.equal(bodies.length,3);
  scope.navigate('B');
  assert.equal(caller.signal.aborted,false);
  bodies.forEach((body,index)=>body.resolve({index}));
  assert.deepEqual(await Promise.all(requests),[{index:0},{index:1},{index:2}]);
  assert.equal(scope.abortedRequests,0);
});
