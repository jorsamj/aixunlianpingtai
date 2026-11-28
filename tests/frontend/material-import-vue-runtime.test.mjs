import test from 'node:test';
import assert from 'node:assert/strict';
import {installMaterialImportVueRuntime,materialImportTaskView,materialImportSafeText} from '../../static/modules/material-import-vue-runtime.js';
test('upload task facts keep zero, unknown and bounded secret-free projection',()=>{
 assert.equal(materialImportTaskView({progress:0}).progress,0);assert.equal(materialImportTaskView({progress:100,progressKnown:false}).progress,null);
 assert.doesNotMatch(materialImportSafeText('api_key="secret value" C:/private/key \\server\\share\\key'),/secret value|private|server/);
});
test('import view uses original upload entries and subscription, exits without cancelling tasks',async()=>{
 let context,subscribed=0,disposed=0,images=0,zips=0,cancelled=0;const state={project:{id:'p'},page:'素材上传与治理'};
 const window={UploadTaskCenterRuntime:{list:()=>Array.from({length:125},(_,i)=>({id:String(i),kind:'browser-upload'})),subscribe(){subscribed++;return()=>subscribed--},switchProject(){}},ZipImportRuntime:{subscribeTransfers:()=>()=>{},cancelAllActive:()=>cancelled++},ImageUppyView:{open:()=>images++},openUppyZipUpload:()=>zips++};
 const runtime=installMaterialImportVueRuntime({enabled:true,getState:()=>state,window,document:{},load:async(_host,value)=>{context=value;return()=>disposed++}});
 await runtime.render({isConnected:true});assert.equal(context.snapshot().tasks.length,100);assert.equal(context.snapshot().total,125);assert.equal(subscribed,1);
 await context.actions.images();await context.actions.zip();assert.equal(images,1);assert.equal(zips,1);
 state.project.id='q';assert.deepEqual(context.snapshot().tasks,[]);await context.actions.images();assert.equal(images,1);
 runtime.leave();assert.equal(context.signal.aborted,true);assert.equal(disposed,1);assert.equal(subscribed,0);assert.equal(cancelled,0);
});
test('late upload page chunk cannot remain mounted after navigation',async()=>{
 let finish,disposed=0;const state={project:{id:'p'},page:'素材上传与治理'};
 const runtime=installMaterialImportVueRuntime({enabled:true,getState:()=>state,window:{},document:{getElementById:()=>null},load:()=>new Promise(resolve=>finish=resolve)});
 const pending=runtime.render({isConnected:true});runtime.leave();finish(()=>disposed++);assert.equal(await pending,false);assert.equal(disposed,1);
});
