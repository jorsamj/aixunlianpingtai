import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {withRequestDeadline} from '../../static/modules/api.js';
const source=readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
const start=source.indexOf('  window.openBenchFeedback64=async function('),end=source.indexOf('\n  window.openBenchResult64=',start);
function harness({detail=true,deadlineMs=1000}={}){
 let project='p1',resolve,reject,top;const calls={closed:0,opened:0,requests:0,toasts:[]};
 const shell={isConnected:true},dialog={isConnected:true,contains:node=>node===detailNode},detailNode={isConnected:true};top=detail?dialog:null;
 const button={isConnected:true,disabled:false,textContent:'提交抽检反馈',closest:selector=>selector==='.bench64-detail'&&detail?detailNode:null};
 const row={a:{task_id:'t1',m:{model_source:'algorithm_version',algorithm_id:'a',version_id:'v'}}};
 const state={page:'质量中心',benchBatch64:{results:[row]}};
 const document={querySelector:selector=>selector==='.scenario-workbench'?shell:selector==='.bench64-detail'&&detail?detailNode:null,querySelectorAll:()=>top?[top]:[]};
 const window={event:{currentTarget:button},NavigationStability:{action:()=>({isCurrent:()=>state.page==='质量中心'})},openPredictionFeedback63:()=>calls.opened++};
 const reply=new Promise((yes,no)=>{resolve=yes;reject=no});
 vm.runInNewContext(`let selectedIndex=0;${source.slice(start,end)}`,{window,state,document,pid:()=>project,canSubmitBenchFeedback64:()=>true,toast:text=>calls.toasts.push(text),api:()=>{calls.requests++;return reply},withRequestDeadline:(operation,options)=>withRequestDeadline(operation,{...options,timeoutMs:deadlineMs}),closeModal:async()=>{calls.closed++;top=null;detailNode.isConnected=false},String,Number,encodeURIComponent});
 return {state,window,button,shell,calls,resolve,reject,changeProject:()=>project='p2',replaceModal:()=>top={contains:()=>false},closeOrigin:()=>{top=null;detailNode.isConnected=false;button.isConnected=false}};
}
for(const change of ['project','row','page','close','new modal'])test(`late feedback response after ${change} cannot write or close another context`,async()=>{
 const h=harness(),flight=h.window.openBenchFeedback64(0,'A');
 if(change==='project')h.changeProject();if(change==='row')h.state.benchBatch64={results:[{}]};if(change==='page')h.state.page='数据集';if(change==='close')h.closeOrigin();if(change==='new modal')h.replaceModal();
 h.resolve({project_id:'p1'});await flight;assert.equal(h.state.lastOnlinePrediction63,undefined);assert.equal(h.calls.closed,0);assert.equal(h.calls.opened,0);
});
test('current original detail closes once then opens feedback with the resolved prediction',async()=>{const h=harness(),prediction={project_id:'p1'},flight=h.window.openBenchFeedback64(0,'A');h.resolve(prediction);await flight;assert.equal(h.state.lastOnlinePrediction63,prediction);assert.equal(h.calls.closed,1);assert.equal(h.calls.opened,1)});
test('detached button and stale failure never receive restoration or a toast',async()=>{const h=harness(),flight=h.window.openBenchFeedback64(0,'A');h.closeOrigin();h.reject(new Error('late'));await flight;assert.equal(h.button.textContent,'正在准备证据…');assert.equal(h.calls.toasts.length,0)});
test('inline current result opens feedback without closing a modal',async()=>{const h=harness({detail:false}),flight=h.window.openBenchFeedback64(0,'A');h.resolve({project_id:'p1'});await flight;assert.equal(h.calls.closed,0);assert.equal(h.calls.opened,1)});

test('feedback deadline restores only its current button and ignores a late accepted reply',async()=>{
 const h=harness({deadlineMs:5}),originalBatch=h.state.benchBatch64,flight=h.window.openBenchFeedback64(0,'A');
 try{await Promise.race([flight,new Promise(resolve=>setTimeout(resolve,30))]);assert.equal(h.button.disabled,false);assert.equal(h.calls.toasts.length,1);assert.match(h.calls.toasts[0],/超时/);assert.equal(h.calls.opened,0);assert.equal(h.calls.closed,0);assert.equal(h.calls.requests,1);assert.equal(h.state.benchBatch64,originalBatch);assert.equal(h.state.lastOnlinePrediction63,undefined)}
 finally{h.resolve({project_id:'p1'});await flight}
 assert.equal(h.state.lastOnlinePrediction63,undefined);assert.equal(h.calls.opened,0);
});
test('feedback deadline after navigation remains silent and never restores a detached control',async()=>{
 const h=harness({deadlineMs:5}),flight=h.window.openBenchFeedback64(0,'A');h.closeOrigin();
 try{await Promise.race([flight,new Promise(resolve=>setTimeout(resolve,30))]);assert.equal(h.button.disabled,true);assert.equal(h.calls.toasts.length,0)}finally{h.resolve({project_id:'p1'});await flight}
 assert.equal(h.state.lastOnlinePrediction63,undefined);
});
