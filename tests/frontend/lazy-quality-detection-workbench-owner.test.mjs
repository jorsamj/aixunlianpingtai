import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installLazyQualityDetectionWorkbench} from '../../static/modules/lazy-quality-detection-workbench.js';

const main = readFileSync(new URL('../../static/main.mjs', import.meta.url),'utf8');
const classic = readFileSync(new URL('../../static/app.js', import.meta.url),'utf8');
const index = readFileSync(new URL('../../static/index.html', import.meta.url),'utf8');
const bench = readFileSync(new URL('../../static/modules/quality-detection-workbench.js', import.meta.url),'utf8');

function fixture() {
  const state={page:'质量中心',qualityCenterTab411:'overview',project:{id:'p1'}};
  const host={};
  const body={innerHTML:'',retry:null,querySelector(selector) {
    return selector==='[data-quality-detection-retry]'
      ? (this.retry ||= {onclick:null}) : null;
  }};
  const root={querySelector:selector=>selector==='[data-quality-detection-lazy-body]'?body:null};
  const view={innerHTML:'',querySelector:selector=>selector==='[data-quality-detection-lazy]'?root:null};
  const doc={getElementById:id=>id==='view'?view:null};
  let resolve,reject;
  const delayed=new Promise((yes,no)=>{resolve=yes;reject=no});
  let loads=0,installs=0,renders=0,deactivations=0,navCurrent=true;
  const module={installQualityDetectionWorkbench:()=>{
    installs++;
    return {render:()=>{renders++;return true},deactivate:()=>{deactivations++;},
      mountEvaluationEvidence:()=>11,currentEvaluationSample:()=>({id:'sample'})};
  }};
  const facade=installLazyQualityDetectionWorkbench({
    getState:()=>state,api:()=>{},toast:()=>{},modal:()=>{},closeModal:()=>{},esc:String,
    host,doc,navigationOwner:()=>({isCurrent:()=>navCurrent}),
    load:()=>{loads++;return delayed},
  });
  return {
    state,host,facade,body,module,resolve,reject,
    get loads(){return loads},get installs(){return installs},
    get renders(){return renders},get deactivations(){return deactivations},
    retire:()=>{navCurrent=false},
  };
}

test('quality detection heavy module is absent from the startup import graph',()=>{
  assert.doesNotMatch(main,/^import \{installQualityDetectionWorkbench\} from ['"].*quality-detection-workbench\.js/m);
  assert.match(main,/import \{installLazyQualityDetectionWorkbench\} from '\.\/modules\/lazy-quality-detection-workbench\.js/);
  assert.match(main,/const qualityDetectionWorkbench=installLazyQualityDetectionWorkbench\(\{getState:\(\)=>state,api,toast:notify,modal,closeModal,esc\}\)/);
  assert.match(main,/window\.QualityDetectionWorkbenchRuntime=qualityDetectionWorkbench/);
  assert.match(main,/qualityDetectionWorkbench\.deactivate\(\)/);
  assert.match(classic,/window\.renderDetectBench = function|window\.renderDetectBench = /); // compatibility checked below independently
  assert.match(classic,/window\.renderDetectBench\?\.\(\)/);
  assert.match(bench,/export function installQualityDetectionWorkbench\(/);
  const mainVersion=index.match(/\/static\/main\.mjs\?v=([\d.]+)/)?.[1];
  assert.equal(mainVersion,'42.25.603');
  assert.ok(index.includes('/static/app.js?v='+mainVersion));
  assert.ok(index.includes('/static/styles.css?v='+mainVersion));
});

test('overview never fetches bench; repeated opens share one module and install only once',async()=>{
  const f=fixture();
  assert.equal(f.facade.render(),false);
  assert.equal(f.loads,0);
  f.state.qualityCenterTab411='detect';
  const first=f.host.renderQualityDetectionBench64();
  await Promise.resolve();
  assert.equal(f.loads,1);
  assert.match(f.body.innerHTML,/正在打开场景算法实测/);
  const second=f.facade.render();
  await Promise.resolve();
  assert.equal(f.loads,1);
  f.resolve(f.module);
  assert.equal(await first,false); // retired by second render
  assert.equal(await second,true);
  assert.equal(f.installs,1);
  assert.equal(f.renders,1);
  assert.equal(f.facade.render(),true);
  assert.equal(f.installs,1);
  assert.equal(f.renders,2);
  assert.equal(f.facade.mountEvaluationEvidence(),11);
  assert.equal(f.facade.currentEvaluationSample().id,'sample');
});

test('leaving or switching projects invalidates a pending import without mounting a stale page',async()=>{
  const f=fixture();
  f.state.qualityCenterTab411='detect';
  const opening=f.facade.render();
  await Promise.resolve();
  f.facade.deactivate();
  f.state.page='训练任务';
  f.resolve(f.module);
  assert.equal(await opening,false);
  assert.equal(f.installs,0);
  f.state.page='质量中心';
  assert.equal(f.facade.render(),true);
  assert.equal(f.installs,1);
  f.state.project.id='p2';
  f.retire();
  f.facade.deactivate();
  assert.equal(f.deactivations,1);
});

test('network failure keeps the quality tab usable and exposes explicit retry',async()=>{
  const f=fixture();
  f.state.qualityCenterTab411='detect';
  const opening=f.facade.render();
  await Promise.resolve();
  f.reject(new Error('offline'));
  assert.equal(await opening,false);
  assert.match(f.body.innerHTML,/模块加载失败/);
  assert.equal(typeof f.body.querySelector('[data-quality-detection-retry]').onclick,'function');
  assert.equal(f.installs,0);
});

test('async first mount reattaches the original quality tab row after workbench replaces view',async()=>{
  const state={page:'质量中心',qualityCenterTab411:'detect',project:{id:'p1'}};
  const originalTabs={id:'quality-navigation'};
  let tabAttached=false,attachCount=0;
  const body={innerHTML:'',querySelector:()=>null};
  const root={querySelector:selector=>selector==='[data-quality-detection-lazy-body]'?body:null};
  const view={
    _html:'',
    set innerHTML(value){this._html=value;tabAttached=false},
    get innerHTML(){return this._html},
    querySelector(selector){
      if(selector==='[data-quality-tabs="1"]')return tabAttached?originalTabs:null;
      if(selector==='[data-quality-detection-lazy]')return root;
      return null;
    },
    insertAdjacentElement(position,node){
      assert.equal(position,'afterbegin');
      assert.equal(node,originalTabs);
      assert.equal(tabAttached,false);
      tabAttached=true;
      attachCount++;
    },
  };
  const doc={getElementById:id=>id==='view'?view:null};
  let resolve;
  const modulePromise=new Promise(yes=>{resolve=yes});
  const facade=installLazyQualityDetectionWorkbench({
    getState:()=>state,api:()=>{},toast:()=>{},modal:()=>{},closeModal:()=>{},esc:String,
    host:{},doc,navigationOwner:()=>({isCurrent:()=>true}),load:()=>modulePromise,
  });
  const opening=facade.render();
  await Promise.resolve();
  // This is what classic renderQualityCenter424 does immediately after calling
  // renderDetectBench, before the real workbench module has finished loading.
  view.insertAdjacentElement('afterbegin',originalTabs);
  assert.equal(tabAttached,true);
  resolve({installQualityDetectionWorkbench:()=>({
    render:()=>{view.innerHTML='<section data-quality-detection-shell="1"></section>';return true},
    deactivate:()=>{},
  })});
  assert.equal(await opening,true);
  assert.equal(tabAttached,true);
  assert.equal(attachCount,2);
  assert.match(view.innerHTML,/data-quality-detection-shell/);
});
