import test from 'node:test';
import assert from 'node:assert/strict';
import {auditSelection, auditCheckText,annotationSummaryText} from '../../static/modules/smart-material-audit.js';

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
test('label suggestions separate native box counts, pending candidates and unchecked fields',()=>{
  const text=annotationSummaryText({suspected_images:2,possible_missing_boxes:3,pending_candidates:4,confirmed_candidates:1});
  assert.match(text,/异常 2 张/);assert.match(text,/漏标 3 框/);assert.match(text,/多标 未检查/);
  assert.match(text,/待复核 4 条/);assert.match(text,/由原 Full Audit 核验/);
});
