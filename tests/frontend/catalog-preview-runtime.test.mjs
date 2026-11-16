import test from 'node:test';
import assert from 'node:assert/strict';
import {installCatalogPreview, PREVIEW_PAGE, MANAGEMENT_PAGE, NODES_PAGE} from '../../static/modules/catalog-preview-runtime.js';

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
