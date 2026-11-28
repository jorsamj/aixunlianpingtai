import test from 'node:test';
import assert from 'node:assert/strict';
import {mountImageUppyView} from '../../static/modules/uppy-image-view.js';
class Uppy {
  constructor(options){ this.options=options; this.files={}; this.state={capabilities:{}}; this.log=[]; }
  getState(){return this.state} setState(value){Object.assign(this.state,value)}
  use(){} addUploader(fn){this.upload=fn} getFile(id){return this.files[id]}
  emit(...args){this.log.push(args)} setOptions(){} destroy(){this.destroyed=true}
}
async function harness(uploadFiles){
 const target={isConnected:true,replaceChildren(){}};
 const view=await mountImageUppyView({target,runtime:{uploadFiles},projectId:'p',getProjectId:()=> 'p',loadUppy:async()=>({Uppy,Dashboard:class{}})});
 const files=Array.from({length:5},(_,i)=>({id:String(i),name:`${i}.png`,data:{name:`${i}.png`},progress:{}}));
 for(const file of files)view.uppy.files[file.id]=file;
 return {...view,files,target};
}
test('five files use one authoritative uploader; individual states wait for receipts and never receive batch percentages',async()=>{
 let calls=0;
 const h=await harness(async(files,opts)=>{
  calls++;assert.equal(files.length,5);assert.equal(opts.externalView,true);
  opts.onEvent({type:'transfer',ratio:1});
  assert.equal(h.uppy.log.filter(row=>row[0]==='upload-success').length,0);
  opts.onCommitted({files,response:{uploaded:files.slice(0,4).map(file=>({filename:file.name})),failed:[{name:'4.png',reason:'invalid'}]}});
 });
 await h.uppy.upload(h.files.map(file=>file.id));
 assert.equal(calls,1);assert.equal(h.uppy.log.filter(row=>row[0]==='upload-success').length,4);
 assert.equal(h.uppy.log.filter(row=>row[0]==='upload-error').length,1);
 assert.equal(h.uppy.log.filter(row=>row[0]==='upload-progress').length,0);
});
test('closing view never cancels owner transport and fences late view events',async()=>{
 let release, callbacks;
 const h=await harness((files,opts)=>{callbacks={files,opts};return new Promise(resolve=>{release=resolve})});
 const pending=h.uppy.upload(h.files.map(file=>file.id));h.destroy();assert.equal(h.uppy.destroyed,undefined);
 callbacks.opts.onCommitted({files:callbacks.files,response:{uploaded:callbacks.files.map(file=>({filename:file.name}))}});
 assert.equal(h.uppy.log.filter(row=>row[0]==='upload-success').length,0);
 release();await pending;assert.equal(h.uppy.destroyed,true);
});
test('local resource failure offers fallback',async()=>{
 let fallback=0;
 const view=await mountImageUppyView({target:{isConnected:true},projectId:'p',getProjectId:()=> 'p',loadUppy:async()=>{throw Error('offline')},onFallback(){fallback++}});
 assert.equal(view.uppy,null);assert.equal(fallback,1);
});

test('retry selection accepts only names in the confirmed failure list', async()=>{
 const view=await mountImageUppyView({target:{isConnected:true,replaceChildren(){}},runtime:{},projectId:'p',getProjectId:()=> 'p',retryNames:['bad.png'],loadUppy:async()=>({Uppy,Dashboard:class{}})});
 view.uppy.info=()=>{};
 assert.equal(view.uppy.options.onBeforeFileAdded({name:'good.png'}),false);
 const failed={name:'bad.png'};assert.equal(view.uppy.options.onBeforeFileAdded(failed),failed);
 view.destroy();
});
