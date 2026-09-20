import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

test('post-import label remap is a durable material batch with real backend progress',()=>{
  assert.match(source,/\/api\/v52\/projects\/\$\{pid\(\)\}\/labels\/remap/);
  assert.match(source,/\/api\/v62\/projects\/\$\{pid\(\)\}\/material-batches\/\$\{taskId\}/);
  assert.match(source,/progress_percent/);
  assert.match(source,/processed/);
  assert.match(source,/total/);
  assert.match(source,/正在批量统一标签/);
  assert.match(source,/PollRegistryRuntime\?\.startTimeout/);
  assert.match(source,/import-label-remap/);
  assert.match(source,/getElementById\('importRemapStage414'\)/);
  assert.match(source,/marker\?\.closest\('\.modal-body'\)/);
});

test('remap UI does not claim synchronous completion after task creation',()=>{
  const start=source.indexOf('window.remapImport414=async function');
  assert.ok(start>=0);
  const tail=source.slice(start,start+1800);
  assert.match(tail,/task\.task_id/);
  assert.match(tail,/pollImportRemap414/);
  assert.match(tail,/import412RemapSubmitting/);
  assert.doesNotMatch(tail,/已同步 .* 个框/);
});


test('legacy remap entry delegates to the single durable remap owner',()=>{
  assert.match(source,/window\.remapImport412=\(source,inputId\)=>window\.remapImport414\(source,inputId\)/);
  assert.doesNotMatch(source,/window\.remapImport412=async/);
});
