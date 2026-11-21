import test from 'node:test';
import assert from 'node:assert/strict';

const tick = () => new Promise(resolve => setImmediate(resolve));

test('a pending local asset load has a bounded fallback instead of an endless loading view',async()=>{
  const {mountUppyZipAdapter}=await import('../../static/modules/uppy-zip-adapter.js');
  let fallbacks=0;
  const result=await Promise.race([
    mountUppyZipAdapter({target:{isConnected:true},runtime:{getProjectId:()=> 'p'},projectId:'p',loadTimeoutMs:10,loadUppy:()=>new Promise(()=>{}),onFallback(){fallbacks++}}),
    new Promise(resolve=>setTimeout(()=>resolve('never recovered'),80)),
  ]);
  assert.notEqual(result,'never recovered');assert.equal(result.uppy,null);assert.equal(fallbacks,1);
});
class FakeUppy {
  constructor(options) { this.options=options; this.events=new Map(); this.files={}; this.state={capabilities:{}}; this.log=[]; }
  use(plugin,options) { this.dashboard=options; return this; }
  on(name,fn) { const list=this.events.get(name)||new Set(); list.add(fn); this.events.set(name,list); }
  off(name,fn) { this.events.get(name)?.delete(fn); }
  emit(name,...args) { this.log.push([name,...args]); for(const fn of this.events.get(name)||[]) fn(...args); }
  addUploader(fn) { this.uploader=fn; }
  removeUploader(fn) { if(this.uploader===fn) this.uploader=null; }
  getFile(id) { return this.files[id]; }
  getFiles() { return Object.values(this.files); }
  getState() { return this.state; }
  setState(value) { Object.assign(this.state,value); }
  setFileState(id,value) { Object.assign(this.files[id],value); }
  destroy() { this.emit('cancel-all'); this.destroyed=true; }
}
async function harness(options={}) {
  const {mountUppyZipAdapter}=await import('../../static/modules/uppy-zip-adapter.js');
  let listener, project='p'; const calls=[];
  const runtime={getProjectId:()=>project,subscribeTransfers(fn){listener=fn;return()=>{listener=null}},uploadBatch(input){calls.push(['batch',input]);return Promise.resolve(null)},resumeTransfer(file,id){calls.push(['resume',file,id]);return Promise.resolve(null)},pauseUpload(id){calls.push(['pause',id])},cancelJob(id){calls.push(['cancel',id])},cancelQueuedUpload(id){calls.push(['cancelQueued',id])}};
  const target=options.target||{isConnected:true};
  const mounted=await mountUppyZipAdapter({target,runtime,projectId:'p',loadUppy:async()=>({Uppy:FakeUppy,Dashboard:class{},zhCN:{strings:{}}}),...options});
  const add=(id,name='same.zip')=>{const data=new File([new Uint8Array(20)],name);mounted.uppy.files[id]={id,name,data,size:20,progress:{}};return data};
  return {...mounted,target,runtime,calls,add,emit:event=>listener?.({projectId:'p',...event}),switchProject(){project='other'},get subscribed(){return !!listener}};
}

test('custom uploader delegates one original batch and preserves File identity and byte progress across rekey',async()=>{
  const h=await harness(),a=h.add('a'),b=h.add('b');
  const pending=h.uppy.uploader(['a','b']);
  assert.equal(h.calls.length,1);assert.deepEqual(h.calls[0][1].files,[a,b]);assert.equal(h.calls[0][1].externalView,true);
  h.emit({type:'queued',file:a,transferId:'local-a'});h.emit({type:'session',file:a,uploadId:'upload-a'});
  h.emit({type:'progress',file:a,loaded:7,total:20});
  const progress=h.uppy.log.find(e=>e[0]==='upload-progress');assert.equal(progress[1].id,'a');assert.equal(progress[2].bytesUploaded,7);assert.equal(progress[2].bytesTotal,20);
  h.emit({type:'success',file:a,uploadId:'upload-a',jobId:'different-job',response:{status:'running'}});
  h.emit({type:'success',file:b,response:{status:'running'}});await pending;
  assert.equal(h.uppy.log.filter(e=>e[0]==='upload-success').length,2);h.destroy();
});

test('paused upload waits, official individual and global controls resume the exact original upload ID',async()=>{
  const h=await harness(),file=h.add('a');let finished=false;const pending=h.uppy.uploader(['a']).then(()=>{finished=true});
  h.emit({type:'session',file,uploadId:'persistent-id'});h.uppy.emit('upload-pause',h.uppy.getFile('a'),true);h.emit({type:'paused',file,uploadId:'persistent-id'});await tick();assert.equal(finished,false);
  h.uppy.emit('upload-pause',h.uppy.getFile('a'),false);await tick();assert.deepEqual(h.calls.at(-1),['resume',file,'persistent-id']);
  h.emit({type:'session',file,uploadId:'persistent-id'});h.uppy.emit('pause-all');h.emit({type:'paused',file});h.uppy.emit('resume-all');await tick();
  assert.equal(h.calls.filter(c=>c[0]==='pause').length,2);assert.equal(h.calls.filter(c=>c[0]==='resume').length,2);
  h.emit({type:'success',file,response:{status:'running'}});await pending;h.destroy();
});

test('per-file failure settles uploader and retry resumes original session without a new batch',async()=>{
  const h=await harness(),file=h.add('a');const first=h.uppy.uploader(['a']);h.emit({type:'session',file,uploadId:'id'});h.emit({type:'error',file,error:new Error('offline')});await first;
  assert.equal(h.uppy.log.filter(e=>e[0]==='upload-error').length,1);
  const retry=h.uppy.uploader(['a']);await tick();assert.equal(h.calls.filter(c=>c[0]==='batch').length,1);assert.deepEqual(h.calls.at(-1),['resume',file,'id']);h.emit({type:'success',file,response:{status:'running'}});await retry;h.destroy();
});

test('processing is not upload success and server handoff never claims background import completion',async()=>{
  const h=await harness(),file=h.add('a');const pending=h.uppy.uploader(['a']);h.emit({type:'processing',file,message:'merge'});assert.equal(h.uppy.log.filter(e=>e[0]==='upload-success').length,0);
  h.emit({type:'success',file,response:{id:'job',status:'awaiting_confirmation'}});await pending;assert.equal(h.uppy.log.find(e=>e[0]==='upload-success')[2].body.status,'awaiting_confirmation');
  assert.match(JSON.stringify(h.uppy.options.locale),/后台导入/);assert.equal(h.uppy.getState().capabilities.individualCancellation,false);assert.equal(h.uppy.dashboard.hideCancelButton,true);h.destroy();
});

test('destroy settles pending waiters, cleans listeners and never cancels original tasks',async()=>{
  const h=await harness();h.add('a');const pending=h.uppy.uploader(['a']);h.destroy();h.destroy();await pending;
  assert.equal(h.subscribed,false);assert.equal(h.uppy.uploader,null);assert.equal([...h.uppy.events.values()].reduce((n,s)=>n+s.size,0),0);assert.equal(h.calls.filter(c=>c[0].startsWith('cancel')).length,0);
});

test('selected file removal delegates only its original owner',async()=>{
  const h=await harness(),a=h.add('a'),b=h.add('b');const pending=h.uppy.uploader(['a','b']);h.emit({type:'session',file:a,uploadId:'one'});h.emit({type:'queued',file:b,transferId:'two'});
  h.uppy.emit('file-removed',h.uppy.getFile('a'));h.uppy.emit('file-removed',h.uppy.getFile('b'));assert.deepEqual(h.calls.slice(1),[['cancel','one'],['cancelQueued','two']]);h.destroy();await pending;
});

test('late foreign project events and detached targets do not affect UI or original owner',async()=>{
  const h=await harness(),file=h.add('a');const pending=h.uppy.uploader(['a']);const before=h.uppy.log.length;h.emit({type:'success',projectId:'other',file});assert.equal(h.uppy.log.length,before);
  h.switchProject();h.emit({type:'success',file});h.uppy.emit('upload-pause',h.uppy.getFile('a'),true);assert.equal(h.calls.length,1);assert.equal(h.uppy.log.filter(e=>e[0]==='upload-success').length,0);h.destroy();await pending;
  const detached=await harness();detached.target.isConnected=false;detached.add('a');await detached.uppy.uploader(['a']);assert.equal(detached.calls.length,0);detached.destroy();
});

test('failed vendor load invokes original UI fallback, with no subscription',async()=>{
  let fellBack=0;const h=await harness({loadUppy:async()=>{throw new Error('offline')},onFallback:()=>fellBack++});assert.equal(h.uppy,null);assert.equal(fellBack,1);assert.equal(h.subscribed,false);h.destroy();
});

test('pause before session identity is available is delegated as soon as original session arrives',async()=>{
  const h=await harness(),file=h.add('a');const pending=h.uppy.uploader(['a']);h.uppy.emit('upload-pause',h.uppy.getFile('a'),true);
  h.emit({type:'session',file,uploadId:'late-id'});assert.deepEqual(h.calls.at(-1),['pause','late-id']);h.destroy();await pending;
});

test('installed official Uppy Core consumes adapter events as real upload progress and handoff success',async()=>{
  const {default:Uppy,BasePlugin}=await import('@uppy/core');
  class Dashboard extends BasePlugin {constructor(uppy,opts){super(uppy,opts);this.id='Dashboard';this.type='acquirer'}}
  const h=await harness({loadUppy:async()=>({Uppy,Dashboard,zhCN:{strings:{}}})});
  const file=new File([new Uint8Array(20)],'real.zip');const id=h.uppy.addFile({name:file.name,type:'application/zip',data:file});
  const pending=h.uppy.upload();await tick();assert.equal(h.calls[0][1].files[0],file);
  h.emit({type:'session',file,uploadId:'official'});h.emit({type:'progress',file,loaded:8,total:20});await tick();assert.equal(h.uppy.getFile(id).progress.bytesUploaded,8);
  h.emit({type:'success',file,response:{id:'job',status:'running'}});const result=await pending;assert.equal(result.successful.length,1);assert.equal(h.uppy.getFile(id).progress.uploadComplete,true);assert.equal(h.uppy.getFile(id).response.body.status,'running');h.destroy();
});

test('host modal closure automatically destroys view and disconnects observer without cancelling transport',async()=>{
  const previous=globalThis.MutationObserver;let observer;
  globalThis.MutationObserver=class {constructor(callback){this.callback=callback;observer=this}observe(target,options){this.options=options}disconnect(){this.disconnected=true}};
  try {
    let hidden=false;const target={isConnected:true,ownerDocument:{body:{}},closest:()=>({classList:{contains:()=>hidden}})};
    const h=await harness({target});h.add('a');const pending=h.uppy.uploader(['a']);hidden=true;observer.callback([]);await pending;
    assert.equal(h.subscribed,false);assert.equal(h.uppy.destroyed,true);assert.equal(observer.disconnected,true);assert.equal(h.calls.length,1);assert.equal(observer.options.subtree,true);
  }finally{globalThis.MutationObserver=previous}
});

test('official Core rolls optimistic full-body progress back to original acknowledged bytes on retry',async()=>{
  const {default:Uppy,BasePlugin}=await import('@uppy/core');
  class Dashboard extends BasePlugin {constructor(uppy,opts){super(uppy,opts);this.id='Dashboard';this.type='acquirer'}}
  const h=await harness({loadUppy:async()=>({Uppy,Dashboard,zhCN:{strings:{}}})});
  try {
    const file=new File([new Uint8Array(20)],'rollback.zip');const id=h.uppy.addFile({name:file.name,type:'application/zip',data:file});
    const pending=h.uppy.upload();await tick();h.emit({type:'session',file,uploadId:'rollback'});
    h.emit({type:'progress',file,loaded:20,total:20});assert.equal(h.uppy.getFile(id).progress.percentage,100);assert.equal(h.uppy.getFile(id).progress.uploadComplete,false);
    h.emit({type:'progress',file,loaded:0,total:20});assert.equal(h.uppy.getFile(id).progress.bytesUploaded,0);assert.equal(h.uppy.getFile(id).progress.percentage,0);assert.equal(h.uppy.getFile(id).progress.uploadComplete,false);
    h.emit({type:'success',file,response:{status:'running'}});await pending;
  }finally{h.destroy()}
});

test('server processing refuses UI pause and late pause rejection cannot overwrite successful handoff',async()=>{
  const notices=[];const h=await harness({notify:message=>notices.push(message)}),file=h.add('a');const pending=h.uppy.uploader(['a']);
  h.emit({type:'session',file,uploadId:'merging'});h.emit({type:'processing',file});h.uppy.setFileState('a',{isPaused:true});h.uppy.emit('upload-pause',h.uppy.getFile('a'),true);
  assert.equal(h.calls.filter(c=>c[0]==='pause').length,0);assert.equal(h.uppy.getFile('a').isPaused,false);assert.match(notices[0],/服务端|后台/);
  h.emit({type:'success',file,response:{status:'running'}});await pending;h.emit({type:'error',file,error:new Error('late pause rejected')});assert.equal(h.uppy.log.filter(e=>e[0]==='upload-error').length,0);h.destroy();
});

test('late rejected pause promise after accepted handoff leaves official success intact',async()=>{
  const h=await harness(),file=h.add('a');let rejectPause;h.runtime.pauseUpload=()=>new Promise((resolve,reject)=>{rejectPause=reject});
  const pending=h.uppy.uploader(['a']);h.emit({type:'session',file,uploadId:'id'});h.uppy.emit('upload-pause',h.uppy.getFile('a'),true);h.emit({type:'success',file,response:{status:'running'}});await pending;rejectPause(new Error('late rejection'));await tick();assert.equal(h.uppy.log.filter(e=>e[0]==='upload-error').length,0);h.destroy();
});
