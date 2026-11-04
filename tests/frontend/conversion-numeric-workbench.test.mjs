import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const ui=fs.readFileSync(new URL('../../static/modules/conversion-workbench-ui.js',import.meta.url),'utf8');
const quality=fs.readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
const app=fs.readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const backend=fs.readFileSync(new URL('../../app.py',import.meta.url),'utf8');
const handler=fs.readFileSync(new URL('../../platform_core/deployment/conversion_tasks.py',import.meta.url),'utf8');

test('conversion editor is not nested over conversion history',()=>{
  assert.match(app,/if\(document\.querySelector\('\.convert428-v2'\)\)await closeModal\(\)/);
  assert.match(ui,/conversion560-create/);
  assert.match(ui,/返回转换记录/);
  assert.match(ui,/conversion560-aside/);
});

test('conversion list and quality center share one numerical verification entry',()=>{
  assert.match(ui,/conversion560-numeric-action/);
  assert.match(ui,/window\.openConversionNumeric560/);
  assert.match(quality,/data-scenario-mode=\\?"conversion/);
  assert.match(quality,/window\.runConversionNumeric560/);
  assert.match(quality,/reuseConversionQuickFiles560/);
});

test('verification uses persistent tasks, uploads actual images, and never promotes BMODEL quality',()=>{
  assert.match(backend,/deploy\/jobs\/\{job_id\}\/numeric-validations/);
  assert.match(backend,/shared_task_repository\(\)\.create\(TaskRecord\.new/);
  assert.match(handler,/request\.get\("execution_mode"\) == "numeric_verification"/);
  assert.match(quality,/PT／ONNX/);
  assert.match(quality,/BMODEL 仅在官方 SDK 模拟器可用时另行数值比较/);
  assert.doesNotMatch(quality.slice(quality.indexOf('function decorateConversionBench560'),quality.indexOf('function benchNotices64')),/TP\s*\/\s*FP\s*\/\s*FN/);
});
