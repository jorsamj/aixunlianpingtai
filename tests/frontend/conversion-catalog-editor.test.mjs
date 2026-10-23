import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {catalogOperationId,installConversionCatalogRuntime} from '../../static/modules/conversion-catalog-runtime.js';
// Record identity, trusted suggestion and hidden-record tests moved to the server CRUD
// tests: the browser no longer owns record IDs, SDK suggestions or full-dictionary PUT.
test('operation identities are unique and safe for backend idempotency receipts',()=>{
 const ids=Array.from({length:60},()=>catalogOperationId(webcrypto));
 assert.equal(new Set(ids).size,60);assert.ok(ids.every(id=>/^catalog-[a-z0-9-]+$/.test(id)));
});
test('operation identities work on HTTP without randomUUID',()=>{
 const crypto={getRandomValues:a=>webcrypto.getRandomValues(a)};
 const ids=Array.from({length:60},()=>catalogOperationId(crypto));
 assert.equal(new Set(ids).size,60);assert.ok(ids.every(id=>/^catalog-[a-f0-9]{32}$/.test(id)));
});
function harness(api){
 const slots=new Map(),listeners=[];
 const element=()=>({innerHTML:'',textContent:'',setAttribute(){},options:[{}],insertAdjacentHTML(){}});
 const host={isConnected:true,innerHTML:'',querySelector(key){if(!slots.has(key))slots.set(key,element());return slots.get(key)},querySelectorAll(){return []},addEventListener(type,handler,options){listeners.push({type,handler,signal:options.signal})}};
 const state={page:'部署资源',project:{id:'p'}};
 const runtime=installConversionCatalogRuntime({api,getState:()=>state,window:{crypto:webcrypto},document:{querySelector(){return null}},modal(){},closeModal(){}});
 return {runtime,host,state,slots,listeners};
}
test('leaving ignores late server results and aborts owned listeners',async()=>{
 let finish,calls=0;const h=harness(()=>{calls++;return new Promise(resolve=>finish=resolve)});
 const mounted=h.runtime.mount(h.host);h.runtime.leave();
 finish({revision:3,templates:[],items:[{id:'x',name:'Late result'}],total:1,page:1,page_size:10});await mounted;
 assert.equal(calls,1);assert.ok(h.listeners.every(l=>l.signal.aborted));
 assert.equal(h.slots.has('[data-slot="vendors"]'),false);
});
test('remount aborts previous page and one owner issues only one query for an empty catalog',async()=>{
 let calls=0;const h=harness(async()=>{calls++;return {revision:0,templates:[],items:[],total:0,page:1,page_size:10}});
 await h.runtime.mount(h.host);const previous=h.listeners.map(l=>l.signal);await h.runtime.mount(h.host);
 assert.equal(calls,2);assert.ok(previous.every(s=>s.aborted));assert.equal(h.listeners.filter(l=>!l.signal.aborted).length,2);
 assert.match(h.slots.get('[data-slot="vendors"]').innerHTML,/暂无匹配记录/);
});


function dialogHarness(detail){
 const listeners=[],writes=[],record={id:'vendor-a',name:'Existing vendor',template_id:'rknn',enabled:true};let html='',area=null,wide=null;
 const element=()=>({innerHTML:'',textContent:'',setAttribute(){},options:[{}],insertAdjacentHTML(){}});
 const slots=new Map(),host={isConnected:true,querySelector(k){if(!slots.has(k))slots.set(k,element());return slots.get(k)},querySelectorAll(){return []},addEventListener(type,fn,options){listeners.push({type,fn,signal:options.signal})}};
 const dialog={addEventListener(){}};
 const doc={querySelector:()=>area,addEventListener(){}};
 const runtime=installConversionCatalogRuntime({api:async(url,options)=>{
   if(url.endsWith('/operations')){writes.push(JSON.parse(options.body));return {revision:2}}
   if(url.includes('/records/vendors/'))return typeof detail==='function'?detail(url):{item:record,revision:1,references:detail};
   return {revision:1,templates:[{id:'rknn',name:'RKNN'}],items:url.includes('entity=vendors')?[record]:[],total:1,page:1,page_size:10};
 },getState:()=>({page:'部署资源',project:{id:'p'}}),window:{crypto:webcrypto},document:doc,
 modal(_title,value,isWide){wide=isWide;html=value;area={closest:()=>dialog,addEventListener(){},querySelector(){return null},querySelectorAll(){return []}}},closeModal(){area=null}});
 const click=(action,id='vendor-a')=>listeners.find(x=>x.type==='click'&&!x.signal.aborted).fn({target:{closest:()=>({dataset:{catalogAction:action,entity:'vendors',id},isConnected:true})}});
 return {runtime,host,writes,click,get html(){return html},get wide(){return wide}};
}

test('unverified references keep ordinary edit available and never offer physical delete',async()=>{
 const h=dialogHarness({check_status:'UNVERIFIED',can_delete:false,reference_count:null,diagnostic:{code:'CATALOG_REFERENCE_CHECK_FAILED',detail:'TASK_JOB_MISSING_CONTRACT_INCOMPLETE: old/job.json'}});
 await h.runtime.mount(h.host);await h.click('edit');
 assert.equal(h.wide,false);assert.match(h.html,/历史引用未核验/);assert.match(h.html,/普通编辑可用/);assert.match(h.html,/删除和改挂暂不可用/);assert.match(h.html,/old\/job.json/);
 assert.match(h.html,/name="template_id" disabled/);assert.doesNotMatch(h.html,/name="name"[^>]*disabled/);
 h.runtime.leave();await h.runtime.mount(h.host);await h.click('delete');
 assert.doesNotMatch(h.html,/data-dialog-action="confirm-delete"/);assert.match(h.html,/历史引用未核验/);
 assert.equal(h.writes.length,0);
});

test('toggle cannot mutate another open draft when requested record did not open',async()=>{
 const h=dialogHarness({can_delete:false,reference_count:1});await h.runtime.mount(h.host);await h.click('edit');
 await h.click('disable','vendor-b');assert.equal(h.writes.length,0);
});

test('late detail failure cannot let an old toggle disable a newly opened draft',async()=>{
 let fail;const h=dialogHarness(url=>url.endsWith('/vendor-a')?new Promise((_,reject)=>fail=reject):Promise.resolve({item:{id:'vendor-b',name:'B',enabled:true},revision:2,references:{can_delete:false}}));
 await h.runtime.mount(h.host);const old=h.click('disable');h.runtime.leave();await h.runtime.mount(h.host);await h.click('edit','vendor-b');
 fail(new Error('old detail unavailable'));await old;assert.equal(h.writes.length,0);assert.match(h.html,/value="B"/);
});
