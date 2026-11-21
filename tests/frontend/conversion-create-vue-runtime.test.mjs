import test from 'node:test';import assert from 'node:assert/strict';
import {installConversionCreateVueRuntime} from '../../static/modules/conversion-create-vue-runtime.js';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
function fixture(){const restored=[];let context,resolveMount,disposed=0,loads=0;
 const node=name=>({name,dataset:{},hidden:false,before(marker){marker.parentNode=true;marker.replaceWith=value=>{restored.push(value.name);marker.parentNode=null}},addEventListener(){},remove(){}});
 const aside=node('aside'),footer=node('footer'),body={...node('body'),querySelector:()=>({closest:()=>footer})},root={...node('root'),isConnected:true,append(){},querySelector(selector){if(selector==='.conversion560-main')return body;if(selector==='input[name="conv428Target"]:checked')return {value:'onnx'};return null},querySelectorAll(){return [aside]}};
 const document={activeRoot:root,querySelector(){return this.activeRoot},createElement:()=>node('host'),createComment:()=>({})},state={project:{id:'p'},conv428SourceId:'version::a::v',conv428SourceReady:false,conv428ResourcesCurrent:false};
 globalThis.MutationObserver=class{observe(){}disconnect(){}};globalThis.window={ConversionWorkbenchUI:{refresh(){}}};globalThis.localStorage={getItem:()=>null};
 const runtime=installConversionCreateVueRuntime({enabled:true,getState:()=>state,projectId:()=>state.project.id,document,load:(_host,c)=>{context=c;loads++;return new Promise(resolve=>{resolveMount=()=>resolve(()=>disposed++)})}});
 return {runtime,state,document,root,aside,restored,get context(){return context},get disposed(){return disposed},get loads(){return loads},resolve:()=>resolveMount()};
}
test('conversion presenter keeps original slots and captured identity through project/root exit and late mount',async()=>{
 const h=fixture();assert.equal(h.runtime.render(h.root,{algorithmId:'wrong',versionId:'v'}),false);assert.equal(h.loads,0);assert.equal(h.runtime.render(h.root,{algorithmId:'a',versionId:'v'}),true);await tick();assert.equal(h.context.snapshot().sourceReady,false);assert.equal(h.aside.hidden,true);h.state.project.id='q';assert.equal(h.runtime.notify(),false);assert.equal(h.context.signal.aborted,true);assert.equal(h.aside.hidden,false);assert.deepEqual(h.restored,['body','footer']);h.resolve();await tick();assert.equal(h.disposed,1);
 const early=fixture();early.runtime.render(early.root);early.runtime.leave();await tick();assert.equal(early.loads,0);
 const changed=fixture();changed.runtime.render(changed.root);await tick();changed.document.activeRoot={};assert.equal(changed.runtime.render(changed.root),false);assert.equal(changed.runtime.notify(),false);changed.resolve();await tick();assert.equal(changed.disposed,1);
 const legacy=fixture();legacy.runtime.render(legacy.root);await tick();legacy.context.actions.legacy();assert.equal(legacy.runtime.render(legacy.root),false);legacy.resolve();await tick();assert.equal(legacy.disposed,1);
});
