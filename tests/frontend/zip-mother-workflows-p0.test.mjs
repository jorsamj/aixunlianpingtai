import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {zipNeedsLabelConfirmation, zipStartDisposition} from '../../static/modules/zip-import-runtime.js';
import {validatePreparedMotherModel} from '../../static/modules/training-submit.js';

const read=path=>readFileSync(new URL(path, import.meta.url),'utf8');

test('raw ZIP with data.yaml hints does not require positive, negative or label confirmation',()=>{
  const job={status:'selecting',scan_kind:'RAW_UNANNOTATED',sample_classification_required:false,
    label_confirmation_required:false,external_class_hints:[{name:'fire'}],external_classes:[]};
  assert.equal(zipNeedsLabelConfirmation(job),false);
  assert.equal(zipStartDisposition(job,[],{intent:'deferred'}),'start');
});

test('ZIP completion action uses backend batch identity and single-layer handoff',()=>{
  const module=read('../../static/modules/zip-import-runtime.js');
  assert.match(module,/startBatchAction\(jobId,action\)/);
  assert.match(module,/closeOwnedLayer\(layer,'handoff'\)/);
  assert.match(module,/createAiLabel429\(\{source_batch_id:String\(jobId\)\}\)/);
  assert.match(module,/openImportManualAnnotation429\(String\(jobId\)\)/);
  assert.match(module,/直接 AI 预标注/);
});

test('first training excludes uploaded PT until safety evidence exists',()=>{
  const target={base_models:[{model_status:'FOUND',trainable:false,value:'asset:pt_0123456789abcdef01234567'}]};
  const draft={config:{model:target.base_models[0].value}};
  assert.throws(()=>validatePreparedMotherModel({draft,target}),/母模型/);
  target.base_models[0].trainable=true;
  assert.equal(validatePreparedMotherModel({draft,target}),true);
});

test('advanced model management is a tab of existing training-resource owner',()=>{
  const nav=read('../../static/modules/advanced-navigation.js');
  assert.match(nav, /id:'models',page:'训练资源',label:'母模型管理'/);
  const discovery=read('../../static/modules/resource-discovery.js');
  assert.match(discovery,/motherModelManagement\(\)/);
  assert.match(discovery,/\/api\/v63\/base-models\/assets/);
});
