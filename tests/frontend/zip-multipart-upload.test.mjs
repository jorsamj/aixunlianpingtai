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
