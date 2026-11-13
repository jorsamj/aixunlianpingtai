import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const moduleSource=readFileSync(new URL('../../static/modules/training-resource-cards.js',import.meta.url),'utf8');
const appSource=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const html=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const familySummary=t=>Object.entries(t?.scan?.families||t?.algorithm_scan?.families||{}).slice(0,6).map(([k,v])=>`${k} ${v}`).join(' · ');
function setup(){
  const window={};
  runInNewContext(moduleSource,{window},{filename:'training-resource-cards.js'});
  return window.TrainingResourceCardsRuntime;
}

test('classic presenter loads before app.js and preserves its synchronous bridge',()=>{
  const resource=html.indexOf('/static/modules/training-resource-cards.js?v=42.25.601-13c04b');
  const classic=html.indexOf('/static/app.js?v=42.25.605');
  const module=html.indexOf('/static/main.mjs?v=42.25.605');
  assert.ok(resource>=0&&resource<classic&&classic<module);
  assert.match(appSource,/function trainingResourceCardsHtmlV3\(\)\{/);
  assert.match(appSource,/renderer\(state\.targets\|\|\[\],\{escape:esc,familySummary\}\)/);
  const bridge=appSource.slice(appSource.indexOf('function trainingResourceCardsHtmlV3(){'),appSource.indexOf('window.patchTrainingResourceCardsV3='));
  assert.doesNotMatch(bridge,/res-card/);
  assert.match(appSource,/window\.renderResourceBasePage=renderResources/);
  assert.match(appSource,/window\.patchTrainingResourceCardsV3=function\(\)/);
});

test('resource card renderer preserves ready, offline, Paddle, and server actions',()=>{
  const runtime=setup();
  assert.equal(Object.isFrozen(runtime),true);
  assert.equal(typeof runtime.render,'function');
  const targets=[
    {id:'server:gpu-1',name:'GPU <A>',framework:'ultralytics',type:'server',server_id:'srv-01',status:'ready',version:'1.2',algorithms:[{},{}],base_models:[{}]},
    {id:'local_paddle',name:'Paddle',framework:'paddle',type:'local',status:'offline',scan:{families:{YOLO:3}},algorithms:[],base_models:[]},
  ];
  const untouched=JSON.stringify(targets);
  const rendered=runtime.render(targets,{escape:esc,familySummary});
  assert.match(rendered,/GPU &lt;A&gt;/);
  assert.doesNotMatch(rendered,/GPU <A>/);
  assert.match(rendered,/class="res-card ready"/);
  assert.match(rendered,/不可用/);
  assert.match(rendered,/2 个算法/);
  assert.match(rendered,/1 个权重/);
  assert.match(rendered,/YOLO 3/);
  assert.match(rendered,/testSavedTrainServer/);
  assert.match(rendered,/viewResourceAlgorithms/);
  assert.equal(JSON.stringify(targets),untouched);
  assert.equal(runtime.render([],{escape:esc,familySummary}),'');
});

test('render output reflects changed status without retaining stale targets',()=>{
  const runtime=setup();
  const targets=[{id:'gpu-1',name:'GPU',framework:'ultralytics',status:'ready',algorithms:[],base_models:[]}];
  const first=runtime.render(targets,{escape:esc,familySummary});
  targets[0].status='offline';
  const second=runtime.render(targets,{escape:esc,familySummary});
  assert.match(first,/class="res-card ready"/);
  assert.match(second,/class="res-card warn"/);
  assert.notEqual(first,second);
});

test('extracted renderer owns no requests, timers, or page state',()=>{
  assert.doesNotMatch(moduleSource,/\bfetch\(|\bsetInterval\(|\baddEventListener\(|\bstate\./);
  assert.equal((appSource.match(/function trainingResourceCardsHtmlV3\(\)/g)||[]).length,1);
});
