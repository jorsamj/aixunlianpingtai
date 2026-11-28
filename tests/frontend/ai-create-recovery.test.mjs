import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
function harness(storage=new Map()){
 let project='p',posts=0,gets=0,closed=0,shown=0,mode='lost',deferred,storageFail=false,writeFail=false,dropWrite=false;
 const panel={hidden:true,innerHTML:'',querySelector:()=>({addEventListener(){}})},root={isConnected:true,querySelector:()=>null,append(){},dataset:{aiCreateEpoch:'1'}};
 const fields={ai429Labels:{value:'smoke'},ai429Model:{value:'model'},ai429Threshold:{value:'.45'},ai429Submit:{disabled:false,isConnected:true,textContent:''},ai429Recovery:panel};
 const state={labels:[{code:'smoke'}],ai429Create:{epoch:1,images:new Set(['i']),excluded:new Set(),sourceBatchId:'batch',taskName:'test',confirmationSnapshot:''}};
 const owner={layer:{},isCurrent:()=>state.ai429Create?.epoch===1&&project==='p'};
 const api=async(url,options={})=>{if(options.method==='POST'){posts++;if(mode==='missing')return {};if(mode==='success')return {id:'task',project_id:'p'};if(mode.startsWith('reject-'))throw Object.assign(new Error('configuration rejected'),{httpStatus:Number(mode.slice(7))});throw new Error('network lost')};gets++;if(deferred)return deferred; if(mode==='found')return {id:'task',project_id:'p'};throw Object.assign(new Error('not found'),{httpStatus:404})};
 const window={crypto:{getRandomValues:b=>b.fill(1)},ModalContentRuntime:{captureOwner:()=>owner,activeLayer:()=>closed?null:owner.layer},closeModalLayer424:async()=>{closed++},localStorage:{getItem:k=>{if(storageFail)throw new Error('private');return storage.get(k)??null},setItem:(k,v)=>{if(storageFail||writeFail)throw new Error('quota');if(!dropWrite)storage.set(k,v)},removeItem:k=>storage.delete(k)}};
 const context={window,state,document:{getElementById:id=>fields[id]||null,querySelector:()=>root,createElement:()=>panel},pid:()=>project,taskApi:(id,p=project)=>`/api/v60/projects/${p}/annotation-tasks${id?'/'+id:''}`,api,toast(){},esc:v=>String(v),renderAiCreateConfirmation429(){},showAiTask60:()=>{shown++},closeModal:async()=>{closed++},Uint8Array,Map,Set,JSON,Number,String,Math,Date,encodeURIComponent,AbortController};
 vm.createContext(context);
 vm.runInContext(source.slice(source.indexOf('  function explicitCanonicalAiLabelText('),source.indexOf('  function renderAiCreateConfirmation429(')),context);
 const start=source.indexOf('  function newAiCreateRequestId429()'),end=source.indexOf('  function taskRow',start);
 vm.runInContext(source.slice(start,end).replace('try{renderAiCreateConfirmation429(body)}','try{/* fixture: confirmation rendering tested separately */}'),context);
 return {window,state,storage,fields,setMode:v=>mode=v,failStorage:()=>storageFail=true,failWrite:()=>writeFail=true,dropWrite:()=>dropWrite=true,setProject:v=>project=v,setDeferred:v=>deferred=v,get posts(){return posts},get gets(){return gets},get closed(){return closed},get shown(){return shown},submit:()=>window.submitAiLabel429()};
}
test('unknown create survives owner reload, contains only identity, and blocks changed intent POST',async()=>{
 const h=harness();await h.submit();await h.submit();assert.equal(h.posts,1);assert.equal(h.storage.size,1);
 const raw=JSON.parse([...h.storage.values()][0]);assert.deepEqual(Object.keys(raw).sort(),['project_id','request_id']);assert.equal(raw.project_id,'p');assert.ok(raw.request_id);
 const next=harness(h.storage);next.state.ai429Create.taskName='changed';await next.submit();assert.equal(next.posts,0);assert.equal(next.gets,1);assert.equal(next.window.pendingAiCreate429().state,'UNKNOWN');assert.equal(next.window.pendingAiCreate429('other'),null);
 await next.window.queryAiCreateReceipt429();assert.equal(next.gets,2);assert.equal(next.storage.size,1);
 next.setMode('found');await next.window.queryAiCreateReceipt429();assert.equal(next.storage.size,0);assert.equal(next.closed,1);assert.equal(next.shown,1);
});
test('storage failure refuses first create POST and returns safe pending state',async()=>{
 const h=harness();await h.submit();h.failStorage();await h.submit();assert.equal(h.posts,0);assert.equal(h.window.pendingAiCreate429().state,'UNKNOWN');assert.ok(h.window.pendingAiCreate429().error);
});
test('successful HTTP without id remains unknown and never causes a second POST',async()=>{
 const h=harness();h.setMode('missing');await h.submit();await h.submit();assert.equal(h.posts,1);assert.equal(h.storage.size,1);await h.submit();assert.equal(h.posts,1);assert.equal(h.closed,0);
});
test('late recovered receipt may clear exact journal but never closes a replacement project/modal',async()=>{
 const h=harness();await h.submit();await h.submit();let resolve;h.setDeferred(new Promise(r=>resolve=r));const pending=h.window.queryAiCreateReceipt429();h.setProject('q');h.state.ai429Create={epoch:2};resolve({id:'task',project_id:'p'});await pending;assert.equal(h.storage.size,0);assert.equal(h.closed,0);assert.equal(h.shown,0);
});


test('prewrite quota and silent readback failure both refuse POST',async()=>{
 for(const fault of ['failWrite','dropWrite']){const h=harness();await h.submit();h[fault]();await h.submit();assert.equal(h.posts,0)}
});
test('authoritative create receipt clears identity and presents original task',async()=>{
 const h=harness();h.setMode('success');await h.submit();await h.submit();assert.equal(h.posts,1);assert.equal(h.storage.size,0);assert.equal(h.closed,1);assert.equal(h.shown,1);
});
test('receipt for another project never clears the pending journal',async()=>{
 const h=harness();await h.submit();await h.submit();h.setDeferred(Promise.resolve({id:'wrong',project_id:'other'}));await h.window.queryAiCreateReceipt429();assert.equal(h.storage.size,1);assert.equal(h.closed,0);
});
test('old project draft cannot submit even if its original DOM survives',async()=>{
 const h=harness();h.setMode('success');await h.submit();
 // Changing the draft project before sending must be refused, even if its old DOM survives.
 h.state.ai429Create.projectId='old';await h.submit();assert.equal(h.posts,0);
});

test('receipt lookup deduplicates its read and exposes modal-owned abort controller',async()=>{
 const h=harness();await h.submit();await h.submit();let resolve;h.setDeferred(new Promise(r=>resolve=r));const first=h.window.queryAiCreateReceipt429();const controller=h.state.ai429Create.createReceiptController;assert.ok(controller);assert.equal(h.state.ai429Create.receiptLoading,true);await h.window.queryAiCreateReceipt429();assert.equal(h.gets,1);controller.abort();resolve({});await first;assert.equal(h.storage.size,1);assert.equal(h.state.ai429Create.receiptLoading,false);assert.equal(h.state.ai429Create.createReceiptController,null);
});

test('authoritative pre-persistence validation rejects allow correction but conflicts stay UNKNOWN',async()=>{
 for(const code of [400,422]){const h=harness();h.setMode('reject-'+code);await h.submit();await h.submit();assert.equal(h.posts,1);assert.equal(h.storage.size,0);assert.equal(h.state.ai429Create.confirmationSnapshot,'');assert.match(h.state.ai429Create.createError,/configuration rejected/);await h.submit();assert.equal(h.posts,1);}
 const conflict=harness();conflict.setMode('reject-409');await conflict.submit();await conflict.submit();assert.equal(conflict.posts,1);assert.equal(conflict.storage.size,1);await conflict.submit();assert.equal(conflict.posts,1);
});
