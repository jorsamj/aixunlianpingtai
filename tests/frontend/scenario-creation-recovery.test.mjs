import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../../static/modules/quality-detection-workbench.js',import.meta.url),'utf8');
const start=source.indexOf('window.openDetectionBatch64=async function');
const end=source.indexOf('\n  function benchNotices64',start);
async function openBatch(batch,{id='original',uncertain=true}={}) {
 const previous={id:'original',running:false,outcomeUncertain:uncertain,results:[{itemIndex:0,status:'unknown',pendingSide:'B'}]};
 const button={disabled:true,textContent:''},messages=[];let rendered=0;
 const context={window:{setScenarioMode64(){},renderBenchBatch64(){rendered++;}},state:{benchBatch64:previous},pid:()=> 'project',batchOpenSequence:0,toast:value=>messages.push(value),api:async()=>({batch}),withRequestDeadline:fn=>fn(null),batchFromDurable64:value=>({...value,restored:true}),document:{querySelector:()=>({}),getElementById:()=>button}};
 vm.runInNewContext(source.slice(start,end),context);await context.window.openDetectionBatch64(id);
 return {context,previous,button,messages,rendered};
}
test('uncertain creation cannot be cleared by incomplete same batch or navigating unrelated history',async()=>{
 for(const [batch,id] of [[{batch_id:'original',items:[]},'original'],[{batch_id:'original',items:[{index:0,models:{A:{task_id:'known'}}}]},'original'],[{batch_id:'other',items:[]},'other']]) {
  const value=await openBatch(batch,{id});assert.equal(value.context.state.benchBatch64,value.previous);assert.equal(value.button.disabled,true);assert.equal(value.rendered,0);assert.ok(value.messages.length);
 }
});
test('matching durable uncertain side identity resolves original creation without another POST',async()=>{
 const value=await openBatch({batch_id:'original',items:[{index:0,models:{B:{task_id:'persisted',status:'QUEUED'}}}]});
 assert.equal(value.context.state.benchBatch64.restored,true);assert.equal(value.rendered,1);
});
test('ordinary historical navigation remains available outside uncertain creation',async()=>{
 const value=await openBatch({batch_id:'other',items:[]},{id:'other',uncertain:false});assert.equal(value.context.state.benchBatch64.restored,true);
});
