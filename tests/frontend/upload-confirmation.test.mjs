import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmationRows, decisionGroups, installUploadConfirmationRuntime} from '../../static/modules/upload-confirmation.js';
const receipt=(id, ids)=>({id,items:ids.map(image_id=>({image_id,decision:'pending',image:{id:image_id,filename:`${image_id}.jpg`}})),upload_request_status:'SUCCEEDED'});
test('confirmation identity uses persisted successful images and filters missing, retired, duplicate rows',()=>{
  const a=receipt('a',['1','2']);a.items.push({image_id:'3',decision:'pending',missing:true,image:null});a.items[1].image.retired_at='now';
  assert.deepEqual(confirmationRows([a,receipt('b',['1','4'])]).map(r=>r.image_id),['1','4']);
});
test('mixed selection routes to actual batches and never resubmits decided rows',()=>{
 const a=receipt('a',['1','2']);a.items[1].decision='clean';const rows=confirmationRows([a,receipt('b',['3'])]);
 assert.deepEqual([...decisionGroups(rows,new Set(['1','2','3']),'ready')],[['a',['1']],['b',['3']]]);
 a.clean_task_id='task';assert.throws(()=>decisionGroups(confirmationRows([a]),new Set(['1']),'clean'),/已有清洗任务/);
});
test('submission refreshes receipts, blocks concurrent duplicate clicks and opens original annotation queue',async()=>{
 const values=new Map();const storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
 const s={project:{id:'p'}};let posts=0,openId;let release;const gate=new Promise(resolve=>release=resolve);let block=false;
 let server=receipt('a',['1','2']);
 const runtime=installUploadConfirmationRuntime({getState:()=>s,storage,window:{openAnnotation:async id=>openId=id},api:async(url,opt)=>{
   if(opt?.method === 'POST'){posts++;assert.deepEqual(JSON.parse(opt.body),{clean_image_ids:[],ready_image_ids:['1','2']});server={...server,items:server.items.map(r=>({...r,decision:'ready'}))};return server;}
   if(block)await gate;return server;
 }});
 await runtime.open({projectId:'p',batchIds:['a'],totalFiles:2});
 // Select through the same rendered checkbox handler without a browser.
 const root={dataset:{},querySelector:()=>null,prepend(){},set innerHTML(v){this.html=v;}};
 const container={querySelector:()=>root,firstElementChild:root,children:[root],replaceChildren(){}};runtime.mount(container);root.onchange({target:{dataset:{uploadAction:'all'},checked:true}});
 block=true;const first=runtime.submit('ready');assert.equal(await runtime.submit('ready'),false);release();assert.equal(await first,true);
 assert.equal(posts,1);assert.deepEqual(s.annotationQueue414,['1','2']);assert.equal(openId,'1');
 await runtime.restoreForProject('p');assert.equal(runtime.renderIfActive(),false);
});

test('project switch during receipt refresh cannot submit decisions to old project',async()=>{
 const s={project:{id:'p'}};let block=false,release,posts=0;const gate=new Promise(resolve=>release=resolve);
 const runtime=installUploadConfirmationRuntime({getState:()=>s,window:{},storage:{getItem:()=>null,setItem(){}},api:async(_url,opt)=>{if(opt.method==='POST')posts++;if(block)await gate;return receipt('a',['1']);}});
 await runtime.open({projectId:'p',batchIds:['a']});
 const root={dataset:{},set innerHTML(v){},querySelector:()=>null};const box={querySelector:()=>root,firstElementChild:root,children:[root]};runtime.mount(box);root.onchange({target:{dataset:{uploadAction:'all'},checked:true}});
 block=true;const pending=runtime.submit('clean');s.project.id='other';release();assert.equal(await pending,false);assert.equal(posts,0);assert.equal(runtime.renderIfActive(),false);
});
test('deferred pointer restores pending entry without auto-opening and ignores uncommitted requests',async()=>{
 const pointer={projectId:'p',batchIds:['a'],requestIds:['a','missing','processing'],deferred:true};const values=new Map([['material-upload-session:p',JSON.stringify(pointer)]]);
 const runtime=installUploadConfirmationRuntime({getState:()=>({project:{id:'p'}}),window:{},storage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},api:async url=>{
  if(url.endsWith('/missing'))throw Object.assign(new Error('missing'),{httpStatus:404});
  if(url.endsWith('/processing'))return {...receipt('processing',[]),upload_request_status:'PROCESSING'};
  return receipt('a',['1']);
 }});
 assert.equal(await runtime.restoreForProject('p'),true);assert.equal(runtime.renderIfActive(),false);assert.deepEqual(runtime.getSession().batchIds,['a']);
});
test('mid-upload refresh keeps unconfirmed counts visible and manual query recovers original request pointer',async()=>{
 const pointer={projectId:'p',batchIds:[],requestIds:['waiting','notyet'],totalFiles:5};const values=new Map([['material-upload-session:p',JSON.stringify(pointer)]]);let ready=false;const queried=[];
 const root={dataset:{},html:'',set innerHTML(value){this.html=value;}};const box={querySelector:()=>root,firstElementChild:root,children:[root]};
 const runtime=installUploadConfirmationRuntime({getState:()=>({project:{id:'p'}}),getContainer:()=>box,window:{},storage:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)},api:async url=>{
  queried.push(url);if(url.endsWith('/notyet'))throw Object.assign(new Error('missing'),{httpStatus:404});
  return ready?receipt('waiting',['1','2','3','4','5']):{...receipt('waiting',[]),upload_request_status:'PROCESSING'};
 }});
 assert.equal(await runtime.restoreForProject('p'),true);assert.equal(runtime.renderIfActive(),true);assert.match(root.html,/待核验入库 <b>5<\/b>/);assert.match(root.html,/重新核验上传回执/);
 ready=true;assert.equal(await runtime.open(runtime.getSession()),true);assert.match(root.html,/成功入库 <b>5<\/b>/);assert.match(root.html,/待核验入库 <b>0<\/b>/);assert.equal(queried.length,4);assert.deepEqual(runtime.getSession().requestIds,['waiting','notyet']);
});

test('navigation restore cannot invalidate an opening receipt request or leave loading stuck',async()=>{
 const values=new Map();let runtime,restored;
 const win={setPage:async()=>{restored=await runtime.restoreForProject('p')}};
 runtime=installUploadConfirmationRuntime({getState:()=>({project:{id:'p'}}),window:win,storage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},api:async()=>receipt('a',['1'])});
 assert.equal(await runtime.open({projectId:'p',batchIds:['a']}),true);
 assert.equal(restored,false);
 assert.equal(await runtime.submit('ready'),true);
});
