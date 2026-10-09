import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {zipFingerprint, zipPartPlan} from '../../static/modules/zip-import-runtime.js';

test('large ZIP is divided into deterministic resumable parts', () => {
  const parts = zipPartPlan(21, 8, [0,2]);
  assert.deepEqual(parts, [
    {index:0,start:0,end:8,size:8,completed:true},
    {index:1,start:8,end:16,size:8,completed:false},
    {index:2,start:16,end:21,size:5,completed:true},
  ]);
});

test('ZIP runtime uses multipart upload path and bounded parallelism', () => {
  const source = fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /import\/uploads/);
  assert.match(source, /concurrency=4/);
  assert.match(source, /uploadZipMultipartJob\(project,file/);
  assert.match(source, /retries=2/);
});

test('resume fingerprint includes sampled content so same name size and mtime cannot reuse foreign parts', async () => {
  const makeFile = bytes => {
    const blob = new Blob([Uint8Array.from(bytes)]);
    Object.defineProperty(blob, 'name', {value:'same.zip'});
    Object.defineProperty(blob, 'lastModified', {value:123456});
    return blob;
  };
  const first = makeFile([1,2,3,4,5,6,7,8]);
  const second = makeFile([1,2,3,4,5,6,7,9]);

  const a = await zipFingerprint(first);
  const b = await zipFingerprint(second);

  assert.match(a, /^v2:same\.zip:8:123456:/);
  assert.notEqual(a, b);
});


test('resume sends only missing parts and never merges before all acknowledgements', async () => {
  const {uploadZipMultipartJob}=await import('../../static/modules/zip-import-runtime.js');
  const file=new Blob([Uint8Array.from({length:11},(_,i)=>i)]);
  Object.defineProperty(file,'name',{value:'original.zip'});
  Object.defineProperty(file,'lastModified',{value:1234});
  const sent=[],requests=[];
  const xhrFactory=()=>({
    upload:{},status:200,responseText:'{}',
    open(method,url){this.url=url;this.method=method},
    setRequestHeader(){},
    send(data){sent.push(this.url);this.onload()},
    abort(){this.onabort?.()},
  });
  const fetchImpl=async (url,options)=>{
    requests.push({url,options});
    const body=url.includes('/complete')?{id:'existing',status:'selecting'}:{
      upload_id:'existing',part_size:4,completed_parts:[0],total_parts:3,upload_progress:36,
    };
    return {ok:true,status:200,json:async()=>body};
  };
  const result=await uploadZipMultipartJob('project',file,{fetchImpl,xhrFactory,control:{state:'active',xhrs:new Set(),expectedUploadId:'existing'}});
  assert.equal(result.id,'existing');
  assert.equal(sent.length,2);
  assert.ok(sent.some(s=>s.endsWith('/parts/1')));
  assert.ok(sent.some(s=>s.endsWith('/parts/2')));
  assert.equal(requests.filter(r=>r.url.includes('/complete')).length,1);
  const body=JSON.parse(requests[0].options.body);
  assert.equal(body.resume_upload_id,'existing');
});

test('ZIP complete lost response recovers using the same durable job id without a second complete POST', async () => {
  const {completeZipUpload}=await import('../../static/modules/zip-import-runtime.js');
  const requests=[];
  const fetchImpl=async (url, options={})=>{
    requests.push({url, method:options.method || 'GET'});
    if (url.endsWith('/complete')) throw new TypeError('Failed to fetch');
    return {ok:true,status:200,json:async()=>({id:'job-42',status:'merging',stage:'正在合并 ZIP 分片'})};
  };
  const result=await completeZipUpload('p1','job-42',{fetchImpl});
  assert.equal(result.status,'merging');
  assert.equal(requests.filter(x=>x.method==='POST').length,1);
  assert.equal(requests.filter(x=>x.method==='GET').length,1);
});

test('ZIP complete unknown network state remains recoverable and never blindly retries POST', async () => {
  const {completeZipUpload}=await import('../../static/modules/zip-import-runtime.js');
  const requests=[];
  const fetchImpl=async (url,options={})=>{
    requests.push({url,method:options.method || 'GET'});
    throw new TypeError('Failed to fetch');
  };
  await assert.rejects(
    completeZipUpload('p1','job-42',{fetchImpl}),
    error=>error.zipCompletionUncertain===true && /不要重复上传/.test(error.message) && /job-42/.test(error.message),
  );
  assert.deepEqual(requests.map(x=>x.method),['POST','GET']);
});

test('ZIP complete HTTP rejection is not treated as a network acknowledgement', async () => {
  const {completeZipUpload}=await import('../../static/modules/zip-import-runtime.js');
  const requests=[];
  const fetchImpl=async (url,options={})=>{
    requests.push({url,method:options.method||'GET'});
    return {ok:false,status:409,json:async()=>({detail:'ZIP 分片尚未全部上传：44/46'})};
  };
  await assert.rejects(completeZipUpload('p1','job-44',{fetchImpl}),/44\/46/);
  assert.equal(requests.length,1);
});

test('ZIP runtime has one active task-center polling owner and a declared modal status',()=>{
  const source=fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/pollOwner:'zip-import-runtime'/);
  assert.match(source,/function body\(job\)\{\s*const s=status\(job\)/);
  assert.match(source,/catch \(refreshError\) \{/);
  assert.match(source,/publishTaskCenterJob\(project,provisional\)/);
});

test('legacy ZIP dock patches text without replacing its content during progress updates',()=>{
  const source=fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const render=source.match(/function render\(\)\{([\s\S]*?)\n  function clearPoll\(\)/)?.[1];
  assert.ok(render, 'ZIP render must be present');
  assert.doesNotMatch(render,/d\.innerHTML=/);
  assert.match(render,/updateDockContent\(d,/);
  assert.match(source,/data-zip-dock-title/);
  assert.match(source,/heading\.textContent!==title/);
});

test('unconfirmed ZIP network completion leaves durable status polling enabled but blocks false upload progress',()=>{
  const source=fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/zipCompletionUncertain=true/);
  assert.match(source,/status:'WAITING'/);
  assert.match(source,/browserTransfer:false,resumeRequired:true,pollOwner:''/);
});

test('interrupted ZIP view exposes pause resume and safe cancellation without stacking a second modal',()=>{
  const source=fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/pauseUpload\('/);
  assert.match(source,/promptResume\('/);
  assert.match(source,/cancelUpload\('/);
  assert.match(source,/input\.closest\?\.\('\.modal'\)/);
  assert.doesNotMatch(source,/window\.closeModal\?\.\(\);open\(\);render\(\)/);
  assert.match(source,/xhr\.timeout=180000/);
  assert.match(source,/xhr\.ontimeout=/);
});

test('failed ZIP network transfer releases stale active controller so same-file retry stays possible',()=>{
  const source=fs.readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  // Paused/cancelled sessions deliberately retain control for later resumption;
  // only failed active transfers should drop the stale browser-owned controller.
  assert.match(source,/catch\(e\)\{const lastUploadProgress=Number\(uploading\?\.progress\|\|0\);uploading=null;[\s\S]*?if\(uploadControl===control&&control\.state==='active'\)uploadControl=null;[\s\S]*?if\(control\.state==='paused'\|\|control\.state==='cancelled'\)return null;/);
});
