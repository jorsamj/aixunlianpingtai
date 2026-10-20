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
