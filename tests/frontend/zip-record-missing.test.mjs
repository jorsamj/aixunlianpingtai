import test from 'node:test';
import assert from 'node:assert/strict';
import * as center from '../../static/modules/upload-task-center.js';
import {installZipImportRuntime, zipView, activeZipJobs} from '../../static/modules/zip-import-runtime.js';

test('persisted server RUNNING is unverified until server confirms it',()=>{
  const row=center.recoverUploadTaskAfterRefresh({id:'zip:lost',kind:'zip',status:'RUNNING',progress:72.7,updatedAt:'2026-10-26T00:00:00Z',serverUrl:'/jobs/lost'});
  assert.equal(row.status,'UNKNOWN');
  assert.equal(row.progress,72.7);
  assert.match(center.renderUploadTaskCenterRow(row),/状态无法确认/);
  assert.match(center.renderUploadTaskCenterRow(row),/最后记录.*72.7/);
  assert.equal(center.isUploadTaskActive(row),false);
});

test('unknown ZIP view never claims live progress and never auto-starts',()=>{
  const job={id:'lost',status:'unknown',progress:88.9,error:'服务器未找到该任务记录'};
  assert.equal(zipView(job,[job]).stage,'状态无法确认');
  assert.deepEqual(activeZipJobs([job]),[]);
});

test('unverified records are never evicted merely because terminal history is full',()=>{
  const rows=Array.from({length:120},(_,i)=>({id:'zip:'+i,kind:'zip',status:'UNKNOWN',createdAt:String(i)}));
  assert.equal(center.retainUploadTaskRows(rows,100).length,120);
});

test('missing cached ZIP is verified once, retained UNKNOWN, backed off, then server recovers',async()=>{
  const saved={window:globalThis.window,document:globalThis.document};
  const rows=[{id:'zip:lost',kind:'zip',status:'UNKNOWN',progress:72.7,title:'lost.zip',serverUrl:'/api/v19/projects/p/import/jobs/lost',pollOwner:'zip-import-runtime',updatedAt:'2026-10-26T00:00:00Z'}];
  let queries=0,recovered=false,posts=0;
  const dock={classList:{add(){},remove(){}},querySelector(){return null},remove(){},style:{},dataset:{}};
  globalThis.document={getElementById:id=>id==='zipImportDurableDock'?dock:null,querySelector:()=>null,querySelectorAll:()=>[]};
  globalThis.window={PollRegistryRuntime:{clear(){},startTimeout(){}},UploadTaskCenterRuntime:{list:()=>rows,upsert(row){const i=rows.findIndex(x=>x.id===row.id);if(i>=0)rows[i]={...rows[i],...row};else rows.push(row)}}};
  const state={project:{id:'p'},page:'数据集'};
  const fetchImpl=async(url,options={})=>{
    if(options.method==='POST'){posts++;throw Error('must never start missing job')}
    if(url.endsWith('/jobs'))return Response.json({items:recovered?[{id:'lost',status:'done',progress:100,file_name:'lost.zip',report:{imported_images:4}}]:[]});
    queries++;
    return Response.json({detail:'导入任务不存在'},{status:404});
  };
  let runtime;
  try{
    runtime=installZipImportRuntime({getState:()=>state,fetchImpl});
    await new Promise(resolve=>setTimeout(resolve,20));
    assert.equal(queries,1);
    assert.equal(rows[0].status,'UNKNOWN');
    assert.equal(rows[0].progress,72.7);
    assert.match(rows[0].detail,/服务器未找到/);
    for(let i=0;i<6;i++)await runtime.reconcile('poll');
    assert.equal(queries,1);
    assert.equal(posts,0);
    recovered=true;
    await runtime.reconcile('poll');
    assert.equal(rows[0].status,'DONE');
    assert.equal(rows[0].progressKnown,true);
    assert.equal(runtime.snapshot().current.status,'done');
  }finally{runtime?.destroy();Object.assign(globalThis,saved)}
});
