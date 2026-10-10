import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {OVERVIEW_TABS,buildAlgorithmMap,buildComputeMap} from '../../static/modules/overview-tabs.js';

test('overview tabs expose three exclusive dashboard views, preserving old production owner', () => {
  assert.deepEqual(OVERVIEW_TABS.map(x=>x.label),['算法生产总览','算法一张图','算力一张图']);
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
    gpus:[{node_id:'a',gpu_uuid:'GPU-a',metrics_fresh:true,telemetry_available:true,active_tasks:0,free_bytes:80}],
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
