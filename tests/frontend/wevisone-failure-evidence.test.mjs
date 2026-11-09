import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('  const aiFailureFields60=');
const stop = source.indexOf('  async function loadAiFailureDetails60(', start);
assert.ok(start > 0 && stop > start, 'the original failure UI owner must be present');

function harness() {
  const blobs = [];
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const document = {createElement: () => ({click() {}})};
  const URL = {createObjectURL: () => 'blob:export', revokeObjectURL() {}};
  class Blob {constructor(parts, options) {blobs.push({parts, options});}}
  const code = source.slice(start, stop) + '\nreturn {aiFailureFields60,aiFailureEvidence60,aiFailureExport60};';
  const helpers = new Function('esc','document','URL','Blob','setTimeout', code)(escape, document, URL, Blob, () => {});
  return {...helpers, blobs};
}

test('failed WeVisOne image shows real bounded evidence and escapes native labels', () => {
  const {aiFailureEvidence60} = harness();
  const html = aiFailureEvidence60({returned_label:'<script>alert(1)</script>',
    allowed_labels:['person','tangzhe'], configured_queries:{person:'standing / walking'},
    label_match_status:'not_allowed',parser_source:'structured_boxes',zero_box:false,
    request_trace_id:'f'.repeat(32),response_summary:{structured_box_count:1},
    error_history:[{error_code:'MODEL_LABEL_NOT_ALLOWED',returned_label:'old'}]});
  assert.match(html,/模型实际返回标签/);
  assert.match(html,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html,/<script>/);
  assert.match(html,/person、tangzhe/);
  assert.match(html,/structured_boxes/);
  assert.match(html,/此前 1 次失败记录/);
});

test('failed-image CSV and JSON retain model label and internal request trace safely', () => {
  const {aiFailureExport60,aiFailureFields60,blobs} = harness();
  const row = {image_id:'img-1',filename:'192207505.jpg',error_code:'MODEL_LABEL_NOT_ALLOWED',
    returned_label:'=HYPERLINK("bad")', allowed_labels:['person','tangzhe'],
    configured_queries:{person:'standing'}, request_trace_id:'trace-0001',
    parser_source:'native_ref_box',response_summary:{raw_ref_count:1},http_status:200};
  assert.ok(aiFailureFields60.includes('returned_label') && aiFailureFields60.includes('response_summary'));
  aiFailureExport60([row],'csv');
  const csv = blobs[0].parts[0];
  assert.match(csv,/returned_label/);
  assert.match(csv,/trace-0001/);
  assert.match(csv,/'=HYPERLINK/); // CSV formula injection is inert.
  assert.match(csv,/native_ref_box/);
  aiFailureExport60([row],'json');
  const json = JSON.parse(blobs[1].parts[0]);
  assert.equal(json[0].returned_label, row.returned_label);
  assert.deepEqual(json[0].allowed_labels,['person','tangzhe']);
});
