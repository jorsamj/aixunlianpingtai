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

test('category dictionary is shared across pool page refreshes without hiding list requests',async()=>{
 const previous={window:globalThis.window,document:globalThis.document};
 let categories=0,lists=0;
 const host={isConnected:true,innerHTML:'',querySelectorAll:()=>[]};
 globalThis.document={getElementById:()=>host,addEventListener:()=>{}};
 globalThis.window={renderDatasets424:()=>window.NegativePoolRuntime.renderPool('materials')};
 try{
   const runtime=installNegativePoolRuntime({
     getState:()=>({page:'数据集',labels:[]}),pid:()=> 'p1',esc:String,toast:()=>{},
     api:async(url,options={})=>{
       if(url.includes('/categories')){categories++;return {items:[{id:'a',name:'分类A'}]}}
       lists++;assert.ok(options.signal instanceof AbortSignal);
       return {items:[],total:0};
     }
   });
   await runtime.open();
   await runtime.refresh();
   assert.equal(categories,1);
   assert.equal(lists,2);
 }finally{Object.assign(globalThis,previous)}
});

test('identical pool queries share inflight; leaving owner aborts old read without repainting',async()=>{
 const previous={window:globalThis.window,document:globalThis.document};
 let resolve,lists=0,signal;
 const host={isConnected:true,innerHTML:'',querySelectorAll:()=>[]};
 globalThis.document={getElementById:()=>host,addEventListener:()=>{}};
 globalThis.window={renderDatasets424:()=>window.NegativePoolRuntime.renderPool('materials')};
 try{
   const runtime=installNegativePoolRuntime({
     getState:()=>({page:'数据集',labels:[]}),pid:()=> 'p1',esc:String,toast:()=>{},
     api:(url,options={})=>{
       if(url.includes('/categories'))return Promise.resolve({items:[]});
       lists++;signal=options.signal;
       return lists===1?Promise.resolve({items:[],total:0}):new Promise(r=>{resolve=r});
     }
   });
   await runtime.open();
   const first=runtime.refresh();
   const second=runtime.refresh();
   assert.equal(first,second);
   await new Promise(r=>setImmediate(r));
   assert.equal(lists,2);
   runtime.beforeNavigate('算法列表');
   assert.equal(signal.aborted,true);
   host.innerHTML='new page';
   resolve({items:[{id:'old'}],total:1});
   await first;
   assert.equal(host.innerHTML,'new page');
 }finally{Object.assign(globalThis,previous)}
});
