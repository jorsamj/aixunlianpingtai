import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {annotationSavePayload} from '../../static/modules/annotation-workbench.js';

function harness(request){
 const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const start=source.indexOf('  window.saveAnnotationCore420=');
 const prefix=source.lastIndexOf('\n  let annotationSaveFlight420',start);
 const end=source.indexOf('\n  // ---------- dataset: labels',start);
 const timers=new Map(),messages=[],calls=[];let id=0,project='p1',saved=0,remembered=0,opened=0;
 const button={disabled:false,textContent:'保存并继续',innerHTML:'保存并继续',classList:{toggle(){}},setAttribute(k,v){this[k]=v}},status={textContent:''};
 const state={activeImage:{id:'i1'},ann:{version:1,boxes:[{label:'car',x1:1}]},images:[{id:'i1'}],annDirty:true,annotationWorkbench:{markSaved(){saved++},remember(){remembered++},open(){opened++}}};
 const window={PlatformCore:{},NegativeSampleRuntime:{decorate(){}}};
 const context={window,state,document:{getElementById:key=>key==='ann414Save'?button:key==='annSaveState'?status:null,querySelector:()=>null,querySelectorAll:()=>[]},pid:()=>project,api:(url,opts)=>{calls.push({url,opts});return request(url,opts)},toast:m=>messages.push(m),drawBoxes(){},renderAnnSide(){},queueIds:()=>['i1','i2'],setTimeout:(fn,ms)=>{const key=++id;timers.set(key,{fn,ms});return key},clearTimeout:key=>timers.delete(key),AbortController,Promise,Error,Set,WeakMap,WeakSet,JSON,Number,String};
 const apiSource=readFileSync(new URL('../../static/modules/api.js',import.meta.url),'utf8');
 vm.runInNewContext(apiSource.slice(0,apiSource.indexOf('export function messageFromApiError')).replace('export async function','async function')+'\nwindow.PlatformCore.withRequestDeadline=withRequestDeadline;',context);
 vm.runInNewContext(source.slice(prefix>=0?prefix:start,end),context);
 const canonicalStart=source.indexOf('  window.saveAnn=async function saveAnnotationCanonical420');
 vm.runInNewContext(source.slice(canonicalStart,source.indexOf('\n  window.resetAnnotationZoom420',canonicalStart)),context);
 return {state,button,status,timers,messages,calls,window,get saved(){return saved},get remembered(){return remembered},get opened(){return opened},setProject:p=>project=p,expire(){for(const [key,t]of [...timers])if(t.ms===30000){timers.delete(key);t.fn()}}};
}
const response=()=>({annotation:{version:2,annotation_state:'annotated',boxes:[{label:'car',x1:1}]},image:{id:'i1'}});

test('silent save shares busy state and rejects duplicate writes and navigation',async()=>{
 let resolve;const h=harness(()=>new Promise(r=>resolve=r));const first=h.window.saveAnn(true),duplicate=h.window.saveAnn(false);
 await Promise.resolve();assert.equal(h.calls.length,1);assert.equal(h.button.disabled,true);assert.match(h.button.innerHTML,/tiny-spinner/);assert.equal(await duplicate,false);
 resolve(response());assert.equal(await first,true);assert.equal(h.saved,1);assert.equal(h.opened,0);assert.equal(h.button.disabled,false);assert.equal(h.timers.size,0);
});
test('permanently pending write times out dirty and requires a fresh read before CAS retry',async()=>{
 const h=harness(()=>new Promise(()=>{}));const pending=h.window.saveAnn(true);
 await Promise.resolve();assert.ok([...h.timers.values()].some(t=>t.ms===30000));h.expire();assert.equal(await pending,false);
 assert.equal(h.state.annDirty,true);assert.equal(h.button.disabled,false);assert.match(h.status.textContent,/超时/);assert.match(h.messages.join(' '),/重新读取/);
 assert.equal(h.calls[0].opts.signal.aborted,true);
});
test('late response after switching image cannot overwrite the new annotation or mark it saved',async()=>{
 let resolve;const h=harness(()=>new Promise(r=>resolve=r));const pending=h.window.saveAnn(false);
 await Promise.resolve();const next={version:7,boxes:[{label:'person'}]};h.state.activeImage={id:'i2'};h.state.ann=next;resolve(response());
 assert.equal(await pending,false);assert.equal(h.state.ann,next);assert.equal(h.state.activeImage.id,'i2');assert.equal(h.saved,0);assert.equal(h.remembered,0);assert.equal(h.opened,0);
});
test('editing while saving retains edits and dirty but advances the acknowledged CAS version',async()=>{
 let resolve;const h=harness(()=>new Promise(r=>resolve=r));const ann=h.state.ann,pending=h.window.saveAnn(false);await Promise.resolve();ann.boxes[0].x1=9;resolve(response());
 assert.equal(await pending,false);assert.equal(h.state.ann,ann);assert.equal(ann.boxes[0].x1,9);assert.equal(ann.version,2);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);assert.equal(h.opened,0);
});
test('late timeout response stays ignored and fresh authoritative annotation permits versioned retry',async()=>{
 let resolve;let count=0;const h=harness(()=>++count===1?new Promise(r=>resolve=r):Promise.resolve(response()));const pending=h.window.saveAnn(true);await Promise.resolve();h.expire();await pending;
 resolve(response());await Promise.resolve();assert.equal(h.state.ann.version,1);assert.equal(h.saved,0);
 h.state.ann={version:3,boxes:[{label:'car'}]};assert.equal(await h.window.saveAnn(true),true);assert.equal(JSON.parse(h.calls[1].opts.body).expected_version,3);
});
test('switching projects fences successful and failing responses from the current editor',async()=>{
 for(const fails of [false,true]){
  let resolve,reject;const h=harness(()=>new Promise((a,b)=>{resolve=a;reject=b}));const pending=h.window.saveAnn(false);await Promise.resolve();h.setProject('p2');h.state.annDirty=false;h.status.textContent='new project';
  if(fails)reject(new Error('old error'));else resolve(response());
  assert.equal(await pending,false);assert.equal(h.state.ann.version,1);assert.equal(h.state.annDirty,false);assert.equal(h.status.textContent,'new project');assert.equal(h.messages.length,0);assert.equal(h.saved,0);
 }
});
test('review changes during save remain unchecked for persistence until explicitly saved again',async()=>{
 let resolve;const h=harness(()=>new Promise(r=>resolve=r));h.state.annotationReviewSelected420=new Set(['car']);const pending=h.window.saveAnn(false,{confirmReview:true,reviewedLabelCodes:['car']});await Promise.resolve();h.state.annotationReviewSelected420.add('person');resolve(response());
 assert.equal(await pending,false);assert.equal(h.state.annotationReviewSelected420.has('person'),true);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);
});
test('CAS conflict retains local edits and releases busy state without retrying the mutation',async()=>{
 const h=harness(async()=>{throw Object.assign(new Error('版本冲突，请重新读取'),{status:409})});const ann=h.state.ann;
 assert.equal(await h.window.saveAnn(true),false);assert.equal(h.state.ann,ann);assert.equal(h.state.annDirty,true);assert.equal(h.button.disabled,false);assert.equal(h.calls.length,1);assert.equal(h.timers.size,0);assert.match(h.messages.join(' '),/版本冲突/);
});
for(const outcome of ['unchanged','committed','conflict'])test(`timeout recovery reads authoritative ${outcome} version without another POST`,async()=>{
 let count=0;const h=harness(()=>++count===1?new Promise(()=>{}):Promise.resolve({image:{id:'i1'},annotation:outcome==='unchanged'?{version:1,boxes:[]} : outcome==='committed'?response().annotation:{version:3,boxes:[{label:'other'}]}}));
 const first=h.window.saveAnn(true);await Promise.resolve();h.expire();await first;
 assert.equal(await h.window.saveAnn(true),outcome==='committed');assert.equal(h.calls.length,2);assert.equal(h.calls[1].opts.method,'GET');assert.equal(h.state.annDirty,outcome!=='committed');
 if(outcome==='conflict'){assert.equal(h.state.ann.version,1);assert.match(h.messages.join(' '),/冲突/)}
 if(outcome==='unchanged'){assert.match(h.messages.join(' '),/再次保存/);await h.window.saveAnn(true);assert.equal(h.calls[2].opts.method,'POST');assert.equal(JSON.parse(h.calls[2].opts.body).expected_version,1)}
});
test('recovering committed timeout keeps later local edits and the acknowledged version',async()=>{
 let count=0;const h=harness(()=>++count===1?new Promise(()=>{}):Promise.resolve(response()));const first=h.window.saveAnn(true);await Promise.resolve();h.expire();await first;
 h.state.ann.boxes[0].x1=8;assert.equal(await h.window.saveAnn(true),false);assert.equal(h.state.ann.boxes[0].x1,8);assert.equal(h.state.ann.version,2);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);assert.equal(h.calls.length,2);
});
test('timeout verification rejects another source SHA and never advances its version',async()=>{
 let count=0;const h=harness(()=>++count===1?new Promise(()=>{}):Promise.resolve({...response(),image:{id:'i1',content_sha256:'changed'}}));const first=h.window.saveAnn(true);await Promise.resolve();h.expire();await first;
 assert.equal(await h.window.saveAnn(true),false);assert.equal(h.state.ann.version,1);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);assert.match(h.messages.join(' '),/身份/);
});
test('timeout verification accepts persisted key ordering and server manual provenance for a new box',async()=>{
 let count=0;const h=harness(()=>++count===1?new Promise(()=>{}):Promise.resolve({image:{id:'i1'},annotation:{version:2,annotation_state:'annotated',boxes:[{x1:1,label:'car',source:'manual'}]}}));const first=h.window.saveAnn(true);await Promise.resolve();h.expire();await first;
 assert.equal(await h.window.saveAnn(true),true);assert.equal(h.state.annDirty,false);assert.equal(h.calls.length,2);
});
for(const error of [new TypeError('Failed to fetch'),Object.assign(new Error('server failure'),{httpStatus:502}),new SyntaxError('Invalid JSON')])test(`uncertain POST ${error.name}/${error.httpStatus||'network or decode'} is verified with GET before another mutation`,async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)throw error;return response()});assert.equal(await h.window.saveAnn(true),false);assert.equal(await h.window.saveAnn(true),true);assert.deepEqual(h.calls.map(call=>call.opts.method),['POST','GET']);
});
test('explicit 4xx failure permits a corrected POST without entering unknown recovery',async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)throw Object.assign(new Error('invalid input'),{httpStatus:422});return response()});assert.equal(await h.window.saveAnn(true),false);assert.equal(await h.window.saveAnn(true),true);assert.deepEqual(h.calls.map(call=>call.opts.method),['POST','POST']);
});
test('failed recovery GET preserves original uncertain submission for the next verification',async()=>{
 let count=0;const h=harness(async()=>{count++;if(count<3)throw new TypeError('lost response');return response()});await h.window.saveAnn(true);assert.equal(await h.window.saveAnn(true),false);assert.equal(await h.window.saveAnn(true),true);assert.deepEqual(h.calls.map(call=>call.opts.method),['POST','GET','GET']);
});
test('confirmed empty recovery rejects newer unannotated state even with matching boxes and scope',async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)return new Promise(()=>{});return {image:{id:'i1'},annotation:{version:2,annotation_state:'unannotated',annotation_scope:['car'],boxes:[]}}});h.state.ann={version:1,boxes:[],annotation_scope:['car']};
 const first=h.window.saveAnn(true,{confirmEmpty:true,confirmReview:true,reviewedLabelCodes:['car']});await Promise.resolve();h.expire();assert.equal(await first,false);assert.equal(await h.window.saveAnn(true),false);assert.equal(h.state.ann.version,1);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);assert.match(h.messages.join(' '),/冲突/);assert.deepEqual(h.calls.map(call=>call.opts.method),['POST','GET']);
});

for(const withModule of [false,true])test(`dirty last-box removal saves pending with no negative proof (module=${withModule})`,async()=>{
 const h=harness(async(_url,opts)=>({image:{id:'i1'},annotation:{version:2,...JSON.parse(opts.body),annotation_scope:[]}}));
 if(withModule)h.window.PlatformCore.annotationWorkbench={annotationSavePayload};
 h.state.ann={version:1,annotation_state:'annotated',annotation_scope:['car'],boxes:[]};h.state.annotationReviewSelected420=new Set(['person']);
 assert.equal(await h.window.saveAnn(true),true);const payload=JSON.parse(h.calls[0].opts.body);
 assert.equal(payload.annotation_state,'unannotated');assert.deepEqual(payload.reviewed_label_codes,[]);assert.deepEqual(payload.boxes,[]);assert.equal(payload.expected_version,1);
 assert.equal(h.state.annDirty,false);assert.match(h.status.textContent,/待标注/);assert.equal(h.saved,1);
});

test('untouched confirmed negative ordinary save is a no-op that preserves review proof',async()=>{
 const h=harness(async()=>{throw new Error('must not write')});h.state.ann={version:7,annotation_state:'confirmed_empty',annotation_scope:['car'],boxes:[]};h.state.annDirty=false;
 assert.equal(await h.window.saveAnn(true),true);assert.equal(h.calls.length,0);assert.equal(h.state.ann.version,7);assert.equal(h.state.ann.annotation_state,'confirmed_empty');assert.deepEqual(h.state.ann.annotation_scope,['car']);assert.equal(h.state.annDirty,false);
});

test('explicit empty confirmation without current review labels does not POST',async()=>{
 const h=harness(async()=>response());h.state.ann={version:1,boxes:[],annotation_scope:['car']};
 assert.equal(await h.window.saveAnn(false,{confirmEmpty:true}),false);assert.equal(h.calls.length,0);assert.equal(h.state.annDirty,true);assert.match(h.messages.join(' '),/审核|标签/);
});

for(const withModule of [false,true])test(`confirmed negative timeout verifies only current reviewed scope (module=${withModule})`,async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)return new Promise(()=>{});return {image:{id:'i1'},annotation:{version:2,annotation_state:'confirmed_empty',annotation_scope:['person'],boxes:[]}}});
 if(withModule)h.window.PlatformCore.annotationWorkbench={annotationSavePayload};
 h.state.ann={version:1,annotation_state:'annotated',annotation_scope:['car'],boxes:[]};
 const first=h.window.saveAnn(true,{confirmEmpty:true,confirmReview:true,reviewedLabelCodes:['person']});await Promise.resolve();h.expire();assert.equal(await first,false);
 const payload=JSON.parse(h.calls[0].opts.body);assert.equal(payload.annotation_state,'confirmed_empty');assert.deepEqual(payload.reviewed_label_codes,['person']);
 assert.equal(await h.window.saveAnn(true),true);assert.deepEqual(h.calls.map(c=>c.opts.method),['POST','GET']);assert.deepEqual(h.state.ann.annotation_scope,['person']);
});

for(const remoteState of ['unannotated','confirmed_empty'])test(`pending timeout validates state and empty scope (${remoteState})`,async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)return new Promise(()=>{});return {image:{id:'i1'},annotation:{version:2,annotation_state:remoteState,annotation_scope:[],boxes:[]}}});
 h.state.ann={version:1,annotation_state:'annotated',annotation_scope:['car'],boxes:[]};
 const first=h.window.saveAnn(true);await Promise.resolve();h.expire();assert.equal(await first,false);
 assert.equal(await h.window.saveAnn(true),remoteState==='unannotated');assert.deepEqual(h.calls.map(c=>c.opts.method),['POST','GET']);assert.equal(h.state.annDirty,remoteState!=='unannotated');
});

test('pending timeout cannot recover stale negative scope as cleared GT',async()=>{
 let count=0;const h=harness(async()=>{if(++count===1)return new Promise(()=>{});return {image:{id:'i1'},annotation:{version:2,annotation_state:'unannotated',annotation_scope:['car'],boxes:[]}}});
 h.state.ann={version:1,annotation_state:'annotated',annotation_scope:['car'],boxes:[]};
 const first=h.window.saveAnn(true);await Promise.resolve();h.expire();await first;
 assert.equal(await h.window.saveAnn(true),false);assert.equal(h.state.annDirty,true);assert.equal(h.state.ann.version,1);assert.match(h.messages.join(' '),/冲突/);
});

test('new box drawn during pending save stays dirty with acknowledged CAS version',async()=>{
 let resolve;const h=harness(()=>new Promise(r=>resolve=r));h.state.ann={version:1,annotation_state:'annotated',annotation_scope:['car'],boxes:[]};
 const local=h.state.ann,first=h.window.saveAnn(true);await Promise.resolve();local.boxes.push({id:'new',label:'car',x1:4});
 resolve({image:{id:'i1'},annotation:{version:2,annotation_state:'unannotated',annotation_scope:[],boxes:[]}});
 assert.equal(await first,false);assert.equal(h.state.ann,local);assert.equal(local.boxes[0].id,'new');assert.equal(local.version,2);assert.equal(h.state.annDirty,true);assert.equal(h.saved,0);assert.equal(h.opened,0);
});
