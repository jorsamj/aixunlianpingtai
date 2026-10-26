import test from 'node:test';
import assert from 'node:assert/strict';
import {auditSelection, auditCheckText} from '../../static/modules/smart-material-audit.js';

test('smart audit defaults to full filtered scope, not the current page',()=>{
  assert.deepEqual(auditSelection({filters:{dataset_id:'default'},pageIds:['one']}),{scope:'FILTERED',filters:{dataset_id:'default'}});
  assert.deepEqual(auditSelection({scope:'ALL',filters:{q:'old'}}),{scope:'FILTERED',filters:{}});
  assert.deepEqual(auditSelection({scope:'SELECTED',imageIds:['a','a','b']}),{scope:'SELECTED',image_ids:['a','b']});
  assert.throws(()=>auditSelection({scope:'SELECTED',imageIds:[]}),/选择/);
});
test('completed analysis and unknown checks never claim business correctness',()=>{
  assert.equal(auditCheckText({status:'completed',checked:2}),'已检查 · 2 张');
  assert.equal(auditCheckText({status:'not_checked'}),'未检查');
  assert.equal(auditCheckText({status:'unknown'}),'未知');
  assert.equal(auditCheckText({}),'未检查');
});
