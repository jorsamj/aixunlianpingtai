import test from 'node:test';
import assert from 'node:assert/strict';
import {installCatalogPreview, PREVIEW_PAGE} from '../../static/modules/catalog-preview-runtime.js';

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
