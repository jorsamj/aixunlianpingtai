import test from 'node:test';
import assert from 'node:assert/strict';
import {trainingMaterialSelectable} from '../../static/modules/training-material-picker-runtime.js';
test('same eligibility protects single and page selection',()=>{
 assert.equal(trainingMaterialSelectable({id:'x',training_usage:{excluded:true}},'train'),false);
 assert.equal(trainingMaterialSelectable({id:'x',training_usage:{state:'unknown'}},'test'),false);
 assert.equal(trainingMaterialSelectable({id:'x',annotation_state:'annotated',training_usage:{state:'unknown'}},'train'),true);
 assert.equal(trainingMaterialSelectable({id:'x'},'train',new Set(['x'])),false);
 assert.equal(trainingMaterialSelectable({id:'x',annotation_state:'unannotated'},'test'),false);
});

import {createTrainingDraft,trainingDraftToRequest} from '../../static/modules/training-draft.js';
test('large selection reference stays compact through Draft and request',()=>{
 const draft=createTrainingDraft({algorithmId:'a',newLabelCodes:['person'],trainSelectionRef:'trainselection_'+'a'.repeat(32),trainSelectionCount:200000,materialIds:[]});
 const request=trainingDraftToRequest(draft);
 assert.equal(request.train_selection_ref,draft.trainSelectionRef);
 assert.deepEqual(request.train_image_ids,[]);
 assert.ok(JSON.stringify(request).length<5000);
});
