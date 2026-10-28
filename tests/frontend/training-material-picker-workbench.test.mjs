import test from 'node:test';
import assert from 'node:assert/strict';
import {installTrainingMaterialPickerRuntime} from '../../static/modules/training-material-picker-runtime.js';

const tick=()=>new Promise(r=>setTimeout(r,0));
function setup(draft,fetchImpl){
  const hosts=new Map();
  const host=id=>{if(!hosts.has(id))hosts.set(id,{id,textContent:'',innerHTML:'',dataset:{},classList:{toggle(){}},addEventListener(){}});return hosts.get(id);};
  globalThis.document={getElementById:host,querySelectorAll:()=>[],head:{appendChild(){}}};
  globalThis.window={modal(){},closeModal(){},PlatformCore:{pagination:{mountPagination(){}}}};
  let patch;
  const runtime=installTrainingMaterialPickerRuntime({getState:()=>({labels:[]}),projectId:()=> 'p',trainingDraftRuntime:{current:()=>draft,update:v=>patch=v},fetchImpl});
  return {runtime,get patch(){return patch;}};
}
const response=body=>({ok:true,json:async()=>body});
const page=n=>({items:[{id:`i${n}`,annotation_state:'annotated'}],total:120,page:n,total_pages:2,repository_revision:1,annotation_revision:2,usage_revision:'u'});

test('reopen restores draft; cache-hit cancels pending page and ignores a late response',async()=>{
  let complete;
  const h=setup({materialIds:['saved'],newLabelCodes:[]},async(url,options={})=>{
    if(url.includes('/revision'))return response({repository_revision:1,annotation_revision:2,usage_revision:'u'});
    if(new URL(url,'http://test').searchParams.get('page')==='2')return new Promise(resolve=>{complete=()=>resolve(response(page(2)));});
    return response(page(1));
  });
  try{
    await h.runtime.open('train');await tick();
    assert.equal(h.runtime.state().selected,1);
    const pending=h.runtime.loadPage({page:2});await tick();
    await h.runtime.loadPage({page:1});
    complete();await pending;
    assert.equal(h.runtime.state().page,1);
    await h.runtime.open('train');await tick();
    assert.equal(h.runtime.state().selected,1);
  }finally{delete globalThis.window;delete globalThis.document;}
});

test('robustness picker scopes candidates and patches only its policy selection',async()=>{
  const calls=[];
  const policy={mode:'enabled',copies:2,selection:{mode:'manual',image_ids:['i1','outside']}};
  const h=setup({materialIds:['i1','i2'],testMaterialIds:['t'],newLabelCodes:[],robustness_policy:policy},async(url,options={})=>{
    calls.push({url,body:options.body?JSON.parse(options.body):null});return response(page(1));
  });
  try{
    await h.runtime.open({role:'robustness'});await tick();
    assert.equal(h.runtime.state().selected,1);
    assert.deepEqual(calls[0].body.image_ids,['i1','i2']);
    assert.match(calls[0].url,/\/page$/);
    window.confirmTrainMaterialPickerV3();
    assert.deepEqual(Object.keys(h.patch),['robustness_policy']);
    assert.deepEqual(h.patch.robustness_policy.selection.image_ids,['i1']);
    assert.equal(h.patch.robustness_policy.copies,2);
  }finally{delete globalThis.window;delete globalThis.document;}
});

test('modal close only cancels the owning picker layer',async()=>{
  let signal;const layer={};
  const h=setup({materialIds:['saved'],newLabelCodes:[]},async(_url,options)=>{signal=options.signal;return new Promise(()=>{});});
  window.modal=()=>layer;
  try{
    await h.runtime.open('train');await tick();
    h.runtime.beforeModalClose({});
    assert.equal(signal.aborted,false);
    h.runtime.beforeModalClose(layer);
    assert.equal(signal.aborted,true);
    assert.equal(h.runtime.state(),null);
  }finally{delete globalThis.window;delete globalThis.document;}
});
