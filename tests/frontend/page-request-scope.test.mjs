import test from 'node:test';
import assert from 'node:assert/strict';

import {PageRequestScope, isPageNavigationCancelled} from '../../static/modules/page-request-scope.js';

function abortError() {
  const error = new Error('aborted');
  error.name = 'AbortError';
  return error;
}

function deferredFetch() {
  const calls = [];
  const fetchImpl = (input, init = {}) => {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
    const call = {input, init, resolve, reject};
    calls.push(call);
    init.signal?.addEventListener('abort', () => reject(abortError()), {once: true});
    return promise;
  };
  return {calls, fetchImpl};
}

test('same-page API GET receives the page abort signal and completes normally', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks');

  assert.equal(fake.calls.length, 1);
  assert.ok(fake.calls[0].init.signal instanceof AbortSignal);
  assert.equal(fake.calls[0].init.signal.aborted, false);

  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});

test('navigating aborts old page GET and quarantines its continuation', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks');

  scope.navigate('数据集');
  assert.equal(fake.calls[0].init.signal.aborted, true);

  let finalized = false;
  await assert.rejects(request.finally(() => {finalized = true;}), isPageNavigationCancelled);
  assert.equal(finalized, true);
  assert.equal(scope.page, '数据集');
  assert.equal(scope.abortedRequests, 1);
});

test('native fetch rejection with the exact navigation reason is quarantined too', async () => {
  const scope = new PageRequestScope({page:'训练资源',fetchImpl:(_url,{signal})=>new Promise((_resolve,reject)=>{
    signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  })});
  const request=scope.fetch('/api/local_models');
  scope.navigate('模型配置');
  await assert.rejects(request, error => error.code === 'PAGE_NAVIGATION_CANCELLED');
  assert.equal(isPageNavigationCancelled('读取失败：__PAGE_NAVIGATION_CANCELLED__'), true);
  assert.equal(scope.abortedRequests,1);
  const error=new Error('real network failure');
  const active=new PageRequestScope({page:'模型配置',fetchImpl:async()=>{throw error;}});
  await assert.rejects(active.fetch('/api/model-configs'),error);
});

test('a synchronous transport failure settles without leaving an orphan retirement promise',async()=>{
  const error=new Error('transport unavailable');
  const scope=new PageRequestScope({page:'A',fetchImpl:()=>{throw error;}});
  await assert.rejects(scope.fetch('/api/data'),error);
  scope.navigate('B');
  assert.equal(scope.abortedRequests,0);
});

test('POST mutations are not automatically cancelled by page navigation', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/tasks', {method: 'POST', body: '{}'});

  assert.equal(fake.calls[0].init.signal, undefined);
  scope.navigate('数据集');

  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});

test('non-API requests are left untouched', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '训练任务', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/static/app.js');

  assert.equal(fake.calls[0].init.signal, undefined);
  const response = {ok: true};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
});

test('bootstrap lifecycle GETs survive page navigation and are not page-scoped', async () => {
  const fake = deferredFetch();
  const scope = new PageRequestScope({page: '算法列表', fetchImpl: fake.fetchImpl});
  const request = scope.fetch('/api/v53/bootstrap/snapshot');

  assert.equal(fake.calls.length, 1);
  assert.equal(fake.calls[0].init.signal, undefined);

  scope.navigate('数据集');
  const response = {ok: true, project: {id: 'project-1'}};
  fake.calls[0].resolve(response);
  assert.equal(await request, response);
  assert.equal(scope.page, '数据集');
  assert.equal(scope.abortedRequests, 0);
});

test('a native response arriving after navigation cannot be consumed', async () => {
  let resolve;
  const scope = new PageRequestScope({page:'A',fetchImpl:()=>new Promise(r=>{resolve=r;})});
  const request = scope.fetch('/api/data');
  scope.navigate('B');
  resolve({ok:true});
  await assert.rejects(request, isPageNavigationCancelled);
  assert.equal(scope.abortedRequests, 1);
});

test('caller-owned signal still passes through and is not a navigation cancellation', async () => {
  const fake=deferredFetch();
  const scope=new PageRequestScope({page:'A',fetchImpl:fake.fetchImpl});
  const controller=new AbortController();
  const request=scope.fetch('/api/data',{signal:controller.signal});
  controller.abort();
  await assert.rejects(request,e=>e.name==='AbortError'&&!isPageNavigationCancelled(e));
  assert.equal(scope.abortedRequests,0);
});

test('Request input retains caller-owned signal across navigation', async () => {
  const fake=deferredFetch();
  const scope=new PageRequestScope({page:'算法列表',fetchImpl:fake.fetchImpl});
  const controller=new AbortController();
  const input=new Request('https://example.test/api/projects/p/algorithms',{signal:controller.signal});
  const responsePromise=scope.fetch(input);
  assert.equal(fake.calls.length,1);
  assert.equal(fake.calls[0].input,input);
  assert.equal(fake.calls[0].init.signal,undefined);
  scope.navigate('数据集');
  assert.equal(input.signal.aborted,false);
  fake.calls[0].resolve({ok:true});
  assert.equal((await responsePromise).ok,true);
  assert.equal(scope.abortedRequests,0);
});

test('Request caller abort is preserved instead of recast as page navigation', async () => {
  const controller=new AbortController();
  const input=new Request('https://example.test/api/projects/p/algorithms',{signal:controller.signal});
  const scope=new PageRequestScope({page:'算法列表',fetchImpl:(request,init)=>new Promise((_resolve,reject)=>{
    assert.equal(init.signal,undefined);
    request.signal.addEventListener('abort',()=>reject(abortError()),{once:true});
  })});
  const pending=scope.fetch(input);
  controller.abort('caller-stop');
  await assert.rejects(pending,error=>error.name==='AbortError'&&!isPageNavigationCancelled(error));
  assert.equal(scope.abortedRequests,0);
});

test('page retirement settles a GET when the transport ignores AbortSignal indefinitely', async () => {
  let fetchSignal;
  const scope = new PageRequestScope({page:'算法列表',fetchImpl:(_url,{signal})=>{
    fetchSignal=signal;
    return new Promise(()=>{});
  }});
  let finalized=0;
  const request=scope.fetch('/api/projects/algorithms').finally(()=>{finalized++;});
  scope.navigate('训练任务');
  await assert.rejects(request,isPageNavigationCancelled);
  assert.equal(fetchSignal.aborted,true);
  assert.equal(finalized,1);
  assert.equal(scope.abortedRequests,1);
});

test('A→B→C→A retires every ignored old read and permits the new owner to finish',async()=>{
  const pending=[];
  const scope=new PageRequestScope({page:'A',fetchImpl:(url,{signal})=>new Promise(resolve=>{
    pending.push({url,signal,resolve});
  })});
  const old=[],finalized=[];
  for(const next of ['B','C','A']){
    const index=old.length;
    old.push(scope.fetch('/api/page-data').finally(()=>{finalized[index]=(finalized[index]||0)+1;}));
    scope.navigate(next);
  }
  const latest=scope.fetch('/api/page-data');
  await Promise.all(old.map(request=>assert.rejects(request,isPageNavigationCancelled)));
  assert.deepEqual(finalized,[1,1,1]);
  assert.equal(scope.abortedRequests,3);
  pending.slice(0,3).forEach(row=>row.resolve({stale:true}));
  pending[3].resolve({stale:false,id:'new-A'});
  assert.deepEqual(await latest,{stale:false,id:'new-A'});
});

test('a caller-owned POST remains pending across navigation until its own transport resolves',async()=>{
  let resolve;
  const scope=new PageRequestScope({page:'A',fetchImpl:()=>new Promise(r=>{resolve=r})});
  const request=scope.fetch('/api/projects/p/train/start',{method:'POST',body:'{}'});
  scope.navigate('B');
  resolve({ok:true,task_id:'existing-task'});
  assert.deepEqual(await request,{ok:true,task_id:'existing-task'});
  assert.equal(scope.abortedRequests,0);
});
