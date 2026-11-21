import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {installProductWorkbenchRuntime} from '../../static/modules/product-workbench-runtime.js';
import * as catalog from '../../static/modules/catalog-preview-runtime.js';
const source=fs.readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
test('workbench preserves every original group/order/entry and adds only distinct explicit trials',()=>{
 assert.equal(installProductWorkbenchRuntime({enabled:false}),null);
 const original=[{title:'总览',items:['总览','质量中心']},{title:'算法生成',items:['算法列表','训练任务']},{title:'数据中心',items:['数据集','视频切帧','自动标注及清洗','标签管理']}],before=JSON.stringify(original);
 const runtime=installProductWorkbenchRuntime({enabled:true});
 for(const advanced of [false,true]){
  const groups=runtime.navigation(original,advanced);assert.deepEqual(groups.slice(0,original.length),original);assert.deepEqual(groups.at(-1),{title:'Vue 试点',items:['统一工作台']});
  const ids=groups.flatMap(g=>g.items);assert.equal(ids.length,new Set(ids).size);
 }
 assert.equal(JSON.stringify(original),before);assert.deepEqual(runtime.knownPages,['统一工作台']);
 assert.equal(runtime.canRestore(catalog.ASSETS_PAGE),false);assert.equal(runtime.canRestore('not-a-page'),false);
 const explicit=installProductWorkbenchRuntime({enabled:true,trialPages:[catalog.ASSETS_PAGE,catalog.ASSETS_PAGE,'not-a-page']});
 assert.deepEqual(explicit.knownPages,['统一工作台',catalog.ASSETS_PAGE]);assert.equal(explicit.canRestore(catalog.ASSETS_PAGE),true);
 assert.equal(explicit.navigationLabel(catalog.ASSETS_PAGE),'Vue 模型资产只读浏览（试点）');assert.equal(explicit.navigationLabel('质量中心'),'质量中心');
});
test('original routes and default restoration are never redirected to Vue pages',()=>{
 const runtime=installProductWorkbenchRuntime({enabled:true});
 for(const page of ['总览','算法列表','数据集','训练任务','自动标注及清洗','服务节点','质量中心','标签管理','AI算法底座',...runtime.knownPages]){
  assert.equal(runtime.initialPage(page),page);assert.equal(runtime.navigationOwner(page),page);
 }
 const main=fs.readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
 const declaration=main.match(/const vueFeatureEnabled=([^;]+);/)[0];const ctx={vueProductFlags:new URLSearchParams('vue_workbench=1')};vm.createContext(ctx);vm.runInContext(declaration+'this.enabled=vueFeatureEnabled;',ctx);
 for(const flag of ['vue_model_assets','vue_algorithm_manage','vue_material_library','vue_training_tasks','vue_training_report','vue_ai_tasks','vue_catalog_manage','vue_configuration','vue_training_create','vue_ai_review'])assert.equal(ctx.enabled(flag),false,flag);
 ctx.vueProductFlags.set('vue_model_assets','1');assert.equal(ctx.enabled('vue_model_assets'),true);assert.equal(ctx.enabled('vue_material_library'),false);
});
test('original renderNav keeps formal algorithm/material/task links even with explicit Vue trials',()=>{
 const begin=source.indexOf('  renderNav=function(){',source.indexOf('const icon414=')),end=source.indexOf('\n  };',begin);
 let html='';const runtime=installProductWorkbenchRuntime({enabled:true,trialPages:[catalog.ASSETS_PAGE,catalog.MATERIALS_PAGE]});
 const context={state:{page:'算法列表',v427Advanced:false},window:{ProductWorkbenchRuntime:runtime,PlatformCore:{navigation:{}}},document:{getElementById:()=>({set innerHTML(v){html=v}})},icon414:{},esc:v=>v};vm.createContext(context);vm.runInContext(source.slice(begin,end+5),context);
 for(const product of [runtime,null]){
  context.window.ProductWorkbenchRuntime=product;context.renderNav();
  for(const page of ['算法列表','数据集','训练任务','自动标注及清洗','质量中心','标签管理'])assert.ok(html.includes(`setPage('${page}')`),page);
  assert.match(html,/<b>算法库<\/b>/);assert.equal((html.match(/data-nav-page="算法列表"/g)||[]).length,1);assert.match(html,/独立业务演示系统/);
 }
 context.window.ProductWorkbenchRuntime=runtime;context.renderNav();assert.match(html,/<b>Vue 模型资产只读浏览（试点）<\/b>/);
 const cards=fs.readFileSync(new URL('../../static/modules/algorithm-list-runtime.js',import.meta.url),'utf8');
 assert.match(cards,/data-algorithm-list-owner="AlgorithmListRuntime"/);assert.match(cards,/algorithm-card-grid/);assert.match(cards,/<h2>算法库<\/h2>/);
});
test('startup restoration keeps original pages and rejects trials not independently enabled',()=>{
 const start=source.indexOf("try{const x=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')"),end=source.indexOf('   if(state.uiReady)rememberCoreView413();',start);assert.ok(start>0&&end>start);
 const restore=source.slice(start,end);
 for(const [trialPages,saved,wanted] of [[[],'总览','总览'],[[],'算法列表','算法列表'],[[],'数据集','数据集'],[[],catalog.AI_TASKS_PAGE,'总览'],[[catalog.AI_TASKS_PAGE],catalog.AI_TASKS_PAGE,catalog.AI_TASKS_PAGE],[[],'not-a-page','总览']]){
  let stored;const runtime=installProductWorkbenchRuntime({enabled:true,trialPages});const context={state:{page:'总览'},window:{ProductWorkbenchRuntime:runtime},RESTORABLE_PAGES413:new Set(['总览','算法列表','数据集']),localStorage:{getItem:()=>JSON.stringify({page:saved,projectId:'stale'}),setItem:(_key,v)=>stored=JSON.parse(v)},Date};vm.createContext(context);vm.runInContext(restore,context);assert.equal(context.state.page,wanted);assert.ok(!('projectId' in stored));
 }
 const context={state:{page:'总览'},window:{},RESTORABLE_PAGES413:new Set(['总览']),localStorage:{getItem:()=>JSON.stringify({page:'总览'}),setItem(){}},Date};vm.createContext(context);vm.runInContext(restore,context);assert.equal(context.state.page,'总览');
});


test('independent Vue refresh restores only a currently registered original navigation owner',()=>{
 const start=source.indexOf("try{const x=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')"),end=source.indexOf('   if(state.uiReady)rememberCoreView413();',start),restore=source.slice(start,end);
 for(const enabled of [true,false]){
  const context={state:{page:'总览'},window:{PlatformCore:{runtime:{navigationStabilityRuntime:{hasPageOwner:page=>enabled&&page===catalog.ASSETS_PAGE}}}},RESTORABLE_PAGES413:new Set(['总览']),localStorage:{getItem:()=>JSON.stringify({page:catalog.ASSETS_PAGE}),setItem(){}},Date};
  vm.createContext(context);vm.runInContext(restore,context);assert.equal(context.state.page,enabled?catalog.ASSETS_PAGE:'总览');
 }
});
