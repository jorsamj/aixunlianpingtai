import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {trainingChartGroups,trainingCharts} from '../../static/modules/reports.js';

function harness(request){
 const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const start=source.indexOf('  let reportRequestSequence425=0');
 const end=source.indexOf('\n  window.openAiCause425=',start);
 const timers=new Map(),layers=[];let nextTimer=0,project='project-a',requests=0;
 const window={PlatformCore:{presentation:{loadingSkeleton:label=>label},reports:{trainingReportHtml:r=>`REPORT:${r.report?.identity?.version_id||'legacy'}`,mountTrainingReport(){}}}};
 const document={body:{},querySelector:selector=>selector.includes('loading')?layers.at(-1)?.loading:layers.at(-1)?.root};
 function modal(){
  const layer={root:{isConnected:true},querySelector:selector=>selector.includes('loading')?layer.loading:layer.root};
  layer.loading={isConnected:true,innerHTML:'正在读取当前任务报告与冻结证据…',listeners:{},querySelector:()=>({addEventListener:(type,callback)=>layer.retry=callback})};
  Object.defineProperty(layer.loading,'outerHTML',{set:html=>{layer.html=html;layer.loading.isConnected=false;}});
  layers.push(layer);return layer;
 }
 const context={window,document,modal,pid:()=>project,state:{algorithms:[]},api:(...args)=>{requests++;return request(...args)},esc:String,URLSearchParams,AbortController,Promise,Error,String,toast(){},closeModal(){},setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,ms});return id},clearTimeout:id=>timers.delete(id)};
 vm.runInNewContext(source.slice(start,end),context);
 return {window,layers,timers,get requests(){return requests},open:(id='job-a',selection={})=>window.trainingReportCore425(id,selection),runTimers:ms=>{for(const [id,t] of [...timers])if(t.ms===ms){timers.delete(id);t.fn()}},close(){window.beforeCloseTrainingReport425(layers.at(-1));layers.at(-1).loading.isConnected=false;},setProject:p=>project=p};
}
const valid=(version='version-a')=>({job:{id:'job-a'},report:{identity:{project_id:'project-a',algorithm_id:'algorithm-a',version_id:version}}});

test('report request deadline settles permanently pending API and exposes retry',async()=>{
 const h=harness(()=>new Promise(()=>{}));const pending=h.open();
 assert.ok([...h.timers.values()].some(t=>t.ms===20000),'request has bounded deadline');
 h.runTimers(20000);await pending;
 assert.match(h.layers[0].loading.innerHTML,/超时/);assert.match(h.layers[0].loading.innerHTML,/data-training-report-retry/);
 assert.equal(h.timers.size,0);
});
for(const status of [404,409,500,502,504])test(`HTTP ${status} report failure is actionable and retryable`,async()=>{
 const error=Object.assign(new Error('现场报告读取失败'),{code:`HTTP_${status}`});
 const h=harness(async()=>{throw error});await h.open();
 assert.match(h.layers[0].loading.innerHTML,new RegExp(String(status)));assert.match(h.layers[0].loading.innerHTML,/data-training-report-retry/);
});
test('closing report cancels API and prevents late response from mounting',async()=>{
 let resolve,signal;const h=harness((url,options)=>{signal=options?.signal;return new Promise(r=>resolve=r)});
 const pending=h.open();h.close();await pending;
 assert.equal(signal?.aborted,true);resolve(valid());await Promise.resolve();assert.equal(h.layers[0].html,undefined);assert.equal(h.timers.size,0);
});
test('rapid version switching rejects stale response and keeps latest report identity',async()=>{
 const resolves=[];const h=harness(()=>new Promise(resolve=>resolves.push(resolve)));
 const first=h.open('job-a',{algorithmId:'algorithm-a',versionId:'version-a'});
 const second=h.open('job-a',{algorithmId:'algorithm-a',versionId:'version-b'});
 resolves[1](valid('version-b'));await second;resolves[0](valid('version-a'));await first;
 assert.equal(h.layers[1].html,'REPORT:version-b');assert.equal(h.layers[0].html,undefined);assert.doesNotMatch(h.layers[0].loading.innerHTML,/正在读取/);
});
test('partial historical evidence still renders while mismatched project is rejected',async()=>{
 const h=harness(async()=>({job:{id:'job-a'},report:{}}));await h.open();assert.equal(h.layers[0].html,'REPORT:legacy');
 const bad=harness(async()=>({...valid(),report:{identity:{project_id:'other-project'}}}));await bad.open();
 assert.equal(bad.layers[0].html,undefined);assert.match(bad.layers[0].loading.innerHTML,/身份/);
});
test('report training charts retain actual gaps, zoom and legend without reset controls',()=>{
 const groups=trainingChartGroups([{epoch:1,map50:.5},{epoch:2,map50:null},{epoch:3,map50:.7}]);
 const chart=groups[0].options;assert.deepEqual(chart.series[0].data,[.5,null,.7]);assert.ok(chart.dataZoom.length);assert.ok(chart.legend);
 assert.equal(chart.toolbox?.feature?.restore,undefined);assert.doesNotMatch(trainingCharts([{epoch:1,map50:.5}]),/data-chart-reset|恢复视图/);
 assert.equal(typeof chart.tooltip.position,'function');assert.deepEqual(chart.tooltip.position([20,30],null,null,null,{viewSize:[400,300],contentSize:[100,80]}),[36,46]);
});

test('retry reads the same modal and succeeds without creating a second dialog',async()=>{
 let failures=true;const h=harness(async()=>{if(failures)throw new Error('temporary');return valid()});
 await h.open();failures=false;h.layers[0].retry();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(h.layers.length,1);assert.equal(h.requests,2);assert.equal(h.layers[0].html,'REPORT:version-a');assert.equal(h.timers.size,0);
});
for(const field of ['job_id','algorithm_id','version_id'])test(`report ${field} mismatch never renders another identity`,async()=>{
 const data=valid();data.report.identity[field]='other';const h=harness(async()=>data);
 await h.open('job-a',{algorithmId:'algorithm-a',versionId:'version-a'});
 assert.equal(h.layers[0].html,undefined);assert.match(h.layers[0].loading.innerHTML,/身份不一致/);
});
