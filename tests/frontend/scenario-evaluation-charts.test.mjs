import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as reports from '../../static/modules/reports.js';

const protocol='confidence_first_class_agnostic_iou_0.5';
const curveProtocol='same_class_confidence_first_iou_0.5_grid_0.05';
function evaluation(){return {per_class:[
  {class_id:0,label:'同名',ground_truth_count:4},{class_id:1,label:'同名',ground_truth_count:3},
  {class_id:2,label:'无GT',ground_truth_count:0}],
  confusion_matrix:{protocol,cells:[{actual:0,predicted:1,count:2,images:['wrong.jpg']},
    {actual:1,predicted:null,count:1,images:['missed.jpg']},{actual:null,predicted:0,count:0,images:[]}]},
  confidence_curve_protocol:curveProtocol,confidence_curves:[
    {class_id:0,label:'同名',points:[{confidence:0,precision:0,recall:1,f1:0},
      {confidence:.5,precision:null,recall:.5},{confidence:1,precision:1,recall:0,f1:0}]},
    {class_id:1,label:'同名',points:[{confidence:.5,precision:.8,recall:.6,f1:.68}]},
    {class_id:2,label:'无GT',points:[{confidence:.5,precision:1,recall:1,f1:1}]}]};}

test('evaluation chart exports are present and missing/unknown evidence creates no charts',()=>{
  assert.equal(typeof reports.evaluationChartGroups,'function');
  assert.equal(typeof reports.mountEvaluationCharts,'function');
  assert.deepEqual(reports.evaluationChartGroups({}),[]);
  const e=evaluation();e.confusion_matrix.protocol='unknown';e.confidence_curve_protocol='unknown';
  assert.deepEqual(reports.evaluationChartGroups(e),[]);
});

test('matrix keeps only real cells, duplicate label IDs, original evidence and background',()=>{
  const e=evaluation(),matrix=reports.evaluationChartGroups(e)[0];
  assert.equal(matrix.key,'evaluation-confusion');
  assert.deepEqual(matrix.cells,e.confusion_matrix.cells);
  assert.strictEqual(matrix.cells[0],e.confusion_matrix.cells[0]);
  assert.deepEqual(matrix.options.series[0].data.map(row=>row.value[2]),[2,1,0]);
  assert.equal(matrix.options.xAxis.data.length,4);
  assert.notEqual(matrix.options.xAxis.data[0],matrix.options.xAxis.data[1]);
  assert.match(matrix.options.xAxis.data.at(-1),/背景/);
  const tooltip=matrix.options.tooltip.formatter({dataIndex:0});
  assert.match(tooltip,/同名/);assert.match(tooltip,/0/);assert.match(tooltip,/1/);assert.match(tooltip,/2/);
});

test('matrix is capped at twenty class IDs plus background and discloses truncation',()=>{
  const e=evaluation();e.per_class=Array.from({length:30},(_,class_id)=>({class_id,label:'类'+class_id,ground_truth_count:1}));
  e.confusion_matrix.cells.push({actual:25,predicted:0,count:8,images:['excluded.jpg']});
  const matrix=reports.evaluationChartGroups(e)[0];
  assert.equal(matrix.options.xAxis.data.length,21);
  assert.match(matrix.title,/截断/);
  assert.equal(matrix.cells.some(cell=>cell.actual===25),false);
});

test('selected covered class alone supplies true confidence series and PR threshold samples',()=>{
  const e=evaluation(),groups=reports.evaluationChartGroups(e),curves=groups.filter(g=>g.key!=='evaluation-confusion');
  assert.equal(curves.length,2);
  const confidence=curves.find(g=>g.key==='evaluation-confidence-0');
  assert.deepEqual(confidence.options.series.find(s=>s.id==='precision').data,[[0,0],[.5,null],[1,1]]);
  assert.deepEqual(confidence.options.series.find(s=>s.id==='f1').data,[[0,0],[.5,null],[1,0]]);
  const pr=curves.find(g=>g.key==='evaluation-pr-0');
  assert.match(pr.title,/阈值采样/);assert.match(pr.title,/非AP/);
  assert.equal(pr.options.series[0].type,'scatter');
  assert.deepEqual(pr.options.series[0].data.map(row=>row.value),[[1,0],[0,1]]);
  assert.equal(pr.options.series[0].data[0].confidence,0);
  assert.deepEqual(reports.evaluationChartGroups(e,{classId:'1'}).map(g=>g.key),
    ['evaluation-confusion','evaluation-confidence-1','evaluation-pr-1']);
  assert.deepEqual(reports.evaluationChartGroups(e,{classId:2}).map(g=>g.key),['evaluation-confusion']);
});

test('missing and invalid numeric points never become zeros or fabricated curves',()=>{
  const e=evaluation();e.confidence_curves[0].points=[{confidence:0,precision:null,recall:false,f1:''},
    {confidence:.5,precision:NaN,recall:Infinity,f1:-1},{confidence:1,precision:1.1},
    {confidence:null,precision:1,recall:1,f1:1}];
  assert.deepEqual(reports.evaluationChartGroups(e).map(g=>g.key),['evaluation-confusion']);
});

test('unknown GT support never makes a class covered and diagnostics do not mutate evidence',()=>{
  const e=evaluation(),before=JSON.stringify(e);
  reports.evaluationChartGroups(e,{classId:1});assert.equal(JSON.stringify(e),before);
  e.per_class[0].ground_truth_count=Infinity;
  assert.deepEqual(reports.evaluationChartGroups(e,{classId:0}).map(g=>g.key),['evaluation-confusion']);
});

let moduleId=0;
async function runtime(load){
  const source=readFileSync(new URL('../../static/modules/reports.js',import.meta.url),'utf8')
    .replace("import('../vendor/echarts/echarts.min.js')",'globalThis.__scenarioEchartsLoad()');
  globalThis.__scenarioEchartsLoad=load;
  return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64')+'#'+(++moduleId));
}
function dom(keys){
  const hosts=new Map(keys.map(key=>[key,{key,clientWidth:600,style:{},textContent:''}]));
  const root={isConnected:true,hosts,querySelector(selector){return hosts.get(selector.match(/="([^"]+)"/)[1]);},
    querySelectorAll(selector){return selector==='[data-report-chart]'?[...hosts.values()]:[];},
    contains(host){return [...hosts.values()].includes(host);}};
  return root;
}
function fakeEcharts(){
  const instances=[];
  const echarts={init(host){
    const events=new Map();
    const chart={host,events,options:[],disposed:false,resizes:0,
      setOption(options,settings){this.options.push({options,settings});},resize(){this.resizes++;},
      on(event,handler){if(!events.has(event))events.set(event,new Set());events.get(event).add(handler);},
      off(event,handler){if(handler)events.get(event)?.delete(handler);else events.delete(event);},
      dispose(){this.disposed=true;events.clear();},emit(event,payload){for(const handler of events.get(event)||[])handler(payload);}};
    instances.push(chart);return chart;
  }};
  return {echarts,instances};
}
function installBrowser(){
  const observers=[];
  globalThis.ResizeObserver=class {constructor(callback){this.callback=callback;this.disconnected=false;observers.push(this);}observe(){}disconnect(){this.disconnected=true;}};
  globalThis.getComputedStyle=()=>({color:'#123456'});
  return observers;
}

test('shared runtime mounts once, rebinds exact matrix click, resizes and disposes switched groups',async()=>{
  const observers=installBrowser(),fake=fakeEcharts();let loads=0;
  const mod=await runtime(async()=>{loads++;globalThis.echarts=fake.echarts;});
  const e=evaluation(),root=dom(['evaluation-confusion','evaluation-confidence-0','evaluation-pr-0']);
  const first=[],second=[];
  await mod.mountEvaluationCharts(root,e,{onCell:cell=>first.push(cell)});
  await mod.mountEvaluationCharts(root,e,{onCell:cell=>second.push(cell)});
  assert.equal(loads,1);assert.equal(fake.instances.length,3);
  const matrix=fake.instances[0];assert.equal(matrix.events.get('click').size,1);
  matrix.emit('click',{componentType:'series',seriesType:'heatmap',dataIndex:0});
  assert.equal(first.length,0);assert.strictEqual(second[0],e.confusion_matrix.cells[0]);
  assert.deepEqual(second[0].images,['wrong.jpg']);
  const resizeCount=matrix.resizes;observers[0].callback();assert.ok(matrix.resizes>resizeCount);
  root.hosts.set('evaluation-confidence-1',{clientWidth:600,style:{}});
  root.hosts.set('evaluation-pr-1',{clientWidth:600,style:{}});
  await mod.mountEvaluationCharts(root,e,{classId:1,onCell:cell=>second.push(cell)});
  assert.equal(fake.instances[1].disposed,true);assert.equal(fake.instances[2].disposed,true);
  assert.equal(fake.instances.length,5);
  mod.disposeReportViews(root);
  assert.ok(fake.instances.every(chart=>chart.disposed));assert.ok(observers[0].disconnected);
  matrix.emit('click',{componentType:'series',seriesType:'heatmap',dataIndex:0});assert.equal(second.length,1);
});

test('loader failure is visible and retries, while dispose before load prevents late mounting',async()=>{
  installBrowser();const fake=fakeEcharts();let attempts=0;
  const mod=await runtime(async()=>{if(++attempts===1)throw new Error('offline');globalThis.echarts=fake.echarts;});
  const root=dom(['evaluation-confusion']);
  await mod.mountEvaluationCharts(root,evaluation());
  assert.match(root.hosts.get('evaluation-confusion').textContent,/加载失败/);
  await mod.mountEvaluationCharts(root,evaluation());assert.equal(attempts,2);assert.equal(fake.instances.length,1);
  assert.equal(root.hosts.get('evaluation-confusion').textContent,'');
  assert.equal(root.hosts.get('evaluation-confusion').style.height,'');
  mod.disposeReportViews(root);
  let release;
  const delayed=await runtime(()=>new Promise(resolve=>{release=()=>{globalThis.echarts=fake.echarts;resolve();};}));
  const late=dom(['evaluation-confusion']),pending=delayed.mountEvaluationCharts(late,evaluation());
  delayed.disposeReportViews(late);release();await pending;
  assert.equal(fake.instances.length,1);
});

test('training and evaluation share one loader and container cleanup, while detached clicks are inert',async()=>{
  installBrowser();const fake=fakeEcharts();let loads=0;
  const mod=await runtime(async()=>{loads++;globalThis.echarts=fake.echarts;});
  const training=dom(['accuracy']),scene=dom(['evaluation-confusion']),hits=[];
  await mod.mountReportCharts(training,[{epoch:1,map50:.5}]);
  await mod.mountEvaluationCharts(scene,evaluation(),{onCell:cell=>hits.push(cell)});
  assert.equal(loads,1);assert.equal(fake.instances.length,2);
  assert.equal(fake.instances[0].options[0].options.series[0].name,'mAP50');
  scene.isConnected=false;
  fake.instances[1].emit('click',{componentType:'series',seriesType:'heatmap',dataIndex:0});
  assert.equal(hits.length,0);
  mod.disposeReportViews({contains:root=>root===training||root===scene});
  assert.ok(fake.instances.every(chart=>chart.disposed));
});

test('an empty latest evaluation cancels a pending mount without leaving an observer',async()=>{
  const observers=installBrowser(),fake=fakeEcharts();let release;
  const mod=await runtime(()=>new Promise(resolve=>{release=()=>{globalThis.echarts=fake.echarts;resolve();};}));
  const root=dom(['evaluation-confusion']),pending=mod.mountEvaluationCharts(root,evaluation());
  await mod.mountEvaluationCharts(root,{});release();await pending;
  assert.equal(fake.instances.length,0);assert.equal(observers.length,0);
  mod.disposeReportViews(root);
});


test('main and training recovery resolve exactly one reports module URL and registry',()=>{
 const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8'),recovery=readFileSync(new URL('../../static/modules/training-recovery-runtime.js',import.meta.url),'utf8');
 const mainPath=main.match(/from ['"]([^'"]*reports\.js\?[^'"]+)['"]/)[1],recoveryPath=recovery.match(/from ['"]([^'"]*reports\.js\?[^'"]+)['"]/)[1];
 assert.equal(new URL(mainPath,'https://offline/static/main.mjs').href,new URL(recoveryPath,'https://offline/static/modules/training-recovery-runtime.js').href);
});
