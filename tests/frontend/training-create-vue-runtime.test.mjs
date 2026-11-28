import test from 'node:test';import assert from 'node:assert/strict';
import {installTrainingCreateVueRuntime} from '../../static/modules/training-create-vue-runtime.js';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
function fixture(){
 const restored=[],listeners=new Set();let context,resolveMount,disposed=0,submits=0,loads=0;
 // Narrow slot ownership fixture: only operations used by this presentation adapter.
 const node=name=>({name,hidden:false,dataset:{},before(marker){marker.parentNode=true;marker.replaceWith=value=>{restored.push(value.name);marker.parentNode=null}},addEventListener(){},remove(){this.removed=true}});
 const steps=[node('step1'),node('step2'),node('step3')],footer={...node('footer'),prepend(value){this.feedback=value}},feedback={...node('feedback'),hidden:false,textContent:'正在创建',dataset:{tone:'working'}},left=node('left'),layout={children:[left],append(){}},root={...node('root'),isConnected:true,dataset:{trainingStep:'1'},querySelector(selector){return selector==='.train-create-layout'?layout:selector==='.train428-footer'?footer:selector==='[data-training-submit-feedback]'?feedback:null},querySelectorAll(selector){return selector==='[data-training-step-panel]'?steps:[]}};
 const document={querySelector:()=>document.activeRoot,activeRoot:root,createElement:()=>node('host'),createComment:()=>({})};
 const state={project:{id:'p'},trainingDraft:{algorithmId:'a',config:{time:0,precision:'fp32',model:'/private/models/base.pt',internal_file:'/private/secret.json'},trainSelectionRef:'frozen',trainSelectionCount:20000}};
 globalThis.MutationObserver=class{observe(){}disconnect(){}};
 globalThis.window={TrainingDraftRuntime:{subscribe(fn){listeners.add(fn);return()=>listeners.delete(fn)}},TrainingSubmitRuntime:{isSubmitting:()=>false,submit(){submits++}},refreshTrainingCreateUi(){},TrainingLabelRuntime:{queueRefresh(){}}};
 const runtime=installTrainingCreateVueRuntime({enabled:true,getState:()=>state,projectId:()=>state.project.id,document,load:(_host,c)=>{context=c;loads++;return new Promise(resolve=>{resolveMount=()=>resolve(()=>disposed++)})}});
 return {runtime,state,document,root,left,feedback,footer,restored,listeners,get context(){return context},get disposed(){return disposed},get submits(){return submits},get loads(){return loads},resolve:()=>resolveMount()};
}
test('training presentation restores original owner on project/root exit and disposes only its late mount',async()=>{
 const h=fixture();assert.equal(h.runtime.render(h.root),true);await tick();assert.equal(h.footer.feedback,h.feedback);assert.equal(h.context.snapshot().error,'');assert.equal(h.context.snapshot().frozenCount,20000);assert.equal(h.context.snapshot().model,'base.pt');assert.equal(h.context.snapshot().parameters.some(row=>/model|internal_file/.test(row.name)),false);assert.equal(h.context.snapshot().parameters.find(row=>row.name==='time').value,0);
 h.state.project.id='other';h.context.actions.submit();assert.equal(h.submits,0);assert.equal(h.runtime.notify(),false);assert.equal(h.context.signal.aborted,true);assert.equal(h.listeners.size,0);assert.equal(h.left.hidden,false);assert.deepEqual(h.restored,['step1','step2','step3','footer','feedback']);h.resolve();await tick();assert.equal(h.disposed,1);
 const second=fixture();second.runtime.render(second.root);await tick();second.document.activeRoot={};second.context.actions.submit();assert.equal(second.submits,0);second.runtime.notify();second.resolve();await tick();assert.equal(second.disposed,1);assert.equal(second.context.signal.aborted,true);
 const early=fixture();early.runtime.render(early.root);early.runtime.leave();await tick();assert.equal(early.loads,0);assert.equal(early.left.hidden,false);
});
