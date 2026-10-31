import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('async function extras412(');
const end=source.indexOf('window.loadPageExtras413=extras412;',start);
assert.ok(start>=0&&end>start,'use the existing page extras owner');

function owner(){
  const state={project:{id:'project-a'},page:'质量中心',testModels:[{id:'generic-before',model_source:'builtin'}],scenarioTestModels:[{id:'scenario-before',scenario_eligible:true}]};
  const pending=[];
  const context={state,window:{},toast:message=>assert.fail(String(message)),api:url=>new Promise(resolve=>pending.push({url,resolve}))};
  vm.runInNewContext(source.slice(start,end)+'\nwindow.loadPageExtras413=extras412;',context);
  function finish(scope,models,project='project-a'){
    const matches=pending.filter(row=>row.url.includes(`/projects/${project}/test_models`)&&row.url.includes('model_scope=scenario')===(scope==='scenario'));
    assert.equal(matches.length,1,'one request for the selected model scope');
    matches[0].resolve({items:models});
  }
  function finishOther(){for(const row of pending)if(!row.url.includes('/test_models'))row.resolve({items:[]});}
  return {state,pending,load:context.window.loadPageExtras413,finish,finishOther};
}

test('late scenario response cannot replace the generic model catalogue',async()=>{
  const runtime=owner();
  const scenario=runtime.load('质量中心');
  runtime.state.page='部署测试';
  const generic=runtime.load('部署测试');
  const genericRows=[{id:'official',model_source:'builtin'},{id:'generic-version',model_source:'algorithm_version'}];
  const scenarioRows=[{id:'qualified',scenario_eligible:true}];
  runtime.finish('generic',genericRows);runtime.finishOther();await generic;
  runtime.finish('scenario',scenarioRows);await scenario;
  assert.equal(runtime.state.testModels,genericRows);
  assert.equal(runtime.state.scenarioTestModels,scenarioRows);
});

test('late generic response cannot replace the scenario model catalogue',async()=>{
  const runtime=owner();runtime.state.page='部署测试';
  const generic=runtime.load('部署测试');
  runtime.state.page='质量中心';
  const scenario=runtime.load('质量中心');
  const genericRows=[{id:'official',model_source:'builtin'}];
  const scenarioRows=[{id:'qualified',scenario_eligible:true}];
  runtime.finish('scenario',scenarioRows);runtime.finishOther();await scenario;
  runtime.finish('generic',genericRows);await generic;
  assert.equal(runtime.state.scenarioTestModels,scenarioRows);
  assert.equal(runtime.state.testModels,genericRows);
});

test('responses from a previous project cannot replace either model catalogue',async()=>{
  const runtime=owner();
  const scenario=runtime.load('质量中心'),generic=runtime.load('部署测试');
  runtime.state.project={id:'project-b'};
  const genericRows=[{id:'project-b-official'}],scenarioRows=[{id:'project-b-qualified'}];
  runtime.state.testModels=genericRows;runtime.state.scenarioTestModels=scenarioRows;
  runtime.finish('scenario',[{id:'stale-project-a-scenario'}]);
  runtime.finish('generic',[{id:'stale-project-a-generic'}]);runtime.finishOther();
  await Promise.all([scenario,generic]);
  assert.equal(runtime.state.testModels,genericRows);
  assert.equal(runtime.state.scenarioTestModels,scenarioRows);
});

test('an older read of the same catalogue cannot commit after a newer read on another visit',async()=>{
  const runtime=owner();
  const old=runtime.load('质量中心');
  runtime.state.page='部署测试';
  const generic=runtime.load('部署测试');
  runtime.state.page='质量中心';
  const current=runtime.load('质量中心');
  const newest=[{id:'new-scenario',scenario_eligible:true}];
  runtime.pending.filter(row=>row.url.includes('model_scope=scenario'))[1].resolve({items:newest});
  runtime.finishOther();
  await current;
  runtime.pending.filter(row=>row.url.includes('model_scope=scenario'))[0].resolve({items:[{id:'old-scenario'}]});
  await old;
  assert.equal(runtime.state.scenarioTestModels,newest);
  runtime.finish('generic',[{id:'generic-current'}]);
  await generic;
  assert.equal(runtime.state.scenarioTestModels,newest);
});
