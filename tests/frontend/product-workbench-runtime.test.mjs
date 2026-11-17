import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {installProductWorkbenchRuntime} from '../../static/modules/product-workbench-runtime.js';
import * as catalog from '../../static/modules/catalog-preview-runtime.js';
const source=fs.readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
test('product navigation is opt-in pure metadata with actual registered page IDs',()=>{
 assert.equal(installProductWorkbenchRuntime({enabled:false}),null);
 const runtime=installProductWorkbenchRuntime({enabled:true});
 for(const [name,page] of Object.entries(catalog))if(name.endsWith('_PAGE'))assert.ok(runtime.knownPages.includes(page),name);
 for(const page of ['统一工作台','素材上传与治理','统一配置中心'])assert.equal(runtime.canRestore(page),true);
 assert.equal(runtime.canRestore('not-a-page'),false);
 const original=[{title:'原业务',items:['算法列表','数据集']}],before=JSON.stringify(original);
 const primary=runtime.navigation(original,false);assert.equal(primary.flatMap(g=>g.items).length,7);assert.ok(!primary.flatMap(g=>g.items).includes('算法列表'));
 assert.deepEqual(runtime.navigation(original,true).slice(primary.length),original);assert.equal(JSON.stringify(original),before);
 assert.equal(runtime.navigationLabel(catalog.ASSETS_PAGE),'算法与模型');assert.equal(runtime.navigationLabel('质量中心'),'质量中心');
});
test('initial restoration maps original entry aliases while keeping concrete scoped pages',()=>{
 const runtime=installProductWorkbenchRuntime({enabled:true});
 for(const [old,page] of [['总览','统一工作台'],['算法列表',catalog.ASSETS_PAGE],['数据集',catalog.MATERIALS_PAGE],['训练任务',catalog.TASKS_PAGE],['自动标注及清洗',catalog.AI_TASKS_PAGE],['服务节点',catalog.NODES_PAGE]])assert.equal(runtime.initialPage(old),page);
 for(const page of [...runtime.knownPages,'质量中心','标签管理','AI算法底座'])assert.equal(runtime.initialPage(page),page);
});
test('original renderNav keeps real setPage IDs, supports friendly labels and optional original groups',()=>{
 const begin=source.indexOf('  renderNav=function(){',source.indexOf('const icon414=')),end=source.indexOf('\n  };',begin);
 let html='';const runtime=installProductWorkbenchRuntime({enabled:true});
 const context={state:{page:catalog.ASSETS_PAGE,v427Advanced:false},window:{ProductWorkbenchRuntime:runtime,PlatformCore:{navigation:{}}},document:{getElementById:()=>({set innerHTML(v){html=v}})},icon414:{},esc:v=>v};vm.createContext(context);vm.runInContext(source.slice(begin,end+5),context);context.renderNav();
 assert.match(html,/data-nav-page="模型资产只读浏览"/);assert.match(html,/<b>算法与模型<\/b>/);assert.match(html,/setPage\('模型资产只读浏览'\)/);assert.ok(!html.includes("setPage('算法列表')"));assert.match(html,/独立业务演示系统/);
 context.window.ProductWorkbenchRuntime=null;context.renderNav();assert.match(html,/setPage\('算法列表'\)/);assert.ok(!html.includes('<b>算法与模型</b>'));
});
test('original startup restoration extends its allowlist without admitting unknown pages',()=>{
 const start=source.indexOf("try{const x=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')"),end=source.indexOf('   if(state.uiReady)rememberCoreView413();',start);
 assert.ok(start>0&&end>start);
 const restore=source.slice(start,end),runtime=installProductWorkbenchRuntime({enabled:true});
 for(const [saved,wanted] of [['总览','统一工作台'],['算法列表',catalog.ASSETS_PAGE],[catalog.AI_TASKS_PAGE,catalog.AI_TASKS_PAGE],['素材上传与治理','素材上传与治理'],['not-a-page','统一工作台']]){
  let stored;const context={state:{page:'总览'},window:{ProductWorkbenchRuntime:runtime},RESTORABLE_PAGES413:new Set(['总览','算法列表','数据集']),localStorage:{getItem:()=>JSON.stringify({page:saved,projectId:'stale'}),setItem:(_key,v)=>stored=JSON.parse(v)},Date};vm.createContext(context);vm.runInContext(restore,context);assert.equal(context.state.page,wanted);assert.ok(!('projectId' in stored));
 }
 const context={state:{page:'总览'},window:{},RESTORABLE_PAGES413:new Set(['总览']),localStorage:{getItem:()=>JSON.stringify({page:'总览'}),setItem(){}},Date};vm.createContext(context);vm.runInContext(restore,context);assert.equal(context.state.page,'总览');
});
