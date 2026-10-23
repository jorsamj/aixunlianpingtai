import test from 'node:test';
import assert from 'node:assert/strict';
import {installZipImportRuntime} from '../../static/modules/zip-import-runtime.js';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
function file(name){return new File([new Uint8Array(11)],name,{lastModified:123});}
function harness({rejectPause=false,durableJobs=()=>[]}={}){
  const previous={window:globalThis.window,document:globalThis.document,XMLHttpRequest:globalThis.XMLHttpRequest};
  const node={classList:{add(){},remove(){}},querySelector(){return null},style:{},remove(){}};
  const requests=[],pending=[],events=[],rows=new Map(),state={project:{id:'p'},page:'数据集'};let modals=0;
  globalThis.document={getElementById:id=>id==='zipImportDurableDock'?node:null,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>node,body:{appendChild(){}}};
  globalThis.window={UploadTaskCenterRuntime:{upsert(row){rows.set(row.id,{...rows.get(row.id),...row})},rekey(from,to){const row=rows.get(from);rows.delete(from);rows.set(to,{...rows.get(to),...row,id:to})}},PollRegistryRuntime:{clear(){},startTimeout(){}},modal(){modals++},confirm:()=>true};
  globalThis.XMLHttpRequest=class {
    upload={};status=200;responseText='{}';
    open(method,url){this.url=url}setRequestHeader(){}
    send(blob){this.size=blob.size;pending.push(this)}
    abort(){this.onabort?.()}
  };
  const fetchImpl=async(url,options={})=>{
    requests.push({url,options});
    if(rejectPause&&url.endsWith('/pause'))return Response.json({detail:'isolated pause rejection'},{status:500});
    if(url.endsWith('/uploads')){const b=JSON.parse(options.body);return Response.json({upload_id:b.resume_upload_id||b.file_name,part_size:4,completed_parts:[],upload_progress:0,total_parts:3})}
    if(url.endsWith('/complete'))return Response.json({id:'job-'+url.split('/').at(-2),status:'running',file_name:'accepted.zip'});
    if(url.endsWith('/jobs'))return Response.json({items:durableJobs()});
    return Response.json({id:url.split('/').at(-1),status:'running'});
  };
  const runtime=installZipImportRuntime({getState:()=>state,projectId:()=>state.project.id,fetchImpl});
  return {runtime,pending,requests,events,rows,get modals(){return modals},async finish(){for(let i=0;i<100;i++){for(const xhr of pending.splice(0)){xhr.upload.onprogress?.({lengthComputable:true,loaded:xhr.size,total:xhr.size});xhr.onload?.()}await new Promise(resolve=>setTimeout(resolve,5))}},cleanup(){runtime.destroy();Object.assign(globalThis,previous)}};
}

test('original ZIP controller publishes per-file identity bytes and handoff, and observer teardown has no upload side effects',async()=>{
  const h=harness();
  try{
    assert.equal(typeof h.runtime.subscribeTransfers,'function');
    const unsubscribe=h.runtime.subscribeTransfers(event=>h.events.push(event));
    const f=file('one.zip'),upload=h.runtime.uploadBatch({files:[f],value:'',externalView:true});
    await tick();await h.finish();await upload;
    assert.equal(h.events[0].type,'queued');assert.equal(h.events[0].file,f);
    assert.ok(h.events.some(e=>e.type==='session'&&e.uploadId==='one.zip'));
    assert.ok(h.events.some(e=>e.type==='progress'&&e.loaded===11&&e.total===11));
    const success=h.events.find(e=>e.type==='success');assert.equal(success.jobId,'job-one.zip');assert.equal(success.response.status,'running');
    assert.equal(h.modals,0);
    unsubscribe();const before=h.events.length;
    await h.runtime.uploadBatch({files:[file('bad.txt')],value:'',externalView:true});
    assert.equal(h.events.length,before);
  }finally{h.cleanup()}
});

test('legacy browser transfer stays authoritative when durable polling lags acknowledged bytes',async()=>{
  let server=[];
  const h=harness({durableJobs:()=>server});
  try{
    const upload=h.runtime.upload({files:[file('source.zip')],value:'',externalView:true});
    await tick();await tick();
    for(const xhr of h.pending)xhr.upload.onprogress?.({lengthComputable:true,loaded:Math.max(1,xhr.size-1),total:xhr.size});
    const before=h.rows.get('zip:source.zip').progress;
    assert.ok(before>30);
    server=[{id:'source.zip',status:'uploading',progress:0,file_name:'source.zip'}];
    await h.runtime.reconcile('source-consistency');
    assert.equal(h.rows.get('zip:source.zip').progress,before);
    await h.finish();await upload;
  }finally{h.cleanup()}
});

test('resuming a ZIP joins the same original two-slot limiter as fresh batches',async()=>{
  const h=harness();
  try{
    assert.equal(typeof h.runtime.resumeTransfer,'function');
    const batch=h.runtime.uploadBatch({files:[file('a.zip'),file('b.zip')],value:'',externalView:true});
    await tick();await tick();
    const resumed=h.runtime.resumeTransfer(file('c.zip'),'original-c');
    await tick();
    assert.equal(h.requests.filter(r=>r.url.endsWith('/uploads')&&JSON.parse(r.options.body).resume_upload_id==='original-c').length,0);
    await h.finish();await Promise.all([batch,resumed]);
    assert.ok(h.requests.some(r=>r.url.endsWith('/uploads')&&JSON.parse(r.options.body).resume_upload_id==='original-c'));
    assert.equal(h.modals,0);
  }finally{h.cleanup()}
});

test('pause during synchronous session notification still rekeys exactly one authoritative task-center row',async()=>{
  const h=harness();
  try{
    h.runtime.subscribeTransfers(event=>{if(event.type==='session')void h.runtime.pauseUpload(event.uploadId)});
    await h.runtime.uploadBatch({files:[file('prepaused.zip')],value:'',externalView:true});await tick();
    assert.deepEqual([...h.rows.keys()],['zip:prepaused.zip']);assert.equal(h.pending.length,0);
  }finally{h.cleanup()}
});

test('pause acknowledgement waits for retry backoff to exit before exact-ID resume',async()=>{
  const h=harness();
  try{
    h.runtime.subscribeTransfers(event=>h.events.push(event));const f=file('backoff.zip');
    const first=h.runtime.uploadBatch({files:[f],value:'',externalView:true});
    for(let i=0;i<100&&!h.pending.length;i++)await new Promise(resolve=>setTimeout(resolve,5));
    h.pending[0].onerror();await tick();
    await h.runtime.pauseUpload('backoff.zip');
    const resumed=h.runtime.resumeTransfer(f,'backoff.zip');await tick();await h.finish();await Promise.all([first,resumed]);
    assert.equal(h.events.filter(e=>e.type==='success').length,1);
    assert.equal(h.events.filter(e=>e.type==='error').length,0);
  }finally{h.cleanup()}
});

test('backend pause rejection emits a recoverable per-file error after local transport stops',async()=>{
  const h=harness({rejectPause:true});
  try{
    let pause;
    h.runtime.subscribeTransfers(event=>{h.events.push(event);if(event.type==='session'&&!pause)pause=h.runtime.pauseUpload(event.uploadId)});
    await h.runtime.uploadBatch({files:[file('pause-failure.zip')],value:'',externalView:true});await pause;
    assert.ok(h.events.some(e=>e.type==='error'&&/pause rejection/.test(e.message)));
  }finally{h.cleanup()}
});


test('a paused legacy upload resumes through Uppy using the same session identity',async()=>{
  const h=harness();
  try{
    let pause;let once=false;const f=file('legacy.zip');
    h.runtime.subscribeTransfers(event=>{h.events.push(event);if(event.type==='session'&&!once){once=true;pause=h.runtime.pauseUpload(event.uploadId)}});
    await h.runtime.upload({files:[f],value:'',externalView:true});await pause;
    const resumed=h.runtime.resumeTransfer(f,'legacy.zip');await h.finish();await resumed;
    assert.equal(h.events.filter(e=>e.type==='success').length,1);
    assert.equal(h.events.filter(e=>e.type==='error').length,0);
  }finally{h.cleanup()}
});


test('official Core and the original controller recover a rejected pause without duplicate task identity',async()=>{
  const {default:Uppy,BasePlugin}=await import('@uppy/core');
  const {mountUppyZipAdapter}=await import('../../static/modules/uppy-zip-adapter.js');
  class Dashboard extends BasePlugin {constructor(uppy,opts){super(uppy,opts);this.id='Dashboard';this.type='acquirer'}}
  const h=harness({rejectPause:true});let adapter;
  try{
    adapter=await mountUppyZipAdapter({target:{isConnected:true},runtime:h.runtime,projectId:'p',loadUppy:async()=>({Uppy,Dashboard,zhCN:{strings:{}}})});
    const f=file('core-pause.zip'),id=adapter.uppy.addFile({name:f.name,type:'application/zip',data:f});let paused=false;
    h.runtime.subscribeTransfers(event=>{h.events.push(event);if(event.type==='session'&&!paused){paused=true;adapter.uppy.pauseAll()}});
    const failed=await adapter.uppy.upload();assert.equal(failed.failed.length,1);assert.match(adapter.uppy.getFile(id).error,/pause rejection/);
    const retry=adapter.uppy.retryUpload(id);await h.finish();const result=await retry;
    assert.equal(result.successful.length,1);assert.equal(h.events.filter(e=>e.type==='success').length,1);
    assert.deepEqual([...h.rows.keys()],['zip:job-core-pause.zip']);
    assert.ok(h.requests.some(r=>r.url.endsWith('/uploads')&&JSON.parse(r.options.body).resume_upload_id==='core-pause.zip'));
  }finally{adapter?.destroy();h.cleanup()}
});
