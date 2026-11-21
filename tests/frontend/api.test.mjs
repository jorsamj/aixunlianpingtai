import test from 'node:test';
import assert from 'node:assert/strict';

import {messageFromApiError, fetchWithUploadProgress} from '../../static/modules/api.js';


test('api error includes detail and solution', () => {
  assert.equal(
    messageFromApiError({message: '标注保存失败', detail: '标签不存在', solution: '请创建标签'}),
    '标注保存失败：标签不存在\n建议：请创建标签'
  );
});

test('original API upload transport reports real bytes and preserves HTTP error response', async () => {
  const updates=[];
  const xhr={upload:{},open(method,url){assert.equal(method,'POST');assert.equal(url,'/api/upload');},
    setRequestHeader(){},getResponseHeader(){return 'application/json';},status:500,responseText:'{"message":"accepted but response failed"}',
    send(){this.upload.onprogress({loaded:3,total:10,lengthComputable:true});this.upload.onprogress({loaded:10,total:10,lengthComputable:true});this.onload();}};
  const response=await fetchWithUploadProgress('/api/upload',{body:new FormData(),onUploadProgress:value=>updates.push(value)},()=>xhr);
  assert.deepEqual(updates.map(value=>[value.loadedBytes,value.totalBytes]),[[3,10],[10,10]]);
  assert.equal(response.status,500);
  assert.equal(response.ok,false);
  assert.equal((await response.json()).message,'accepted but response failed');
});

test('original API upload transport uses the existing deadline abort signal', async () => {
  const controller=new AbortController();let aborted=0;
  const xhr={upload:{},open(){},setRequestHeader(){},send(){},abort(){aborted++;this.onabort?.();}};
  const pending=fetchWithUploadProgress('/api/upload',{body:new FormData(),signal:controller.signal},()=>xhr);
  controller.abort();
  await assert.rejects(pending,error=>error.name==='AbortError');
  assert.equal(aborted,1);
});

