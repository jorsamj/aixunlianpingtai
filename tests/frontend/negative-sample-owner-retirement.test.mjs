import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const negative = fs.readFileSync(new URL('../../static/modules/negative-samples.js', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('dirty editor removes confirmed-negative decoration without mutating formal GT',()=>{
  let status=null;const button={dataset:{},classList:{toggle(){}},textContent:''};
  const toolbar={querySelector:()=>status,appendChild:value=>{status=value}};
  const state={activeImage:{id:'i1'},ann:{annotation_state:'confirmed_empty',annotation_scope:['fire'],boxes:[]},annDirty:false};
  const window={};
  const document={querySelector:()=>toolbar,getElementById:()=>button,createElement:()=>({dataset:{},remove(){status=null}})};
  vm.runInNewContext(negative.replace('export function installNegativeSampleRuntime','function installNegativeSampleRuntime')+'\ninstallNegativeSampleRuntime({getState:()=>state});',{window,document,state,queueMicrotask:fn=>fn()});
  assert.equal(button.textContent,'✓ 已确认负样本');assert.match(status.textContent,/fire/);
  state.annDirty=true;window.NegativeSampleRuntime.decorate();
  assert.equal(button.textContent,'确认本图无目标');assert.equal(status,null);assert.equal(state.ann.annotation_state,'confirmed_empty');
  state.ann.boxes=[{label:'fire'}];window.NegativeSampleRuntime.decorate();
  assert.equal(button.hidden,false);assert.equal(button.textContent,'保存并确认审核');assert.equal(status,null);
});

test('negative sample runtime is decorator-only and never captures annotation owners', () => {
  for (const token of [
    '__negativeWrapped',
    'const original = window.',
    'window.renderAnnotator =',
    'window.saveAnn =',
    'wrapNavigation',
    'setTimeout(',
  ]) assert.equal(negative.includes(token), false, token);
  assert.match(negative, /document\.getElementById\?\.\('ann420SaveReview'\)/);
  assert.match(negative, /window\.NegativeSampleRuntime = runtime/);
  assert.match(negative, /confirmed_empty/);
});

test('canonical annotation owners explicitly decorate and confirm empty truth', () => {
  assert.match(app, /window\.saveAnn=async function saveAnnotationCanonical420/);
  assert.doesNotMatch(app, /ann420ConfirmEmpty|confirmEmptyAnnotation420/);
  assert.match(app, /if\(!selected\.length\)\{toast\('请先勾选已经查看图片并完成审核的标签'/);
  assert.match(app, /confirmEmpty:\(state\.ann\?\.boxes\?\.length\|\|0\)===0,confirmReview:true,reviewedLabelCodes:selected/);
  assert.ok((app.match(/window\.NegativeSampleRuntime\?\.decorate\?\.\(\);/g) || []).length >= 2);
  assert.match(main, /negative-samples\.js\?v=20261022a/);
});
