import test from 'node:test';
import assert from 'node:assert/strict';
import {installTrainingMaterialPickerRuntime} from '../../static/modules/training-material-picker-runtime.js';
const tick=()=>new Promise(r=>setTimeout(r,0));
function setup(summaryOverride={}){
 const hosts=new Map();const host=id=>{if(!hosts.has(id))hosts.set(id,{id,isConnected:true,innerHTML:'',classList:{toggle(){}},querySelectorAll:()=>[],querySelector:()=>null});return hosts.get(id)};
 globalThis.document={getElementById:host,querySelectorAll:()=>[],querySelector:()=>null,head:{appendChild(){}}};
 let patch,context,disposed=0;const draft={materialIds:[],testMaterialIds:[],newLabelCodes:[]};
 globalThis.window={modal:()=>layer={querySelector:()=>null,querySelectorAll:()=>[]},closeModal(){runtime.beforeModalClose(layer)},PlatformCore:{pagination:{mountPagination(){}}}};
 let layer;const calls=[];
 const runtime=installTrainingMaterialPickerRuntime({getState:()=>({labels:[]}),projectId:()=> 'p',trainingDraftRuntime:{current:()=>draft,update:v=>{patch=v;Object.assign(draft,v)}},fetchImpl:async(url,opt)=>{calls.push([url,opt]);return {ok:true,json:async()=>url.includes('selection-summary')?{requested_count:1,matched_count:1,repository_revision:1,annotation_revision:2,selection_validation:{requested_count:1,eligible_count:1,excluded_count:0,unknown_count:0,repository_revision:1,annotation_revision:2,usage_revision:'u',negative_pool_revision:3,negative_confirmation_revision:4},...summaryOverride}:{items:[{id:'i',filename:'i.jpg',annotation_state:'annotated'}],page:1,page_size:60,total:1,total_pages:1,repository_revision:1,annotation_revision:2,usage_revision:'u',negative_pool_revision:3,negative_confirmation_revision:4}}}});
 runtime.setVuePresenter(async(_host,c)=>{context=c;return()=>disposed++});
 return {runtime,calls,draft,get context(){return context},get patch(){return patch},get disposed(){return disposed}};
}
test('presenter keeps selection in owner and confirms only after original summary',async()=>{
 const h=setup();await h.runtime.open('train');await tick();assert.ok(h.context);assert.equal(h.context.snapshot().items.length,1);
 h.context.actions.toggle('i',true);assert.equal(h.context.snapshot().selectedCount,1);assert.equal(h.patch,undefined);
 await h.context.actions.confirm();assert.deepEqual(h.patch.materialIds,['i']);assert.equal(h.calls.filter(([u])=>u.includes('selection-summary')).length,1);
 assert.ok(h.calls.every(([u])=>!u.includes('/submit')));
});
test('reference requires explicit clear and legacy presentation preserves unconfirmed selection',async()=>{
 const h=setup();h.draft.trainSelectionRef='ref';h.draft.trainSelectionCount=3000;await h.runtime.open('train');await tick();
 h.context.actions.toggle('i',true);assert.equal(h.context.snapshot().reference.selection_ref,'ref');
 h.context.actions.bulk('clear-all');h.context.actions.toggle('i',true);h.context.actions.legacy();
 assert.equal(h.runtime.state().selected,1);assert.equal(h.patch,undefined);assert.equal(h.disposed,1);
});
test('changed task identity blocks confirmation before a summary or Draft write',async()=>{
 const h=setup();await h.runtime.open('train');await tick();h.context.actions.toggle('i',true);h.draft.config={model:'different.pt'};
 await h.context.actions.confirm();assert.equal(h.patch,undefined);assert.match(h.context.snapshot().error,/身份/);
 assert.equal(h.calls.filter(([u])=>u.includes('selection-summary')).length,0);
});
test('on-demand summary returns bounded original facts without confirming Draft',async()=>{
 const h=setup();await h.runtime.open('train');await tick();h.context.actions.toggle('i',true);
 await h.context.actions.summary();assert.equal(h.patch,undefined);assert.equal(h.context.snapshot().summary.matched_count,1);
 h.context.actions.toggle('i',false);assert.equal(h.context.snapshot().summary,null);
});
test('late presenter mount is disposed once after closing its owner',async()=>{
 const h=setup();let finish,disposed=0;h.runtime.setVuePresenter(()=>new Promise(resolve=>{finish=()=>resolve(()=>disposed++)}));
 await h.runtime.open('train');await tick();h.runtime.close();finish();await tick();assert.equal(disposed,1);assert.equal(h.runtime.state(),null);
});
test('large explicit selection stays bounded in presentation and Test cannot make a manifest',async()=>{
 const h=setup();h.draft.testMaterialIds=Array.from({length:3000},(_,i)=>'t'+i);await h.runtime.open('test');await tick();
 const snap=h.context.snapshot();assert.equal(snap.selectedCount,3000);assert.equal(snap.selectedPreview.length,100);assert.equal(snap.items.length,1);
 assert.ok(!JSON.stringify(snap).includes('t2999'));await h.context.actions.confirm();assert.equal(h.patch,undefined);assert.match(h.context.snapshot().error,/2000/);
 assert.ok(h.calls.every(([u])=>!u.includes('selection-reference')));
});
test('a closed presenter cannot invoke reads or selection changes',async()=>{
 const h=setup();await h.runtime.open('train');await tick();const old=h.context;h.runtime.close();const count=h.calls.length;
 old.actions.reload();old.actions.toggle('i',true);assert.equal(h.calls.length,count);assert.equal(h.runtime.state(),null);assert.equal(h.disposed,1);
});

test('Test retains a previously frozen Train reference in original confirmation and Vue refuses unsafe overlap',async()=>{
 const h=setup();h.draft.trainSelectionRef='train-ref';h.draft.trainSelectionCount=5000;
 await h.runtime.open('test');await tick();assert.equal(h.context,undefined);assert.equal(h.draft.trainSelectionRef,'train-ref');
 h.runtime.setVuePresenter(null);await h.runtime.open('test');await tick();window.confirmTrainMaterialPickerV3();
 assert.equal(h.draft.trainSelectionRef,'train-ref');assert.equal(h.draft.trainSelectionCount,5000);
});
test('explicit history changes cannot rebind another changed task identity',async()=>{
 const h=setup();await h.runtime.open('train');await tick();h.draft.config={model:'changed.pt'};
 h.context.actions.historyPolicy('include_history');assert.equal(h.patch,undefined);assert.match(h.context.snapshot().error,/身份/);
});
test('cross-page explicit eligibility failure cannot confirm even when all IDs match',async()=>{
 const h=setup({selection_validation:{requested_count:1,eligible_count:0,excluded_count:1,unknown_count:0,repository_revision:1,annotation_revision:2,usage_revision:'u',negative_pool_revision:3,negative_confirmation_revision:4}});
 await h.runtime.open('train');await tick();h.context.actions.toggle('i',true);await h.context.actions.confirm();
 assert.equal(h.patch,undefined);assert.match(h.context.snapshot().error,/资格/);
 assert.equal(JSON.parse(h.calls.find(([u])=>u.includes('selection-summary'))[1].body).validate_selection,true);
});
test('Test unknown history and a mismatched usage revision both fail closed',async()=>{
 for(const [role,override] of [['test',{unknown_count:1}],['train',{usage_revision:'changed'}]]){
  const h=setup({selection_validation:{requested_count:1,eligible_count:1,excluded_count:0,unknown_count:0,repository_revision:1,annotation_revision:2,usage_revision:'u',negative_pool_revision:3,negative_confirmation_revision:4,...override}});
  await h.runtime.open(role);await tick();h.context.actions.toggle('i',true);await h.context.actions.confirm();assert.equal(h.patch,undefined);assert.ok(h.context.snapshot().error);
 }
});
test('an explicit history-policy change alone may rebind and confirm the same task',async()=>{
 const h=setup();await h.runtime.open('train');await tick();h.context.actions.historyPolicy('include_history');await tick();
 assert.equal(h.draft.history_policy,'include_history');h.context.actions.toggle('i',true);await h.context.actions.confirm();assert.deepEqual(h.patch.materialIds,['i']);
});


test('mixed Vue selection cannot launch an unbounded ID probe',async()=>{
 const h=setup();await h.runtime.open('train');await tick();h.context.actions.toggle('i',true);
 await h.context.actions.bulk('select-all');assert.equal(h.context.snapshot().selectedCount,1);assert.equal(h.patch,undefined);
 assert.equal(h.calls.filter(([url])=>url.includes('bulk-selection')||url.includes('selection-reference')).length,0);
 assert.match(h.context.snapshot().error,/逐张/);
});
