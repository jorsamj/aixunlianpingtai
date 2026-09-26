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
  assert.match(source,/annotation-label-remap/);
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


test('label management whole-label unify reuses the same durable remap owner',()=>{
  assert.match(source,/openLabelUnify414/);
  assert.match(source,/\/api\/v54\/projects\/\$\{pid\(\)\}\/labels\/unify/);
  assert.match(source,/source_class_ids:ids/);
  assert.match(source,/openLabelBulkUnify414/);
  assert.match(source,/labels\/unify\/preview/);
  assert.match(source,/annotationRemapOrigin414='label-schema'/);
  assert.match(source,/\['数据集','标签管理'\]/);
  assert.match(source,/目标标签必须由你手工选择，系统不会自动推荐/);
});


test('historical label merge is multi-source, manually targeted and background-safe',()=>{
  assert.match(source,/批量统一标签/);
  assert.match(source,/系统不会自动推荐/);
  assert.match(source,/完整成功后，来源标签会标记为 merged/);
  assert.match(source,/正在计算真实影响范围/);
  assert.match(source,/button\.classList\.add\('is-loading'\)/);
  assert.match(source,/任务创建后可关闭窗口，后台仍会继续/);
});
