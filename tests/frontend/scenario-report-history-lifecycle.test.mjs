import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
function section(start,end){return source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)))}
test('removing the selected model cancels prior report loading even when its response arrives later',async()=>{
 let resolve,selected={algorithm_id:'a'},states=[];const reply=new Promise(yes=>resolve=yes),window={};
 vm.runInNewContext(`let reportController=null,comparisonController=null,comparisonSequence=0,comparison={},matrixCell=null,curveClass='',classPage=0,reportSequence=0,reportLoading=false,reportError='',reportVersion=null,reportModel=null;${section('  async function loadScenarioReport64(){','  function renderScenarioAccuracy64(){')}function renderScenarioAccuracy64(){states.push(reportLoading)}`,{window,state:{algorithms:[]},AbortController,pid:()=> 'p1',selectedModel64:()=>selected,loadScenarioComparison64:()=>{},states,withRequestDeadline:operation=>operation(),api:()=>reply,document:{querySelector:()=>({})},detectionModels64:()=>[],String,encodeURIComponent});
 const first=window.retryScenarioReport64();selected=null;await window.retryScenarioReport64();
 assert.equal(states.at(-1),false,'no selected model must immediately leave loading');resolve({id:'a',versions:[]});await first;assert.equal(states.at(-1),false);
});
function historyHarness(pending={id:'old',results:[]}){
 let resolve;const state={benchBatch64:pending},button={disabled:true,textContent:'检测中'},window={setScenarioMode64(){},renderBenchBatch64(){}};const reply=new Promise(yes=>resolve=yes),toasts=[];
 vm.runInNewContext(`let batchOpenSequence=0;${section('  window.openDetectionBatch64=async function(','\n  function benchNotices64(')}`,{window,state,pid:()=> 'p1',withRequestDeadline:operation=>operation(),api:()=>reply,document:{querySelector:()=>({}),getElementById:()=>button},batchFromDurable64:batch=>({id:batch.batch_id}),toast:text=>toasts.push(text),String,Number,encodeURIComponent});
 return {window,state,button,resolve,toasts};
}
test('late history response cannot replace a newly started run or unlock its button',async()=>{
 const h=historyHarness(),flight=h.window.openDetectionBatch64('history');const run={id:'new',running:true};h.state.benchBatch64=run;h.resolve({batch:{batch_id:'history',items:[]}});await flight;assert.equal(h.state.benchBatch64,run);assert.equal(h.button.disabled,true);
});
test('current history response still restores the requested batch',async()=>{const h=historyHarness(),flight=h.window.openDetectionBatch64('history');h.resolve({batch:{batch_id:'history',items:[]}});await flight;assert.equal(h.state.benchBatch64.id,'history');assert.equal(h.button.disabled,false)});
for(const item of [null,{index:0,models:{A:{task_id:'wrong-side'}}}])test(`unknown batch remains locked without its exact pending side task: ${item?'wrong side':'empty response'}`,async()=>{
 const pending={id:'unknown',outcomeUncertain:true,results:[{status:'unknown',itemIndex:0,pendingSide:'B'}]},h=historyHarness(pending),flight=h.window.openDetectionBatch64('unknown');h.resolve({batch:{batch_id:'unknown',items:item?[item]:[]}});await flight;assert.equal(h.state.benchBatch64,pending);assert.equal(h.button.disabled,true);assert.match(h.toasts[0],/禁止重复创建/);
});
