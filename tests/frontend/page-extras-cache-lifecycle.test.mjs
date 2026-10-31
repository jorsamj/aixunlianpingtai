import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=main.indexOf('const PAGE_EXTRAS_CACHE_TTL_MS');
const end=main.indexOf('window.PlatformCore.runtime.refreshPageExtras = refreshPageExtrasInBackground;',start);
assert.ok(start>=0&&end>start,'reuse the original page extras cache owner');

function owner(){
  const state={page:'模型配置',project:{id:'p1'},qualityCenterTab411:'overview'};
  const calls=[],errors=[];
  let generation=0;
  const win={
    loadPageExtras413:()=>new Promise(resolve=>calls.push(resolve)),
    patchModelPromptTemplatesV35:()=>true,
  };
  const scope={stats:()=>({generation})};
  const code=main.slice(start,end)+'\nreturn {refresh:refreshPageExtrasInBackground,cache:pageExtrasLoadedAt,inflight:pageExtrasInflight};';
  const runtime=new Function('state','window','pageRequestScope','notify','isPageNavigationCancelled',
    'navigationStabilityRuntime','renderCanonicalOwner','render',code)(
    state,win,scope,error=>errors.push(error),()=>false,{hasPageOwner:()=>false},()=>{},()=>{},
  );
  return {...runtime,state,calls,errors,navigate:page=>{generation++;state.page=page}};
}

test('failed page extras are not stamped fresh for five minutes',async()=>{
  const ctx=owner();
  const failed=ctx.refresh('模型配置');
  ctx.calls[0]({cacheable:false});
  await failed;
  assert.equal(ctx.cache.size,0);
  assert.equal(ctx.inflight.size,0);
  const retry=ctx.refresh('模型配置');
  assert.equal(ctx.calls.length,2,'revisit retries a failed read');
  ctx.calls[1]({cacheable:true});
  await retry;
  assert.equal(ctx.cache.size,1);
  assert.equal(ctx.refresh('模型配置'),null,'healthy cache is reused');
});

test('partial allSettled failure reports non-cacheable and preserves successful fields',async()=>{
  const from=app.indexOf('async function extras412(pageOverride){');
  const to=app.indexOf('window.loadPageExtras413=extras412;',from);
  assert.ok(from>=0&&to>from);
  const state={page:'质量中心',project:{id:'p1'},scenarioTestModels:[]};
  const calls=[],toasts=[];
  const api=url=>new Promise((resolve,reject)=>calls.push({url,resolve,reject}));
  const fn=new Function('state','api','toast','window',app.slice(from,to)+'\nreturn extras412;')(
    state,api,error=>toasts.push(error),{PageRequestScopeRuntime:{stats:()=>({generation:0})}},
  );
  const pending=fn('质量中心');
  calls.find(call=>call.url.includes('test_models')).resolve({items:[{id:'scenario'}]});
  calls.find(call=>call.url.includes('inference_envs')).reject(new Error('envs failed'));
  const result=await pending;
  assert.equal(result.cacheable,false);
  assert.equal(state.scenarioTestModels[0].id,'scenario');
  assert.deepEqual(toasts,['envs failed']);
});
