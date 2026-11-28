import test from 'node:test';
import assert from 'node:assert/strict';
import {installTrainingMaterialPickerRuntime} from '../../static/modules/training-material-picker-runtime.js';

test('bounded picker review requires explicit selection and confirmation, preserves failures, sends server revision-bound evidence without formal GT writes', async () => {
  const hosts=new Map();
  const host=id=>{if(!hosts.has(id))hosts.set(id,{id,hidden:false,textContent:'',innerHTML:'',dataset:{},classList:{toggle(){}},addEventListener(){}});return hosts.get(id);};
  globalThis.document={getElementById:host,querySelectorAll:()=>[],head:{appendChild(){}}};
  let confirms=0, fail=true;
  globalThis.window={modal(){},confirm(){confirms++;return true;},PlatformCore:{pagination:{mountPagination(){}}}};
  const calls=[];
  const draft={algorithmId:'vest-alg',newLabelCodes:['vest'],config:{model:'m.pt'}};
  const runtime=installTrainingMaterialPickerRuntime({getState:()=>({labels:[]}),projectId:()=> 'p',
    trainingDraftRuntime:{current:()=>draft,update(){}},fetchImpl:async(url,options)=>{
      const body=options.body?JSON.parse(options.body):null;calls.push({url,body});
      if(url.endsWith('/negative-preview'))return {ok:true,json:async()=>({pending_count:1,counts:{pending_negative:1},proof_digest:'version-seven-source-sha'})};
      if(url.endsWith('/confirm-negatives'))return {ok:!fail,json:async()=>fail?{detail:'版本冲突'}:{confirmed_count:1,receipt_ids:['r']}};
      return {ok:true,json:async()=>({items:[{id:'person-1',sample_role:'pending_negative',annotation_version:7,source_content_sha256:'sha',boxes:[],annotation_state:'annotated'}],effective_label_codes:['vest'],sample_role_counts:{pending_negative:1},total:1,page:1})};
    }});
  try {
    await runtime.open('train'); await new Promise(resolve=>setTimeout(resolve,0));
    await runtime.startReview();
    await runtime.confirmReview();
    assert.equal(calls.filter(call=>call.url.endsWith('/confirm-negatives')).length,0);
    window.toggleTrainMaterialV3('person-1',true);
    await runtime.confirmReview();
    assert.equal(confirms,1);
    assert.match(host('trV3ReviewProgress').textContent,/版本冲突/);
    const sent=calls.find(call=>call.url.endsWith('/confirm-negatives')).body;
    assert.deepEqual(sent.image_ids,['person-1']);
    assert.equal(sent.proof_digest,'version-seven-source-sha');
    assert.equal(calls.some(call=>call.url.includes('/annotations/')||call.url.endsWith('/review-negative')),false);
    assert.deepEqual(sent.train_labels,['vest']);
    fail=false;
    await runtime.confirmReview();
    assert.equal(confirms,2,'failed selection remains selected for explicit retry');
    assert.match(host('trV3ReviewProgress').textContent,/已保存 1\/1/);
    assert.equal(runtime.state().selected,0,'review choices do not silently modify training selection');
    assert.equal(calls.filter(call=>call.url.endsWith('/role-page')).at(-1).body.page,1,'shrinking pending review returns to page one');
    draft.newLabelCodes=[];
    await runtime.open('train'); await new Promise(resolve=>setTimeout(resolve,0));
    assert.match(calls.findLast(call=>call.url.includes('/training-materials?')).url,/training-materials\?/,'first training can select materials before choosing labels');
  } finally {delete globalThis.window;delete globalThis.document;}
});
