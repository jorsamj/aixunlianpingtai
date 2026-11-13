import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installLazyAdvancedEvaluation} from '../../static/modules/lazy-advanced-evaluation.js';

const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
const html=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');

function fixture(){
  const state={page:'质量中心',qualityCenterTab411:'advanced',project:{id:'p1'}};
  let host=null;
  const view={
    get innerHTML(){return this.html||''},
    set innerHTML(value){this.html=value;host={innerHTML:value,querySelector(selector){
      if(selector==='[data-advanced-load-retry]')return this.retry||(this.retry={onclick:null});
      return null;
    }}},
    querySelector(selector){return selector==='[data-advanced-evaluation]'?host:null},
  };
  const doc={getElementById:id=>id==='view'?view:null,querySelector:sel=>sel==='[data-advanced-evaluation]'?host:null};
  let resolve,reject,calls=0,mounts=0,deactivations=0,navCurrent=true;
  const promise=new Promise((res,rej)=>{resolve=res;reject=rej});
  const facade=installLazyAdvancedEvaluation({
    getState:()=>state,api:()=>{},load:()=>{calls++;return promise},
    doc,navigationOwner:()=>({isCurrent:()=>navCurrent}),
  });
  const module={installAdvancedEvaluation:()=>({mount:()=>{mounts++},deactivate:()=>{deactivations++}})};
  return {state,view,doc,facade,module,resolve,reject,get calls(){return calls},
    get mounts(){return mounts},get deactivations(){return deactivations},
    retireNavigation(){navCurrent=false}};
}

test('advanced evaluation is absent from the main static import graph',()=>{
  assert.doesNotMatch(main,/^import\s+\{installAdvancedEvaluation\}\s+from\s+['"].*advanced-evaluation\.js/m);
  assert.match(main,/import \{installLazyAdvancedEvaluation\} from '\.\/modules\/lazy-advanced-evaluation\.js/);
  assert.match(main,/const advancedEvaluation=installLazyAdvancedEvaluation\(\{getState:\(\)=>state,api\}\)/);
  assert.match(main,/window\.AdvancedEvaluationRuntime=advancedEvaluation/);
  assert.match(main,/if\(page!=='质量中心'\)advancedEvaluation\.deactivate\(\)/);
  assert.match(html,/\/static\/main\.mjs\?v=42\.25\.605/);
});

test('only first advanced-tab mount loads module and repeated mounts reuse it',async()=>{
  const f=fixture();
  f.state.qualityCenterTab411='overview';
  assert.equal(f.facade.mount(),false);
  assert.equal(f.calls,0);
  f.state.qualityCenterTab411='advanced';
  const first=f.facade.mount();
  await Promise.resolve();
  assert.equal(f.calls,1);
  assert.match(f.view.innerHTML,/data-advanced-evaluation/);
  f.resolve(f.module);
  assert.equal(await first,true);
  assert.equal(f.mounts,1);
  assert.equal(f.facade.mount(),undefined);
  assert.equal(f.mounts,2);
  assert.equal(f.calls,1);
});

test('deactivation and project change invalidate delayed mount',async()=>{
  const f=fixture();
  const opening=f.facade.mount();
  await Promise.resolve();
  f.facade.deactivate();
  f.state.page='训练任务';
  f.resolve(f.module);
  assert.equal(await opening,false);
  assert.equal(f.mounts,0);
  f.state.page='质量中心';
  const second=f.facade.mount();
  assert.equal(second,undefined);
  assert.equal(f.mounts,1);
  f.state.project.id='p2';
  f.retireNavigation();
  f.facade.deactivate();
  assert.equal(f.deactivations,1);
});

test('failed import stays local and offers user-initiated retry',async()=>{
  const f=fixture();
  const opening=f.facade.mount();
  await Promise.resolve();
  f.reject(new Error('network fixture'));
  assert.equal(await opening,false);
  const host=f.doc.querySelector('[data-advanced-evaluation]');
  assert.match(host.innerHTML,/页面模块加载失败/);
  assert.equal(typeof host.querySelector('[data-advanced-load-retry]').onclick,'function');
  assert.equal(f.mounts,0);
});
