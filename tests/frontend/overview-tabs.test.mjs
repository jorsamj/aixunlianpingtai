import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {OVERVIEW_TABS,buildAlgorithmMap,buildComputeMap,installOverviewTabsRuntime} from '../../static/modules/overview-tabs.js';

test('overview tabs expose three exclusive dashboard views, preserving old production owner', () => {
  assert.deepEqual(OVERVIEW_TABS.map(x=>x.label),['算法一张图','算力一张图']);
  const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
  assert.match(main,/\['总览', 'renderDashboardCanonical422'\]/);
  assert.match(main,/registerPageOwner\(\s*'总览', \(\) => overviewTabsRuntime\.render\(\)/);
  assert.match(main,/installOverviewTabsRuntime/);
});

test('algorithm types sort by real inventory; quality is not strategy accuracy or use frequency',()=>{
  const algs=[
    {id:'a',name:'烟雾',algorithm_type:'yolo',industry:'安防'},
    {id:'b',name:'火焰',algorithm_type:'yolo',industry:'安防'},
    {id:'c',name:'分类器',algorithm_type:'paddle',industry:'巡查'},
  ];
  const snapshot=buildAlgorithmMap(algs,{algorithms:[{id:'b',metrics:{map50:0.82,precision:0.75,recall:0.8}},{id:'a',metrics:{map50:null}}]});
  assert.equal(snapshot.total,3);
  assert.deepEqual(snapshot.types,[{name:'yolo',count:2},{name:'paddle',count:1}]);
  assert.equal(snapshot.scores.length,3);
  assert.equal(snapshot.measured,1);
  assert.equal(snapshot.scores[0].map50,82);
  assert.equal(snapshot.scores[0].precision,75);
  assert.equal(snapshot.strategyAccuracy,null);
  assert.deepEqual(snapshot.usage,[]);
  assert.deepEqual(snapshot.units,[]);
  assert.equal(buildAlgorithmMap([],null).scores.length,0);
  assert.equal(buildAlgorithmMap([],null).measured,0);
});

test('capacity only aggregates fresh online-node telemetry and explicit placement',()=>{
  const nodes=[
    {node_id:'a',placement:'center',connection_mode:'agent',status:'ONLINE',online:true,resources:{
      cpu:{usage_percent:40},memory:{usage_percent:55},disk:{usage_percent:10},
      gpu:{gpus:[{uuid:'GPU-a',name:'A800',memory_total_bytes:100,memory_used_bytes:20,utilization_percent:30}]}}},
    {node_id:'b',placement:'edge',connection_mode:'agent',status:'ONLINE',online:true,resources:{
      cpu:{usage_percent:90},memory:{usage_percent:70},disk:{usage_percent:65},gpu:{gpus:[]}}},
    {node_id:'c',placement:'unclassified',connection_mode:'local',status:'OFFLINE',online:false,resources:{
      cpu:{usage_percent:99},memory:{usage_percent:99},disk:{usage_percent:99},
      gpu:{gpus:[{uuid:'GPU-stale',name:'stale'}]}}},
  ];
  const stats=buildComputeMap(nodes,[{type:'oss'},{type:'local'}],{
    max_concurrent_per_gpu:1,memory_safety_bytes:10,
    gpus:[{node_id:'a',gpu_uuid:'GPU-a',metrics_fresh:true,telemetry_available:true,
      active_tasks:0,reserved_bytes:0,total_bytes:100,free_bytes:80}],
  });
  assert.equal(stats.nodeCount,3);
  assert.equal(stats.online,2);
  assert.equal(stats.offline,1);
  assert.equal(stats.cpuAvg,65);
  assert.equal(stats.gpuCount,1);
  assert.equal(stats.gpuFreeCandidates,1);
  assert.equal(stats.gpuMeasured,1);
  assert.deepEqual(stats.gpuByPlacement,{center:1,edge:0,unclassified:0});
  assert.equal(stats.placement.unclassified.length,1);
  assert.equal(stats.storageCount,2);
  assert.equal(stats.cloudBytes,null);
  assert.equal(stats.storageBytes,null);
  assert.equal(stats.warnings,2);
});

test('unknown GPU runtime evidence must never be interpreted as available',()=>{
  const data=buildComputeMap([{node_id:'x',placement:'unclassified',connection_mode:'local',status:'ONLINE',online:true,resources:{
    gpu:{gpus:[{uuid:'GPX',memory_free_bytes:300,utilization_percent:0}]}}}],[],null);
  assert.equal(data.gpuCount,1);
  assert.equal(data.gpuMeasured,0);
  assert.equal(data.gpuFreeCandidates,0);
  assert.equal(data.placement.unclassified.length,1);
});


test('GPU telemetry without reservation ledger cannot claim schedulable candidates',()=>{
  const nodes=[{node_id:'n',status:'ONLINE',online:true,placement:'center',resources:{gpu:{gpus:[{uuid:'g',memory_total_bytes:1000,memory_used_bytes:0,utilization_percent:0}]}}}];
  const runtime={gpus:[{node_id:'n',gpu_uuid:'g',metrics_fresh:true,telemetry_available:true,free_bytes:1000}]};
  const x=buildComputeMap(nodes,[],runtime);
  assert.equal(x.gpuMeasured,0);
  assert.equal(x.gpuFreeCandidates,0);
  assert.equal(x.gpus[0].admission,'unknown');
  const withLedger=buildComputeMap(nodes,[],{...runtime,max_concurrent_per_gpu:1,memory_safety_bytes:20,
    gpus:[{...runtime.gpus[0],active_tasks:1,reserved_bytes:400,total_bytes:1000}]});
  assert.equal(withLedger.gpuMeasured,1);
  assert.equal(withLedger.gpuFreeCandidates,0);
  assert.equal(withLedger.gpus[0].admission,'occupied');
});

test('disabled, disconnected and offline nodes retain status but do not reuse stale usage metrics',()=>{
  const nodes=[
    {node_id:'on',status:'ONLINE',online:true,placement:'center',resources:{cpu:{usage_percent:90},gpu:{gpus:[]}}},
    {node_id:'off',status:'OFFLINE',online:false,placement:'edge',resources:{cpu:{usage_percent:100}}},
    {node_id:'disabled',status:'DISABLED',online:false,resources:{cpu:{usage_percent:100}}},
    {node_id:'never',status:'NEVER_CONNECTED',online:false,resources:{cpu:{usage_percent:100}}},
  ];
  const m=buildComputeMap(nodes);
  assert.equal(m.nodeCount,4);
  assert.equal(m.nodes.length,4);
  assert.equal(m.online,1);
  assert.equal(m.disabled,1);
  assert.equal(m.neverConnected,1);
  assert.equal(m.cpuAvg,90);
  assert.equal(m.nodes.find(n=>n.id==='off').cpu,null);
  assert.equal(m.warnings,2);
  assert.equal(m.monitoredNodeCount,2);
});

test('algorithm model version counts are distinct from measured model quality',()=>{
  const m=buildAlgorithmMap([{id:'x',versions:[{id:'v1'},{id:'v2'}]},{id:'y',versions:[]}],{algorithms:[]});
  assert.equal(m.total,2);assert.equal(m.withVersions,1);assert.equal(m.versionCount,2);assert.equal(m.measured,0);
});

test('overview request identity fence rejects stale A → B → A response and fetches scoped algorithms',async()=>{
  const old=globalThis.document;
  const view={innerHTML:'',insertAdjacentHTML(position,html){this.innerHTML=position==='afterbegin'?html+this.innerHTML:this.innerHTML+html},querySelector(){return {addEventListener(){}}},querySelectorAll(){return []}};
  const state={page:'总览',project:{id:'A'},algorithms:[]};
  const pending=[];
  globalThis.document={getElementById(id){return id==='view'?view:null}};
  try{
    const runtime=installOverviewTabsRuntime({getState:()=>state,renderProduction(){view.innerHTML=''},request(url){
      return new Promise((resolve,reject)=>pending.push({url,resolve,reject}));
    }});
    runtime.select('algorithm');
    const first=pending.splice(0);assert.equal(first.length,2);
    state.project={id:'B'};runtime.render();const second=pending.splice(0);assert.equal(second.length,2);
    state.project={id:'A'};runtime.render();const third=pending.splice(0);assert.equal(third.length,2);
    for(const x of first)x.resolve(x.url.includes('quality-overview')?{algorithms:[]}:{items:[{id:'stale',name:'旧项目数据'}]});
    for(const x of second)x.resolve(x.url.includes('quality-overview')?{algorithms:[]}:{items:[]});
    await new Promise(resolve=>setImmediate(resolve));
    assert.doesNotMatch(view.innerHTML,/旧项目数据/);
    for(const x of third)x.resolve(x.url.includes('quality-overview')?{algorithms:[]}:{items:[{id:'fresh',name:'新项目数据',algorithm_type:'yolo'}]});
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(view.innerHTML,/新项目数据/);
    assert.doesNotMatch(view.innerHTML,/旧项目数据/);
    assert.ok(third.some(x=>x.url==='/api/v12/projects/A/algorithms'));
  }finally{globalThis.document=old}
});

test('failed algorithm fetch cannot present former algorithm totals as live',async()=>{
  const old=globalThis.document;
  const view={innerHTML:'',insertAdjacentHTML(position,html){this.innerHTML=position==='afterbegin'?html+this.innerHTML:this.innerHTML+html},querySelector(){return {addEventListener(){}}},querySelectorAll(){return []}};
  globalThis.document={getElementById(){return view}};
  const state={page:'总览',project:{id:'P'}};
  let fail=false;
  try{
    const runtime=installOverviewTabsRuntime({getState:()=>state,renderProduction(){view.innerHTML=''},request:async url=>{
      if(fail&&url.includes('/algorithms'))throw new Error('offline');
      return url.includes('quality-overview')?{algorithms:[]}:{items:[{id:'one',name:'旧算法'}]};
    }});
    runtime.select('algorithm');await runtime.refresh();
    assert.match(view.innerHTML,/旧算法/);
    fail=true;await runtime.refresh();
    assert.match(view.innerHTML,/offline/);
    assert.doesNotMatch(view.innerHTML,/旧算法/);
  }finally{globalThis.document=old}
});

test('local controller snapshot is a read-only observer, not a schedulable Agent',()=>{
 const backend=readFileSync(new URL('../../platform_core/service_nodes.py',import.meta.url),'utf8');
 const frontend=readFileSync(new URL('../../static/modules/overview-tabs.js',import.meta.url),'utf8');
 assert.match(backend,/controller-snapshot/);
 assert.match(backend,/scheduler_admission.*not_evaluated/);
 assert.match(frontend,/service-nodes\/controller-snapshot/);
});

test('merged production quality request is reused instead of issuing a duplicate',async()=>{
  const previous=globalThis.document;
  const view={innerHTML:'',insertAdjacentHTML(position,html){this.innerHTML=position==='afterbegin'?html+this.innerHTML:this.innerHTML+html},querySelector(){return {addEventListener(){}}},querySelectorAll(){return []}};
  let resolve;
  const qualityPromise=new Promise(done=>{resolve=done});
  const state={page:'总览',project:{id:'P'},algorithms:[],v42:{quality:null},
    dashboard422ExtrasProjectId:'',dashboard422ExtrasRefreshPromise:qualityPromise};
  const calls=[];
  globalThis.document={getElementById(){return view}};
  try{
    const runtime=installOverviewTabsRuntime({getState:()=>state,renderProduction(){view.innerHTML=''},
      request:async url=>{calls.push(url);return {items:[{id:'a',name:'真实算法'}]}}});
    runtime.render();
    state.v42.quality={algorithms:[{id:'a',metrics:{map50:0.88}}]};
    state.dashboard422ExtrasProjectId='P';
    resolve(true);
    await new Promise(done=>setImmediate(done));
    assert.equal(calls.filter(url=>url.includes('quality-overview')).length,0);
    assert.match(view.innerHTML,/真实算法/);
    assert.match(view.innerHTML,/88.0%/);
  }finally{globalThis.document=previous}
});


test('local controller stays visible if service-node API fails without claiming zero Agent nodes',async()=>{
  const original=globalThis.document;
  const view={innerHTML:'',insertAdjacentHTML(position,html){this.innerHTML=position==='afterbegin'?html+this.innerHTML:this.innerHTML+html},querySelector(){return {addEventListener(){}}},querySelectorAll(){return []}};
  globalThis.document={getElementById:()=>view};
  const state={page:'总览',project:{id:'P'}};
  try{
    const rt=installOverviewTabsRuntime({getState:()=>state,renderProduction(){view.innerHTML=''},request:async url=>{
      if(url==='/api/v63/service-nodes')throw Error('HTTP 503');
      if(url.endsWith('/controller-snapshot'))return {name:'控制端（本机）',sampled_at:'2026-10-10T00:00:00Z',
        resources:{cpu:{usage_percent:19},memory:{usage_percent:25,used_bytes:25,total_bytes:100},
          disk:{usage_percent:10,used_bytes:10,total_bytes:100},gpu:{gpus:[]}}};
      if(url.includes('gpu-runtime'))return {gpus:[]};
      return {items:[]};
    }});
    rt.select('compute');await rt.refresh();
    assert.match(view.innerHTML,/控制端 · 本机资源/);
    assert.match(view.innerHTML,/HTTP 503/);
    assert.match(view.innerHTML,/节点状态尚未取得/);
    assert.doesNotMatch(view.innerHTML,/服务节点<\/span><strong>0/);
  }finally{globalThis.document=original}
});

// The same triple-click gesture is scoped to the active tab and never mutates
// backend snapshots, live statistics or production dashboard ownership.
test('each overview tab switches into isolated demo fixtures and restores live data',async()=>{
  const previous=globalThis.document;
  let tabHandler,exitHandler,productionRenders=0;
  const view={
    innerHTML:'',
    insertAdjacentHTML(position,html){this.innerHTML=position==='afterbegin'?html+this.innerHTML:this.innerHTML+html},
    querySelector(selector){
      if(selector==='[data-overview-tabs]')return {addEventListener(_,cb){tabHandler=cb}};
      if(selector==='[data-overview-demo-exit]')return {addEventListener(_,cb){exitHandler=cb}};
      return null;
    },
    querySelectorAll(){return []},
  };
  globalThis.document={getElementById(id){return id==='view'?view:null}};
  const state={page:'总览',project:{id:'test-project'}};
  const requests=[];
  try{
    const rt=installOverviewTabsRuntime({
      getState:()=>state,
      renderProduction(){productionRenders++;view.innerHTML='<section>真实生产看板</section>'},
      request:async url=>{
        requests.push(url);
        if(url.includes('/algorithms'))return {items:[{id:'real-a',name:'真实模型',algorithm_type:'yolo',versions:[]}]};
        if(url.includes('quality-overview'))return {algorithms:[]};
        if(url.endsWith('/service-nodes'))return {items:[]};
        if(url.includes('storage-sources'))return {items:[]};
        if(url.includes('gpu-runtime'))return {gpus:[]};
        return {name:'控制端（本机）',sampled_at:'2026-10-12T02:00:00Z',resources:{cpu:{usage_percent:12},gpu:{gpus:[]}}};
      },
    });
    const click=tab=>tabHandler({target:{closest(selector){
      return selector==='[data-overview-tab]'?{dataset:{overviewTab:tab}}:null;
    }}});
    rt.render();await new Promise(resolve=>setImmediate(resolve));
    assert.match(view.innerHTML,/真实模型/);
    const requestsBeforeDemo=requests.length;
    const liveRenders=productionRenders;
    for(let i=0;i<3;i++)click('algorithm');
    assert.match(view.innerHTML,/data-overview-demo="true"/);
    assert.match(view.innerHTML,/ov352-dashboard/);
    assert.match(view.innerHTML,/样例数据/);
    assert.match(view.innerHTML,/返回实时/);
    assert.doesNotMatch(view.innerHTML,/演示|模拟/);
    assert.doesNotMatch(view.innerHTML,/演示数据模式|不参与真实统计或任务调度|所有服务器、GPU、利用率、容量均为模拟/);
    assert.match(view.innerHTML,/12,840 次/);
    assert.match(view.innerHTML,/94.6%/);
    assert.doesNotMatch(view.innerHTML,/真实模型|真实生产看板/);
    assert.equal(productionRenders,liveRenders+2);
    assert.equal(requests.length,requestsBeforeDemo);
    exitHandler();await new Promise(resolve=>setImmediate(resolve));
    assert.match(view.innerHTML,/真实模型/);
    assert.match(view.innerHTML,/真实生产看板/);
    click('compute');await new Promise(resolve=>setImmediate(resolve));
    assert.doesNotMatch(view.innerHTML,/data-overview-demo="true"/);
    for(let i=0;i<2;i++)click('compute');
    assert.match(view.innerHTML,/data-overview-demo="true"/);
    assert.match(view.innerHTML,/ov352-dashboard/);
    assert.match(view.innerHTML,/样例数据/);
    assert.match(view.innerHTML,/返回实时/);
    assert.doesNotMatch(view.innerHTML,/演示|模拟/);
    assert.doesNotMatch(view.innerHTML,/演示数据模式|不参与真实统计或任务调度|所有服务器、GPU、利用率、容量均为模拟/);
    assert.match(view.innerHTML,/GPU 训练服务器 A/);
    assert.doesNotMatch(view.innerHTML,/94.6%/);
    click('algorithm');await new Promise(resolve=>setImmediate(resolve));
    assert.doesNotMatch(view.innerHTML,/data-overview-demo="true"/);
    assert.match(view.innerHTML,/真实模型/);
  }finally{globalThis.document=previous}
});

test('both overview pages use consistent responsive dashboard sections and visible source attribution',()=>{
  const js=readFileSync(new URL('../../static/modules/overview-tabs.js',import.meta.url),'utf8');
  const css=readFileSync(new URL('../../static/overview-tabs.css',import.meta.url),'utf8');
  assert.match(js,/ov352-dashboard ov352-algorithm/);
  assert.match(js,/ov352-dashboard ov352-compute/);
  assert.match(js,/ov352-compute-intro/);
  assert.match(js,/ov352-device-grid/);
  assert.match(js,/data-overview-demo="true"><span>样例数据/);
  assert.match(js,/数据来源：界面样例数据/);
  assert.doesNotMatch(js,/演示/);
  assert.match(css,/\.ov352-dashboard \.ov348-kpis\{display:grid;grid-template-columns:repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(css,/@media\(max-width:900px\)/);
  assert.match(css,/\.ov352-source\{/);
});
