import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  formatCacheBytes,
  materialCacheNodeRuntimeView,
  materialCacheStatusView,
  storageCacheSummary,
  storageCacheTruth,
  storageLifecycleView,
} from '../../static/modules/storage-cache-runtime.js';

test('lifecycle summary preserves measured zero and unavailable values without a physical total',()=>{
  const view=storageLifecycleView({metrics:{original_index_logical_bytes:{value:0,scope:'项目当前素材索引逻辑量'},thumbnail_cache_logical_bytes:{value:1024},worker_workspace_logical_bytes:{value:null},cleanup_pending_tasks:{value:null}}});
  assert.equal(view.find(row=>row.key==='original_index_logical_bytes').value,'0 B');
  assert.equal(view.find(row=>row.key==='thumbnail_cache_logical_bytes').value,'1.00 KB');
  assert.equal(view.find(row=>row.key==='worker_workspace_logical_bytes').value,'未获取');
  assert.equal(view.find(row=>row.key==='cleanup_pending_tasks').value,'未获取');
  assert.ok(storageLifecycleView({metrics:{original_index_logical_bytes:{value:'12'}}}).every(row=>row.value==='未获取'));
});

test('lifecycle summary reads once, force refreshes and isolates another project and shell',async()=>{
  const previousWindow=globalThis.window,previousDocument=globalThis.document;
  let project='p1',shell={querySelector:()=>null},finish,fail=false;const cards={storageLifecycleStatus61:{innerHTML:''}};const calls=[];
  try{
    globalThis.window={pid:()=>project,PlatformCore:{},getStorageSourcesSnapshot61:()=>[]};
    globalThis.document={getElementById:id=>cards[id] || null,querySelector:selector=>selector==='.storage61-shell'?shell:null};
    const {installStorageCacheRuntime}=await import('../../static/modules/storage-cache-runtime.js');
    const runtime=installStorageCacheRuntime({fetchImpl:async(url)=>{
      calls.push(url);
      if(url==='/api/v62/workers')return {ok:true,json:async()=>({items:[]})};
      if(url.includes('/p2/'))return new Promise(resolve=>{finish=resolve;});
      if(fail)return {ok:false,json:async()=>({detail:'HTTP 503'})};
      return {ok:true,json:async()=>({ok:true,project_id:'p1',metrics:{original_index_logical_bytes:{value:1024}}})};
    }});
    await runtime.refresh({sources:[]});await runtime.refresh({sources:[]});
    assert.equal(calls.filter(url=>url.includes('lifecycle-summary')).length,1);
    await runtime.refresh({sources:[],force:true});
    assert.equal(calls.filter(url=>url.includes('lifecycle-summary')).length,2);
    fail=true;await runtime.refresh({sources:[],force:true});
    assert.match(cards.storageLifecycleStatus61.innerHTML,/1\.00 KB/);
    assert.match(cards.storageLifecycleStatus61.innerHTML,/刷新失败，显示上次采样/);
    assert.match(cards.storageLifecycleStatus61.innerHTML,/HTTP 503/);
    project='p2';shell={querySelector:()=>null};const pending=runtime.refresh({sources:[]});
    await new Promise(resolve=>setImmediate(resolve));
    project='p3';shell=null;
    const current=cards.storageLifecycleStatus61.innerHTML;
    finish({ok:true,json:async()=>({project_id:'p2',metrics:{original_index_logical_bytes:{value:999999}}})});
    await pending;
    assert.equal(cards.storageLifecycleStatus61.innerHTML,current);
  }finally{
    if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow;
    if(previousDocument===undefined)delete globalThis.document;else globalThis.document=previousDocument;
  }
});

test('returning to a cached project fences the old force request without leaving refresh disabled',async()=>{
  const previousWindow=globalThis.window,previousDocument=globalThis.document;
  let shell={querySelector:()=>null},reads=0,finish,pending;
  const card={innerHTML:''};
  try{
    globalThis.window={pid:()=>'p1',PlatformCore:{},getStorageSourcesSnapshot61:()=>[]};
    globalThis.document={getElementById:id=>id==='storageLifecycleStatus61'?card:null,querySelector:selector=>selector==='.storage61-shell'?shell:null};
    const {installStorageCacheRuntime}=await import('../../static/modules/storage-cache-runtime.js');
    const response=value=>({ok:true,json:async()=>({ok:true,project_id:'p1',metrics:{original_index_logical_bytes:{value}}})});
    const runtime=installStorageCacheRuntime({fetchImpl:async url=>{
      if(url==='/api/v62/workers')return {ok:true,json:async()=>({items:[]})};
      if(++reads===1)return response(1024);
      return new Promise(resolve=>{finish=resolve;});
    }});
    await runtime.refresh();
    const old=pending=runtime.refresh({force:true});
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(card.innerHTML,/aria-busy="true"/);
    shell={querySelector:()=>null};
    await runtime.refresh();
    assert.match(card.innerHTML,/1\.00 KB/);
    assert.doesNotMatch(card.innerHTML,/aria-busy="true"|正在读取/);
    assert.equal(reads,2,'the cached page does not create another read');
    const current=card.innerHTML;
    finish(response(999999));
    await old;await new Promise(resolve=>setImmediate(resolve));
    assert.equal(card.innerHTML,current,'the abandoned force response cannot repaint the new shell');
  }finally{
    if(finish){finish({ok:true,json:async()=>({ok:true,project_id:'p1',metrics:{}})});await pending;}
    if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow;
    if(previousDocument===undefined)delete globalThis.document;else globalThis.document=previousDocument;
  }
});

test('failed Worker refresh preserves known nodes, reports the failure and recovers explicitly',async()=>{
  const previousWindow=globalThis.window,previousDocument=globalThis.document;
  const card={innerHTML:''},shell={querySelector:()=>({})};let mode='known';
  try{
    globalThis.window={PlatformCore:{},getStorageSourcesSnapshot61:()=>[]};
    globalThis.document={querySelector:selector=>selector==='.storage61-shell'?shell:null,getElementById:id=>id==='storageCacheStatus61'?card:null};
    const {installStorageCacheRuntime}=await import('../../static/modules/storage-cache-runtime.js');
    const runtime=installStorageCacheRuntime({fetchImpl:async()=>{
      if(mode==='503')return {ok:false,status:503};
      if(mode==='bad-json')return {ok:true,json:async()=>{throw new Error('bad JSON');}};
      return {ok:true,json:async()=>({items:[{node_id:'known-node',hostname:'known-host',worker_id:'worker',online:true}]})};
    }});
    await runtime.refresh();
    for(mode of ['503','bad-json']){
      await runtime.refresh({force:true});
      assert.equal(runtime.state().workerCount,1);
      assert.match(card.innerHTML,/known-host/);
      assert.match(card.innerHTML,/刷新失败.*上次.*刷新重试/);
    }
    mode='known';await runtime.refresh({force:true});
    assert.doesNotMatch(card.innerHTML,/刷新失败/);
  }finally{
    if(previousWindow===undefined)delete globalThis.window;else globalThis.window=previousWindow;
    if(previousDocument===undefined)delete globalThis.document;else globalThis.document=previousDocument;
  }
});

test('remote object storage exposes two-layer cache truth and immutable platform writes', () => {
  const truth = storageCacheTruth({type: 'oss', config: {}});
  assert.equal(truth.remote, true);
  assert.equal(truth.protectedWrites, true);
  assert.match(truth.cacheLabel, /SHA256/);
  assert.match(truth.cacheLabel, /Bundle/);
  assert.match(truth.protectionLabel, /禁止原地覆盖/);
  assert.match(truth.protectionLabel, /重新扫描/);
});

test('explicit legacy overwrite configuration is surfaced as unsafe instead of hidden', () => {
  const truth = storageCacheTruth({type: 's3', config: {protect_existing_objects: false}});
  assert.equal(truth.protectedWrites, false);
  assert.match(truth.protectionLabel, /允许原地覆盖/);
  assert.match(storageCacheSummary({type: 's3', config: {protect_existing_objects: false}}), /不建议/);
});

test('local storage does not pretend to use remote material cache', () => {
  const truth = storageCacheTruth({type: 'local', config: {}});
  assert.equal(truth.remote, false);
  assert.equal(truth.externalMutationRequiresRescan, false);
  assert.match(truth.cacheLabel, /本地直读/);
});

test('cache status projection exposes maintained bytes files quota and ttl', () => {
  const view = materialCacheStatusView({
    after_bytes: 3 * 1024 * 1024 * 1024,
    max_bytes: 128 * 1024 * 1024 * 1024,
    ttl_seconds: 30 * 86400,
    scanned_files: 100,
    evicted_files: 4,
    over_budget_bytes: 0,
    generated_at: '2026-09-16T00:00:00+00:00',
  });
  assert.equal(view.available, true);
  assert.equal(view.usage, '3.00 GB');
  assert.equal(view.files, '96');
  assert.equal(view.limit, '128 GB');
  assert.equal(view.ttl, '30 天');
  assert.equal(view.overBudget, false);
  assert.equal(formatCacheBytes(0), '0 B');
});

test('missing maintenance snapshot is explicit rather than rendered as zero usage', () => {
  const view = materialCacheStatusView(null);
  assert.equal(view.available, false);
  assert.equal(view.usage, '未知');
  assert.equal(view.files, '-');
});

test('multiple workers on one node collapse into one cache node without byte summation', () => {
  const snapshot = {
    after_bytes: 5 * 1024 * 1024,
    max_bytes: 100 * 1024 * 1024,
    ttl_seconds: 86400,
    scanned_files: 20,
    evicted_files: 2,
    over_budget_bytes: 0,
    generated_at: '2026-09-16T01:00:00+00:00',
  };
  const report = {
    reporter_worker_id: 'worker-background',
    cache_scope: 'configured_cache_dir',
    cache_root_source: 'MC_MATERIAL_CACHE_DIR',
    reported_at: '2026-09-16T01:00:10+00:00',
    snapshot_generated_at: '2026-09-16T01:00:00+00:00',
    snapshot,
  };
  const view = materialCacheNodeRuntimeView([
    {
      worker_id: 'worker-training', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:00:11+00:00', material_cache: report,
    },
    {
      worker_id: 'worker-background', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:00:12+00:00', material_cache: report,
    },
  ]);

  assert.equal(view.aggregation, 'per_node_only_no_sum');
  assert.equal(view.knownNodeCount, 1);
  assert.equal(view.onlineNodeCount, 1);
  assert.equal(view.snapshotNodeCount, 1);
  assert.equal(view.unknownSnapshotNodeCount, 0);
  assert.equal(view.nodes[0].workerCount, 2);
  assert.equal(view.nodes[0].onlineWorkerCount, 2);
  assert.equal(view.nodes[0].snapshot.usage, '5.00 MB');
  assert.equal(view.nodes[0].scopeLabel, '独立缓存目录');
  assert.equal(view.nodes[0].state, '已上报');
});

test('cache report becomes stale when its reporter worker is no longer online', () => {
  const view = materialCacheNodeRuntimeView([
    {
      worker_id: 'worker-live', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:01:00+00:00',
      material_cache: {
        reporter_worker_id: 'worker-gone',
        cache_scope: 'data_dir_cache',
        cache_root_source: 'data_dir',
        reported_at: '2026-09-16T00:59:00+00:00',
        snapshot: {
          after_bytes: 1024,
          max_bytes: 2048,
          ttl_seconds: 0,
          scanned_files: 1,
          evicted_files: 0,
          generated_at: '2026-09-16T00:58:00+00:00',
        },
      },
    },
  ]);

  assert.equal(view.nodes[0].reporterFresh, false);
  assert.equal(view.nodes[0].state, '上报已过期');
  assert.equal(view.snapshotNodeCount, 0);
  assert.equal(view.unknownSnapshotNodeCount, 1);
  assert.equal(view.nodes[0].scopeLabel, '数据目录兼容缓存');
});

test('cache report becomes stale when reporter heartbeat advances but report hook stops advancing', () => {
  const view = materialCacheNodeRuntimeView([
    {
      worker_id: 'worker-live', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:05:00+00:00',
      material_cache: {
        reporter_worker_id: 'worker-live',
        cache_scope: 'configured_cache_dir',
        cache_root_source: 'MC_MATERIAL_CACHE_DIR',
        reported_at: '2026-09-16T01:04:30+00:00',
        snapshot: {
          after_bytes: 4096,
          max_bytes: 8192,
          ttl_seconds: 86400,
          scanned_files: 4,
          evicted_files: 0,
          generated_at: '2026-09-16T01:04:00+00:00',
        },
      },
    },
  ]);

  assert.equal(view.nodes[0].online, true);
  assert.equal(view.nodes[0].reporterFresh, false);
  assert.equal(view.nodes[0].state, '上报已过期');
  assert.equal(view.snapshotNodeCount, 0);
  assert.equal(view.unknownSnapshotNodeCount, 1);
});


const runtimeSource = fs.readFileSync(new URL('../../static/modules/storage-cache-runtime.js', import.meta.url), 'utf8');
const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const mainSource = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('storage cache decorations do not wrap canonical public owners or refetch storage sources', () => {
  for (const token of ['originalRender', 'originalOpen', 'originalTypeChanged', '__storageCacheRuntimeWrapped']) {
    assert.equal(runtimeSource.includes(token), false, token);
  }
  assert.doesNotMatch(runtimeSource, /window\.renderStorageSources61\s*=/);
  assert.doesNotMatch(runtimeSource, /window\.openStorageSource61\s*=/);
  assert.doesNotMatch(runtimeSource, /window\.storageTypeChanged61\s*=/);
  assert.doesNotMatch(runtimeSource, /fetchImpl\('\/api\/v61\/storage-sources'/);
  assert.match(runtimeSource, /WORKER_CACHE_TTL_MS = 2 \* 60 \* 1000/);
  assert.match(runtimeSource, /workerInflight/);
  assert.match(appSource, /window\.getStorageSourcesSnapshot61=/);
  assert.match(appSource, /window\.StorageCacheRuntime\?\.decorate\?\./);
  assert.match(appSource, /window\.StorageCacheRuntime\?\.decorateEditor\?\./);
  assert.match(mainSource, /page === '存储配置'/);
  assert.match(mainSource, /StorageCacheRuntime\?\.refresh/);
});


test('storage worker discovery throttles a failed request on rapid revisit but permits explicit refresh', async () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  let calls = 0;
  try {
    globalThis.window = {PlatformCore: {}, getStorageSourcesSnapshot61: () => []};
    globalThis.document = {getElementById: () => null, querySelector: () => null};
    const {installStorageCacheRuntime} = await import('../../static/modules/storage-cache-runtime.js');
    const runtime = installStorageCacheRuntime({
      fetchImpl: async () => {
        calls += 1;
        if (calls === 1) throw new Error('worker request interrupted by navigation');
        return {ok: true, json: async () => ({items: []})};
      },
      notify: () => {},
    });
    await runtime.refresh({sources: []});
    await runtime.refresh({sources: []});
    assert.equal(calls, 1, 'rapid revisit cannot emit a second workers GET');
    await runtime.refresh({sources: [], force: true});
    assert.equal(calls, 2, 'explicit refresh can recover the worker request');
    assert.equal(runtime.state().workerInflight, false);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
