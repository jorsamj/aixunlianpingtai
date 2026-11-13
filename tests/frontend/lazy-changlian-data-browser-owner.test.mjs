import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installLazyChangLianDataBrowserRuntime} from '../../static/modules/lazy-changlian-data-browser.js';

const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
const html=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');

function fixture(){
  const state={page:'总览',project:{id:'p1'}},host={};
  let root=null;
  const view={
    set innerHTML(value){this.html=value;root={html:value,onclick:null};},
    get innerHTML(){return this.html||'';},
    querySelector:selector=>selector==='[data-cldb-lazy-retry]'?root:null,
  };
  const doc={getElementById:id=>id==='view'?view:null};
  const loads=[],renders=[],leaves=[],destroyed=[],refreshes=[];
  let validNavigation=true;
  const facade=installLazyChangLianDataBrowserRuntime({
    getState:()=>state,request:()=>{throw new Error('unexpected provider HTTP')},
    host,document:doc,navigationOwner:()=>({isCurrent:()=>validNavigation}),
    load:attempt=>new Promise((resolve,reject)=>loads.push({attempt,resolve,reject})),
  });
  const mod={installChangLianDataBrowserRuntime:()=>({
    render:()=>{renders.push(state.page);return true;},
    leave:()=>{leaves.push(true);},
    destroy:()=>{destroyed.push(true);},
    refresh:()=>{refreshes.push(true);return Promise.resolve(true);},
    snapshot:()=>({loaded:true,products:[]}),
  })};
  return {state,host,view,facade,mod,loads,renders,leaves,destroyed,refreshes,
    retireNavigation:()=>{validNavigation=false}};
}

test('13C-03 removes provider page module from startup static graph',()=>{
  assert.doesNotMatch(main,/^import \{installChangLianDataBrowserRuntime\} from '\.\/modules\/changlian-data-browser\.js/m);
  assert.match(main,/import \{installLazyChangLianDataBrowserRuntime\} from '\.\/modules\/lazy-changlian-data-browser\.js/);
  assert.match(main,/const changLianDataBrowserRuntime = installLazyChangLianDataBrowserRuntime\(\{/);
  assert.match(main,/changLianDataBrowserRuntime\.leave\(\)/);
  assert.match(main,/changLianDataBrowserRuntime\?\.render\?\.\(\)/);
  assert.match(main,/changLianDataBrowserRuntime\?\.destroy\?\.\(\)/);
  for(const name of ['app.js','main.mjs','styles.css'])
    assert.ok(html.includes('/static/'+name+'?v=42.25.602'));
});

test('only entering page loads module; provider refresh remains manual',async()=>{
  const f=fixture();
  assert.equal(f.host.ChangLianDataBrowserRuntime,f.facade);
  assert.equal(f.facade.render(),false);
  assert.equal(f.loads.length,0);
  f.state.page='畅联云数据';
  const opening=f.facade.render();
  await Promise.resolve();
  assert.deepEqual(f.loads.map(v=>v.attempt),[1]);
  assert.match(f.view.innerHTML,/正在打开畅联云数据/);
  f.loads[0].resolve(f.mod);
  assert.equal(await opening,true);
  assert.deepEqual(f.renders,['畅联云数据']);
  assert.equal(f.refreshes.length,0);
  assert.equal(f.facade.render(),true);
  assert.equal(f.loads.length,1);
  assert.equal(f.renders.length,2);
  assert.deepEqual(f.facade.snapshot(),{loaded:true,products:[]});
  await f.facade.refresh();
  assert.equal(f.refreshes.length,1);
});

test('leaving page invalidates held import; later entry reuses loaded module',async()=>{
  const f=fixture();
  f.state.page='畅联云数据';
  const old=f.facade.render();
  await Promise.resolve();
  f.facade.leave();
  f.state.page='训练任务';
  f.loads[0].resolve(f.mod);
  assert.equal(await old,false);
  assert.equal(f.renders.length,0);
  f.state.page='畅联云数据';
  assert.equal(f.facade.render(),true);
  assert.equal(f.renders.length,1);
  f.facade.leave();
  assert.equal(f.leaves.length,1);
  f.facade.destroy();
  assert.equal(f.destroyed.length,1);
  assert.equal(f.facade.render(),false);
});

test('project switch and navigation retirement reject late import',async()=>{
  const f=fixture();
  f.state.page='畅联云数据';
  const opening=f.facade.render();
  await Promise.resolve();
  f.state.project.id='p2';
  f.retireNavigation();
  f.loads[0].resolve(f.mod);
  assert.equal(await opening,false);
  assert.equal(f.renders.length,0);
  assert.equal(f.facade.snapshot().loaded,false);
});

test('load error stays local and retry gets a unique import attempt',async()=>{
  const f=fixture();
  f.state.page='畅联云数据';
  const first=f.facade.render();
  await Promise.resolve();
  f.loads[0].reject(new Error('network fixture'));
  assert.equal(await first,false);
  assert.match(f.view.innerHTML,/页面模块加载失败/);
  const retry=f.view.querySelector('[data-cldb-lazy-retry]');
  assert.equal(typeof retry.onclick,'function');
  retry.onclick();
  await Promise.resolve();
  assert.deepEqual(f.loads.map(v=>v.attempt),[1,2]);
  f.loads[1].resolve(f.mod);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.renders.length,1);
});
