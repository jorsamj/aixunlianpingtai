import test from 'node:test';
import assert from 'node:assert/strict';
import {negativePoolQuery,installNegativePoolRuntime} from '../../static/modules/negative-pool-runtime.js';

test('pool query preserves complete category/label/date/status filters for server all-ID selection',()=>{
 const q=negativePoolQuery({query:'雨天 图片',category_id:['a','b'],label:['person','fire'],joined_days:'7',joined_from:'2026-10-01',joined_to:'2026-10-28',review_status:'unknown'},3);
 assert.equal(q.get('query'),'雨天 图片');assert.deepEqual(q.getAll('category_id'),['a','b']);assert.deepEqual(q.getAll('label'),['person','fire']);assert.equal(q.get('joined_to'),'2026-10-28');assert.equal(q.get('review_status'),'unknown');assert.equal(q.get('page'),'3');
});

test('pool uses explicit owner hooks and rejects delayed previous-project responses',async()=>{
 const previous={window:globalThis.window,document:globalThis.document};
 let project='p1',resolve;const calls=[];const host={isConnected:true,innerHTML:''};
 const original=()=>{};
 globalThis.window={renderDatasets424:original};globalThis.document={getElementById:()=>host,addEventListener:()=>{}};
 try{
  const runtime=installNegativePoolRuntime({getState:()=>({page:'数据集'}),api:async url=>{calls.push(url);return url.includes('/categories')?{items:[]}:await new Promise(r=>resolve=r)},pid:()=>project,esc:String,toast:()=>{}});
  assert.equal(window.renderDatasets424,original,'original owner is never replaced');
  const pending=runtime.renderPool('materials');await new Promise(r=>setImmediate(r));project='p2';host.innerHTML='new project';resolve({items:[{id:'stale'}],total:1});await pending;
  assert.equal(host.innerHTML,'new project');assert.equal(runtime.active('materials'),false);assert.equal(calls.length,2);
 }finally{Object.assign(globalThis,previous)}
});
