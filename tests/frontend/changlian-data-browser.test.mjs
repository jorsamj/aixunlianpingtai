import test from 'node:test';
import assert from 'node:assert/strict';

import {
  installChangLianDataBrowserRuntime,
  productIdentity,
  providerItems,
  versionIdentity,
  weightIdentity,
  weightRemoteLink,
  remoteField, tagsView, providerDetail,
} from '../../static/modules/changlian-data-browser.js';

test('provider response normalization keeps official products versions and weights', () => {
  assert.deepEqual(providerItems({response: {code: 0, data: [{productId: 1}]}}), [{productId: 1}]);
  assert.deepEqual(providerItems({response: {data: {records: [{algoVersionId: 2}]}}}), [{algoVersionId: 2}]);
  assert.equal(productIdentity({productId: 11}), '11');
  assert.equal(versionIdentity({algoVersionId: 22}), '22');
  assert.equal(weightIdentity({weightId: 33}), '33');
  assert.equal(weightRemoteLink({filePath: 'https://oss.example/model.rknn'}), 'https://oss.example/model.rknn');
  assert.equal(weightRemoteLink({filePath: '/private/path/model.rknn'}), '');
});

test('changlian data browser is manual-only and reads product version weight truth on refresh', async () => {
  const state = {page: '畅联云数据'};
  const urls = [];
  const request = async url => {
    urls.push(url);
    if (url.endsWith('/products?status=1')) return {response: {data: [{productId: 'p1', productName: '抽烟检测', status: 1}]}};
    if (url.endsWith('/products?status=0')) return {response: {data: []}};
    if (url.endsWith('/versions/by-product/p1')) return {response: {data: [{algoVersionId: 'v1', versionName: 'V1'}]}};
    if (url.endsWith('/weights/by-version/v1')) return {response: {data: [{weightId: 'w1', fileName: 'model.rknn', filePath: 'https://oss.example/model.rknn'}]}};
    throw new Error(`unexpected URL: ${url}`);
  };
  const runtime = installChangLianDataBrowserRuntime({getState: () => state, request, document: null});
  assert.deepEqual(urls, []);
  assert.equal(runtime.snapshot().loaded, false);

  const result = await runtime.refresh();
  assert.equal(result.loaded, true);
  assert.deepEqual(urls, [
    '/api/v63/external-algorithm-platform/provider/products?status=1',
    '/api/v63/external-algorithm-platform/provider/products?status=0',
    '/api/v63/external-algorithm-platform/provider/versions/by-product/p1',
    '/api/v63/external-algorithm-platform/provider/weights/by-version/v1',
  ]);
  assert.equal(result.products[0].versions[0].weights[0].weightId, 'w1');
  assert.equal(urls.some(url => /sync|POST|PUT|DELETE/i.test(url)), false);
  runtime.destroy();
});


test('weight details are click-only and preserve int64 and successful snapshot cache', async()=>{
  const calls=[],id='2112456166616469504';
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{
    calls.push(url);
    if(url.includes('/weights/'))return {response:{code:200,data:{weightId:id,tags:['Car'],imageWidth:640,imageHeight:384}}};
    return {response:{data:[]}};
  }});
  assert.deepEqual(calls,[]);
  const first=await runtime.openWeightDetails({weightId:id});
  assert.deepEqual(first.data.tags,['Car']);
  assert.equal(first.data.weightId,id);
  await runtime.openWeightDetails({weightId:id});
  assert.equal(calls.length,1);
  await runtime.openWeightDetails({weightId:id},{withTags:true});
  assert.equal(calls.at(-1),'/api/v63/external-algorithm-platform/provider/weights/'+id+'?withTags=true');
  runtime.destroy();
});


for(const [input,state] of [[{tags:['Car','smoke']},'returned'],[{tags:[]},'empty'],[{tags:null},'null'],[{},'missing'],[{tags:''},'invalid']])test(`tags retain remote semantic state ${state}`,()=>{
  const view=tagsView(input);assert.equal(view.state,state);if(state==='returned')assert.deepEqual(view.items,['Car','smoke']);
});
test('remote fields distinguish absent null empty string and empty array and preserve raw bytes',()=>{
  assert.equal(remoteField({},'remark'),'未返回');assert.match(remoteField({remark:null},'remark'),/null/);
  assert.equal(remoteField({remark:''},'remark'),'空字符串');assert.match(remoteField({remark:[]},'remark'),/空数组/);
  assert.equal(remoteField({fileSize:1048576},'fileSize'),'1 MB（1048576 字节）');assert.equal(remoteField({delFlag:2},'delFlag'),'已删除（2）');
  assert.equal(weightRemoteLink({filePath:'https://'}),'');assert.equal(weightRemoteLink({filePath:'https://good.test\\evil'}),'');
});
test('official withTags pagination finds exact Weight on a later page without merging base data',async()=>{
  const id='2112456166616469504',version='2109729657292197888',calls=[];
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{
    calls.push(url);
    if(!url.includes('/page?'))return {response:{code:200,data:{weightId:id,algoVersionId:version,fileName:'best.bmodel'}}};
    const q=new URL('https://local'+url).searchParams;assert.equal(q.get('withTags'),'true');assert.equal(q.get('algoVersionId'),version);
    return {response:{code:200,total:51,data:q.get('pageNum')==='1'?Array.from({length:50},(_,i)=>({weightId:String(i+1),tags:['unrelated']})):[{weightId:id,algoVersionId:version,tags:['Car']}]}};
  }});
  const result=await runtime.openWeightDetails({weightId:id,versionId:version});assert.equal(calls.length,3);
  assert.equal(Object.hasOwn(result.data,'tags'),false);assert.deepEqual(result.tagsEvidence.data.tags,['Car']);assert.match(result.tagsEvidence.source,/withTags=true/);runtime.destroy();
});
test('failed Tags query preserves base detail and error and retries only on explicit request',async()=>{
  const id='21';let calls=0;
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{
    calls++;if(url.includes('/page?'))throw new Error('HTTP 400 withTags unsupported');return {response:{code:200,data:{weightId:id,algoVersionId:'22'}}};
  }});
  const result=await runtime.openWeightDetails({weightId:id});assert.match(result.tagsError,/unsupported/);assert.equal(result.data.weightId,id);assert.equal(calls,2);
  await runtime.openWeightDetails({weightId:id},{force:true});assert.equal(calls,4);runtime.destroy();
});
test('identity conflicts stop Tags lookup and never overwrite list snapshot',async()=>{
  const calls=[];const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{calls.push(url);return {response:{code:200,data:{weightId:'11',algoVersionId:'99'}}}}});
  const result=await runtime.openWeightDetails({weightId:'11',versionId:'22'});assert.equal(result.issues.length,1);assert.equal(calls.length,1);assert.equal(runtime.snapshot().loaded,false);runtime.destroy();
});
test('duplicate clicks share one request and late responses cannot replace active Weight',async()=>{
  const pending=new Map(),calls=[];const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:url=>{calls.push(url);return new Promise(resolve=>pending.set(url.split('/').at(-1),resolve))}});
  const first=runtime.openWeightDetails({weightId:'11'}),again=runtime.openWeightDetails({weightId:'11'}),second=runtime.openWeightDetails({weightId:'22'});
  assert.equal(calls.length,2);pending.get('22')({response:{code:200,data:{weightId:'22',tags:['Car']}}});await second;
  pending.get('11')({response:{code:200,data:{weightId:'11',tags:[]}}});await Promise.all([first,again]);assert.equal(runtime.detailSnapshot().result.data.weightId,'22');runtime.destroy();
});
test('refresh invalidates detail cache without preloading any details',async()=>{
  let reads=0;const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{if(url.includes('/weights/')){reads++;return {response:{code:200,data:{weightId:'11',tags:[]}}}}return {response:{data:[]}}}});
  await runtime.openWeightDetails({weightId:'11'});await runtime.refresh();assert.equal(reads,1);await runtime.openWeightDetails({weightId:'11'});assert.equal(reads,2);runtime.destroy();
});
test('leave and destroy fence in-flight results and invalid IDs never request',async()=>{
  const state={page:'畅联云数据'};let resolve,calls=0;const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>state,request:()=>{calls++;return new Promise(r=>resolve=r)}});
  await assert.rejects(runtime.openWeightDetails({weightId:'1/other'}),/int64/);assert.equal(calls,0);
  const pending=runtime.openWeightDetails({weightId:'11'});runtime.leave();state.page='算法列表';runtime.destroy();resolve({response:{code:200,data:{weightId:'11',tags:['Car']}}});await pending;assert.equal(runtime.detailSnapshot(),null);
});
test('business failure and null results remain explicit and errors are never cached',async()=>{
  assert.throws(()=>providerDetail({response:{code:500,msg:'Token expired'}}),/Token expired/);
  let calls=0;const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async()=>{calls++;if(calls===1)throw new Error('timeout');return {response:{code:200,data:null}}}});
  await assert.rejects(runtime.openWeightDetails({weightId:'11'}),/timeout/);const result=await runtime.openWeightDetails({weightId:'11'});assert.equal(result.data,null);assert.equal(calls,2);runtime.destroy();
});


test('superseded detail does not start late pagination',async()=>{
  let resolve;const calls=[];
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:url=>{calls.push(url);if(url.endsWith('/11'))return new Promise(r=>resolve=r);return Promise.resolve({response:{code:200,data:{weightId:'22',tags:[]}}})}});
  const old=runtime.openWeightDetails({weightId:'11',versionId:'33'});await runtime.openWeightDetails({weightId:'22'});
  resolve({response:{code:200,data:{weightId:'11',algoVersionId:'33'}}});await old;assert.equal(calls.length,2);runtime.destroy();
});
test('detail basic differences stay distinct from list evidence',async()=>{
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async()=>({response:{code:200,data:{weightId:'11',fileName:'new.bmodel',tags:['Car']}}})});
  const result=await runtime.openWeightDetails({weightId:'11',listWeight:{fileName:'old.bmodel'}});
  assert.match(result.listDifferences[0],/old.bmodel.*new.bmodel/);assert.equal(result.data.fileName,'new.bmodel');runtime.destroy();
});


test('late failed UI request cannot toast on a different page',async()=>{
  const state={page:'畅联云数据'},notes=[];let click,reject;
  const root={isConnected:true,addEventListener(){},innerHTML:''};
  const view={innerHTML:'',addEventListener(type,fn){click=fn},removeEventListener(){},contains(){return true}};
  const doc={getElementById:()=>view,querySelector:()=>root};
  const runtime=installChangLianDataBrowserRuntime({document:doc,getState:()=>state,modal(){},closeModal(){},notify:m=>notes.push(m),request:async url=>{
    if(url.endsWith('/products?status=1'))return {response:{data:[{productId:'1'}]}};
    if(url.endsWith('/products?status=0'))return {response:{data:[]}};
    if(url.includes('/versions/'))return {response:{data:[{algoVersionId:'2'}]}};
    if(url.includes('/by-version/'))return {response:{data:[{weightId:'3'}]}};
    return new Promise((resolve,r)=>reject=r);
  }});
  await runtime.refresh();notes.length=0;
  click({target:{closest:()=>({hasAttribute:()=>false,dataset:{cldbProduct:'1',cldbVersion:'2',cldbWeight:'3'}})}});
  runtime.leave();state.page='算法列表';reject(new Error('late timeout'));await new Promise(r=>setImmediate(r));
  assert.deepEqual(notes,[]);runtime.destroy();
});


test('conflicting tags from list and getInfo are diagnostic facts not silently merged',async()=>{
  const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async()=>({response:{code:200,data:{weightId:'11',tags:['Car']}}})});
  const result=await runtime.openWeightDetails({weightId:'11',listWeight:{tags:['car']}});
  assert.equal(result.listDifferences.length,1);assert.deepEqual(result.data.tags,['Car']);assert.match(result.listDifferences[0],/car.*Car/);runtime.destroy();
});


for(const [scenario,second,total,message] of [
  ['repeated',Array.from({length:50},(_,i)=>({weightId:String(i+1)})),101,/重复返回/],
  ['premature-empty',[],101,/提前返回空页/],
  ['duplicate-id',[{weightId:'99'},{weightId:'99'}],101,/重复 Weight ID/],
])test(`Tags pagination stops safely on ${scenario}`,async()=>{
  let page=0;const runtime=installChangLianDataBrowserRuntime({document:null,getState:()=>({page:'畅联云数据'}),request:async url=>{
    if(!url.includes('/page?'))return {response:{code:200,data:{weightId:'99',algoVersionId:'100'}}};
    page++;return {response:{code:200,total,data:page===1?Array.from({length:50},(_,i)=>({weightId:String(i+1)})):second}};
  }});
  const result=await runtime.openWeightDetails({weightId:'99'});assert.match(result.tagsError,message);assert.equal(page,2);runtime.destroy();
});
