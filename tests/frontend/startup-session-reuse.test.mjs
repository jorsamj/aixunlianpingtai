import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const ownerStart = source.indexOf('/* v42.13 startup prepared snapshot */');
const ownerEnd = source.indexOf('const TOP_CRUMB413=Object.freeze', ownerStart);
assert.ok(ownerStart >= 0 && ownerEnd > ownerStart);
const ownerSource = source.slice(ownerStart, ownerEnd) + '\n})();';

function setup(session, fetchCore) {
  const state = {page:'算法列表',uiReady:false,algorithms:[],jobs:[],labels:[]};
  let renders = 0;
  const context = {
    window: {}, state, AbortController, Promise, Error, Date, setTimeout, clearTimeout,
    performance:{now:()=>10},
    esc:value=>String(value),
    api:fetchCore,
    render:()=>{renders++;},
    sessionStorage:session,
    localStorage:{getItem:()=>null,setItem(){}},
    document:{
      getElementById:()=>({innerHTML:'',querySelector:()=>null}),
      querySelector:()=>({getAttribute:()=>'/static/app.js?v=42.24.561'}),
    },
  };
  vm.runInNewContext(ownerSource,context);
  return {state,window:context.window,get renders(){return renders;}};
}

const snapshot = {
  projects:[{id:'project-a'}],project:{id:'project-a',name:'隔离项目'},datasets:[],labels:[],
  algorithms:[{id:'algorithm-a',name:'人员检测',versions:[{id:'version-a'}]}],
  algorithms_total:1,algorithm_revision:42,algorithms_deferred:false,
  jobs:[],jobs_deferred:true,platform_version:'42.24.561',build_id:'fixture',
};

test('F5 restores the last verified algorithm cards before a slow bootstrap request settles',async()=>{
  const records=new Map();
  const session={getItem:key=>records.get(key)||null,setItem:(key,value)=>records.set(key,value)};
  const first=setup(session,()=>Promise.resolve(snapshot));
  await first.window.__clInit();
  assert.equal(first.renders,1);
  assert.ok(records.size===1,'initial server truth is saved once in the existing v53 owner');

  let settle;
  const second=setup(session,()=>new Promise(resolve=>{settle=resolve}));
  await second.window.__clInit();
  assert.equal(second.renders,1,'reload painted without waiting for HTTP');
  assert.equal(second.state.algorithms[0].versions[0].id,'version-a');
  assert.equal(second.state.algorithmsDeferred,false);
  settle({...snapshot,algorithms:[{id:'algorithm-a',name:'基础列表',versions:[],versions_deferred:true}],algorithms_deferred:true});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(second.state.algorithmsDeferred,false,'same authoritative revision keeps already painted cards');
  assert.equal(second.state.algorithms[0].versions[0].id,'version-a');
});

test('changed server revision invalidates stale cards and fetches focused truth once',async()=>{
  const records=new Map();
  const session={getItem:key=>records.get(key)||null,setItem:(key,value)=>records.set(key,value)};
  await setup(session,()=>Promise.resolve(snapshot)).window.__clInit();
  let resolveServer,refreshCalls=0;
  const reloaded=setup(session,()=>new Promise(resolve=>{resolveServer=resolve}));
  reloaded.window.AlgorithmListRuntime={refresh:async()=>{refreshCalls++;}};
  await reloaded.window.__clInit();
  resolveServer({...snapshot,algorithm_revision:43,algorithms:[{id:'algorithm-b',name:'新列表',versions:[],versions_deferred:true}],algorithms_deferred:true});
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.equal(refreshCalls,1);
  assert.equal(reloaded.state.algorithmsDeferred,true);
  assert.equal(reloaded.state.algorithms[0].id,'algorithm-b');
});
