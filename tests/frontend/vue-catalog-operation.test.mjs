import test from 'node:test';
import assert from 'node:assert/strict';
import {submitCatalogOperation, recoverCatalogOperation} from '../../frontend/src/api/catalog-operation.ts';

const operation=()=>({entity:'vendors',action:'create',operation_id:'original-id',expected_revision:7,record:{name:'厂商',template_id:'rknn'}});
const result=op=>({ok:true,operation_id:op.operation_id,entity:op.entity,action:op.action,id:'server-id',item:{id:'server-id',name:'厂商'},revision:8});
test('lost POST reply is recovered through receipt without another POST or new identity',async()=>{
 const op=operation(),calls=[];
 const api={post:async packet=>{calls.push(packet);throw new TypeError('connection lost')},receipt:async id=>{calls.push(id);return result(op)}};
 assert.equal((await submitCatalogOperation(api,op)).revision,8);
 assert.deepEqual(calls,[op,'original-id']);
});
test('missing receipt requires explicit original-body replay, never an automatic second POST',async()=>{
 const op=operation(),calls=[];let committed=false;
 const api={post:async packet=>{calls.push(structuredClone(packet));if(!committed)throw new SyntaxError('malformed reply');return result(op)},receipt:async()=>{throw Object.assign(new Error('missing'),{code:'CATALOG_OPERATION_NOT_FOUND',httpStatus:404})}};
 await assert.rejects(()=>submitCatalogOperation(api,op),/回执|确认/);
 assert.equal(calls.length,1);committed=true;
 await recoverCatalogOperation(api,op,true);
 assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);
});
test('definite revision rejection remains visible and is never blindly replayed',async()=>{
 const op=operation();let receipts=0;
 await assert.rejects(()=>submitCatalogOperation({post:async()=>{throw Object.assign(new Error('revision changed'),{code:'CATALOG_REVISION_CONFLICT',httpStatus:409})},receipt:async()=>{receipts++}},op),e=>e.code==='CATALOG_REVISION_CONFLICT');
 assert.equal(receipts,0);
});
test('wrong receipt identity or invalid successful body cannot be treated as saved',async()=>{
 const op=operation();
 await assert.rejects(()=>submitCatalogOperation({post:async()=>({...result(op),operation_id:'different'}),receipt:async()=>({...result(op),operation_id:'different'})},op),/回执|确认|身份/);
});
