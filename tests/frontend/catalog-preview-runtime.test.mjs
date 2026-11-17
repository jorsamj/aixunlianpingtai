import test from 'node:test';
import assert from 'node:assert/strict';
import {installCatalogPreview, PREVIEW_PAGE, MANAGEMENT_PAGE, NODES_PAGE, ASSETS_PAGE, HISTORY_PAGE, TASKS_PAGE, REPORT_PAGE, POOL_PAGE} from '../../static/modules/catalog-preview-runtime.js';

test('algorithm capability cannot mutate versions and tasks/report remain GET-only',async()=>{
 const owners=new Map(),contexts=[],calls=[],state={page:ASSETS_PAGE,project:{id:'p'}};
 const runtime=installCatalogPreview({algorithmEnabled:true,tasksEnabled:true,reportsEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return ()=>{}}},getState:()=>state,
 document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},deadline:(fn,{signal})=>fn(signal),request:async(url,options)=>{calls.push({url,options});return {ok:true}},
 load:async()=>({mountModelAssets:async(_host,context)=>{contexts.push(context);return ()=>{}},mountTrainingTasks:async(_host,context)=>{contexts.push(context);return ()=>{}},mountTrainingReport:async(_host,context)=>{contexts.push(context);return ()=>{}}})});
 await owners.get(ASSETS_PAGE)();const algorithm=contexts[0];await algorithm.writeAlgorithm('POST','',{name:'A'});assert.equal(calls[0].url,'/api/v12/projects/p/algorithms?asset_view=true');
 assert.throws(()=>algorithm.writeAlgorithm('PUT','a/versions/v',{remark:'x'}),/稳定算法ID/);assert.throws(()=>algorithm.writeAlgorithm('DELETE','a',{}),/不允许/);
 state.page=TASKS_PAGE;await owners.get(TASKS_PAGE)();const tasks=contexts[1];assert.equal(tasks.writeAlgorithm,undefined);assert.equal(tasks.post,undefined);await tasks.get('/api/v62/projects/p/tasks?reader_view=true');await assert.rejects(()=>tasks.get('/api/v62/projects/q/tasks?reader_view=true'),/不允许/);
 tasks.memory.report={jobId:'t',returnPage:'tasks'};state.page=REPORT_PAGE;await owners.get(REPORT_PAGE)();const report=contexts[2];assert.equal(report.post,undefined);assert.equal(report.writeAlgorithm,undefined);await report.get('/api/v44/projects/p/jobs/t/report?reader_view=true');await assert.rejects(()=>report.get('/api/v44/projects/p/jobs/other/report?reader_view=true'),/不允许/);runtime.destroy();
});

test('model browsing is GET-only and history cannot read another project, algorithm or version',async()=>{
 const owners=new Map(),contexts=[],calls=[],state={page:ASSETS_PAGE,project:{id:'p'}};
 const runtime=installCatalogPreview({assetsEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return ()=>{}}},getState:()=>state,
 document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},deadline:(fn,{signal})=>fn(signal),request:async(url,options)=>{calls.push({url,options});return {ok:true}},
 load:async()=>({mountModelAssets:async(_host,context)=>{contexts.push(context);return ()=>{}},mountConversionHistory:async(_host,context)=>{contexts.push(context);return ()=>{}}})});
 await owners.get(ASSETS_PAGE)();const assets=contexts[0];assert.equal(assets.post,undefined);
 await assets.get('/api/v12/projects/p/algorithms?summary_only=true&asset_view=true');
 for(const url of ['/api/v12/projects/q/algorithms?summary_only=true&asset_view=true','/api/v12/projects/p/algorithms/a','https://other.test/api/v12/projects/p/algorithms?summary_only=true&asset_view=true'])await assert.rejects(()=>assets.get(url),/不允许/);
 assets.memory.selection={algorithmId:'a',versionId:'v'};state.page=HISTORY_PAGE;await owners.get(HISTORY_PAGE)();const history=contexts[1];assert.equal(assets.signal.aborted,true);assert.equal(history.post,undefined);
 await history.get('/api/v42/projects/p/algorithms/a/versions/v/deployments?asset_view=true');
 for(const url of ['/api/v42/projects/q/algorithms/a/versions/v/deployments?asset_view=true','/api/v42/projects/p/algorithms/b/versions/v/deployments?asset_view=true','/api/v42/projects/p/algorithms/a/versions/other/deployments?asset_view=true','/api/v39/projects/p/deploy/jobs'])await assert.rejects(()=>history.get(url),/不允许/);
 assert.equal(calls.length,2);assert.ok(calls.every(call=>call.options.method==='GET'));runtime.leave();assert.equal(history.signal.aborted,true);runtime.destroy();
});

function harness(enabled = true) {
  const owners = new Map(), calls = [], mounts = [], hosts = [];
  const state = {page: PREVIEW_PAGE, project: {id: 'p'}};
  const document = {getElementById: () => ({replaceChildren: node => hosts.push(node)}), createElement: () => ({setAttribute(){},textContent:''})};
  const runtime = installCatalogPreview({enabled, navigation: {registerPageOwner(name, fn){owners.set(name, fn); return () => owners.delete(name)}},
    getState: () => state, request: async (url, options) => {calls.push({url, options}); return {ok:true}},
    deadline: fn => fn(new AbortController().signal), document,
    load: async () => ({mountCatalogPreview: async (_host, context) => {mounts.push(context); return () => calls.push('unmount')}})});
  return {runtime, owners, state, calls, mounts, hosts};
}

test('late legacy report navigation cannot open a modal on another page',async()=>{
 const owners=new Map(),contexts=[],state={page:REPORT_PAGE,project:{id:'p'}};let complete,opened=0;
 const previous=globalThis.window;globalThis.window={setPage:()=>new Promise(resolve=>complete=resolve),openJobReport429:()=>opened++};
 const runtime=installCatalogPreview({reportsEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return ()=>{}}},getState:()=>state,
 document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},load:async()=>({mountTrainingReport:async(_host,context)=>{contexts.push(context);return ()=>{}}})});
 try{await owners.get(REPORT_PAGE)();const navigation=contexts[0].legacyReport({jobId:'t',returnPage:'tasks'});state.page='服务节点';complete();await navigation;assert.equal(opened,0)}finally{runtime.destroy();globalThis.window=previous}
});

test('preview is opt-in and registers no owner when disabled', () => {
  const h = harness(false); assert.equal(h.owners.size, 0); h.runtime.leave();
});

test('preview delegates GETs to the original API, rejects other paths and releases its mount', async () => {
  const h = harness(); await h.owners.get(PREVIEW_PAGE)();
  await h.mounts[0].get('/api/v39/deploy/catalog/records?entity=vendors&observe_only=true');
  assert.equal(h.calls[0].options.method, 'GET');
  assert.ok(h.calls[0].options.signal);
  await assert.rejects(() => h.mounts[0].get('/api/v39/deploy/catalog/operations'), /只读/);
  h.runtime.leave(); assert.equal(h.mounts[0].signal.aborted, true);
  assert.equal(h.calls.filter(x => x === 'unmount').length, 1);
});

test('late module loading cannot mount after leaving or switching projects', async () => {
  let complete; const h = harness();
  h.runtime.destroy();
  const owners = new Map(); let mounted = false;
  const runtime = installCatalogPreview({enabled:true, navigation:{registerPageOwner(name, fn){owners.set(name,fn);return ()=>{}}},
    getState:()=>h.state, document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},
    load:()=>new Promise(resolve=>complete=resolve)});
  const pending = owners.get(PREVIEW_PAGE)(); runtime.leave();
  complete({mountCatalogPreview:()=>{mounted=true}}); await pending;
  assert.equal(mounted,false);
});

test('management delegates only original catalog writes; nodes remain GET-only',async()=>{
 const owners=new Map(),contexts=[],calls=[];const state={page:MANAGEMENT_PAGE,project:{id:'p'}};
 const runtime=installCatalogPreview({managementEnabled:true,nodesEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return ()=>{}}},getState:()=>state,createOperationId:()=> 'original-owner-id',
 document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},deadline:(fn,{signal})=>fn(signal),request:async(url,options)=>{calls.push({url,options});return {ok:true}},
 load:async()=>({mountCatalogPreview:async(_host,context)=>{contexts.push(context);return ()=>{}},mountServiceNodes:async(_host,context)=>{contexts.push(context);return ()=>{}}})});
 await owners.get(MANAGEMENT_PAGE)();const management=contexts[0];
 assert.equal(management.createOperationId(),'original-owner-id');
 await management.post('/api/v39/deploy/catalog/operations',{operation_id:'original-owner-id'});
 assert.equal(calls[0].options.method,'POST');
 assert.equal(calls[0].options.body,'{"operation_id":"original-owner-id"}');
 await management.get('/api/v39/deploy/catalog/operations/original-owner-id');
 assert.throws(()=>management.post('/api/v63/service-nodes',{}),/不允许/);
 const packet={operation_id:'pending-original',entity:'vendors'};management.pending.save(packet);runtime.leave();await owners.get(MANAGEMENT_PAGE)();assert.deepEqual(contexts[1].pending.value,packet);
 runtime.leave();state.project.id='q';await owners.get(MANAGEMENT_PAGE)();assert.deepEqual(contexts[2].pending.value,packet,'global catalog pending operation survives switching projects');
 runtime.leave();state.page=NODES_PAGE;await owners.get(NODES_PAGE)();const nodes=contexts[3];assert.equal(nodes.post,undefined);await nodes.get('/api/v63/service-nodes');await assert.rejects(()=>nodes.get('/api/v63/service-nodes/controller-snapshot'),/不允许/);
 assert.equal(calls.at(-1).options.method,'GET');runtime.destroy();
});

test('project change discards a late POST reply and keeps the exact pending packet',async()=>{
 const owners=new Map(),contexts=[];let resolve;const state={page:MANAGEMENT_PAGE,project:{id:'p'}};
 const runtime=installCatalogPreview({managementEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return ()=>{}}},getState:()=>state,
 document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},deadline:(fn,{signal})=>fn(signal),request:()=>new Promise(done=>resolve=done),load:async()=>({mountCatalogPreview:async(_host,context)=>{contexts.push(context);return ()=>{}}})});
 await owners.get(MANAGEMENT_PAGE)();const context=contexts[0],packet={operation_id:'same-request',entity:'vendors'};context.pending.save(packet);
 const response=context.post('/api/v39/deploy/catalog/operations',packet);state.project.id='next-project';resolve({ok:true});await assert.rejects(()=>response,/项目或页面/);assert.equal(context.signal.aborted,true);assert.deepEqual(context.pending.value,packet);runtime.destroy();
});


test('pool journal fails closed when browser persistence is unavailable',async()=>{
 const previous=globalThis.sessionStorage,owners=new Map();let context;
 globalThis.sessionStorage={getItem:()=>null,setItem(){throw new Error('storage full')},removeItem(){throw new Error('storage full')}};
 const runtime=installCatalogPreview({poolEnabled:true,navigation:{registerPageOwner(p,fn){owners.set(p,fn);return()=>{}}},getState:()=>({page:POOL_PAGE,project:{id:'p'}}),document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},load:async()=>({mountNegativePool:async(_host,c)=>{context=c;return()=>{}}})});
 try{await owners.get(POOL_PAGE)();assert.throws(()=>context.poolPending.save({operation_id:'original'}),/storage full/);assert.equal(context.poolPending.value,null)}finally{runtime.destroy();if(previous===undefined)delete globalThis.sessionStorage;else globalThis.sessionStorage=previous}
});


test('training operations delegate only to the original project-owned detail and log owner',async()=>{
 const owners=new Map(),contexts=[],calls=[],state={page:TASKS_PAGE,project:{id:'p'}};
 const previous=globalThis.window;
 globalThis.window={setPage:async page=>{state.page=page},openTrainingRecoveryDetail:id=>calls.push(['detail',id]),showTrainLog423:id=>calls.push(['log',id])};
 const runtime=installCatalogPreview({tasksEnabled:true,navigation:{registerPageOwner(name,fn){owners.set(name,fn);return()=>{}}},getState:()=>state,document:{getElementById:()=>({replaceChildren(){}}),createElement:()=>({setAttribute(){}})},load:async()=>({mountTrainingTasks:async(_host,context)=>{contexts.push(context);return()=>{}}})});
 try{await owners.get(TASKS_PAGE)();await contexts[0].legacyTask('train_a','log');assert.deepEqual(calls,[['log','train_a']]);state.page=TASKS_PAGE;await owners.get(TASKS_PAGE)();const context=contexts.at(-1);state.project={id:'other'};await context.legacyTask('train_a','detail');assert.equal(calls.length,1);assert.equal(context.post,undefined)}finally{runtime.destroy();globalThis.window=previous}
});
