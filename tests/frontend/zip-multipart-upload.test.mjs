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
