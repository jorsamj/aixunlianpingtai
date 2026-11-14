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
  const code = source.slice(start, stop) + '\nreturn {aiFailureFields60,aiFailureEvidence60,aiFailureExport60,aiFailureCard60,collectAiFailureRows60};';
  const helpers = new Function('esc','document','URL','Blob','setTimeout','taskApi', code)(escape, document, URL, Blob, () => {}, id => '/api/tasks/' + id);
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
    parser_source:'native_ref_box',response_summary:{raw_ref_count:1},http_status:200,
    error_history:[{attempt:1,error_code:'MODEL_LABEL_NOT_ALLOWED',request_trace_id:'trace-old'}]};
  assert.ok(aiFailureFields60.includes('returned_label') && aiFailureFields60.includes('response_summary'));
  aiFailureExport60([row],'csv');
  const csv = blobs[0].parts[0];
  assert.match(csv,/returned_label/);
  assert.match(csv,/trace-0001/);
  assert.match(csv,/'=HYPERLINK/); // CSV formula injection is inert.
  assert.match(csv,/native_ref_box/);
  assert.match(csv,/trace-old/); // Historical evidence arrays stay structured, not [object Object].
  assert.doesNotMatch(csv,/\[object Object\]/);
  aiFailureExport60([row],'json');
  const json = JSON.parse(blobs[1].parts[0]);
  assert.equal(json[0].returned_label, row.returned_label);
  assert.deepEqual(json[0].allowed_labels,['person','tangzhe']);
});

test('task failure cards prioritize useful diagnosis and safely collapse full technical evidence', () => {
  const {aiFailureCard60} = harness();
  const html = aiFailureCard60({image_id:'image/1',filename:'room.jpg',url:'/images/1',
    status:'failed',http_status:200,error_code:'MODEL_LABEL_NOT_ALLOWED',error_stage:'response_parse',
    error:'<script>unsafe</script>',returned_label:'person. tangzhe.',
    allowed_labels:['person','tangzhe'],retry_suggestion:'核对标签映射后重试'});
  assert.match(html, /class="ai60-failure-code"[^>]*>MODEL_LABEL_NOT_ALLOWED/);
  assert.match(html, /查看技术诊断与历史记录/);
  assert.match(html, /<details class="ai60-failure-diagnostics">/);
  assert.match(html, /data-ai-retry-image="image%2F1"/);
  assert.match(html, /&lt;script&gt;unsafe&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /模型实际返回标签/);
});

test('full failure export traverses every page and preserves all 238 distinct diagnostics', async () => {
  const {collectAiFailureRows60,aiFailureExport60,blobs} = harness();
  const sourceRows = Array.from({length:238},(_,index)=>({image_id:'image-'+index,
    filename:'image-'+index+'.jpg',status:'failed',error_code:'MODEL_LABEL_NOT_ALLOWED',
    request_trace_id:'trace-'+index,returned_label:'person. tangzhe.'}));
  const cursors=[],progress=[];
  const request = async (url,{signal}) => {
    assert.equal(signal.aborted,false);
    assert.match(url, /filter=failed/);
    const cursor=Number(new URL(url,'https://example.test').searchParams.get('cursor'));
    cursors.push(cursor);
    return {items:sourceRows.slice(cursor,cursor+100),total:sourceRows.length,
      review_revision:9,next_cursor:cursor+100<sourceRows.length?String(cursor+100):null};
  };
  const rows=await collectAiFailureRows60('task-1',{request,signal:new AbortController().signal,onProgress:(done,total)=>progress.push([done,total])});
  assert.deepEqual(cursors,[0,100,200]);
  assert.deepEqual(progress,[[100,238],[200,238],[238,238]]);
  assert.equal(rows.length,238);
  assert.ok(rows.every(row=>row.task_id==='task-1'));
  aiFailureExport60(rows,'csv','annotation-errors-task-1-238');
  const csv=blobs[0].parts[0];
  assert.equal(csv.split('\r\n').length,239);
  assert.match(csv,/trace-237/);
  assert.match(csv,/trace-0/);
});

test('all-pages export rejects revised, missing or duplicated records without silently writing a partial file', async () => {
  const {collectAiFailureRows60,blobs} = harness();
  const first={items:[{image_id:'A',status:'failed'}],total:2,review_revision:2,next_cursor:'1'};
  for(const second of [
    {items:[{image_id:'B',status:'failed'}],total:2,review_revision:3,next_cursor:null},
    {items:[{image_id:'A',status:'failed'}],total:2,review_revision:2,next_cursor:null},
    {items:[],total:2,review_revision:2,next_cursor:null},
  ]){
    let calls=0;
    await assert.rejects(collectAiFailureRows60('task-2',{request:async()=>++calls===1?first:second}),
      /发生变化|重复或遗漏|未生成不完整文件/);
  }
  assert.equal(blobs.length,0);
});

test('network failure or explicit cancellation halts all-pages export', async () => {
  const {collectAiFailureRows60,blobs} = harness();
  const first={items:[{image_id:'A',status:'failed'}],total:2,review_revision:5,next_cursor:'1'};
  let calls=0;
  await assert.rejects(collectAiFailureRows60('task-3',{request:async()=>++calls===1?first:Promise.reject(new Error('network down'))}),/network down/);
  const controller=new AbortController();calls=0;
  await assert.rejects(collectAiFailureRows60('task-3',{request:async()=>{calls++;return first},
    signal:controller.signal,onProgress:()=>controller.abort()}),error=>error.name==='AbortError');
  assert.equal(calls,1);
  assert.equal(blobs.length,0);
});

test('failure UI has a page-independent full export, backward paging and bounded list', () => {
  assert.match(source,/data-ai-export-format="csv">导出全部问题 CSV/);
  assert.match(source,/data-ai-export-format="json">导出全部 JSON/);
  assert.match(source,/candidates\?limit=12&cursor=/);
  assert.match(source,/candidates\?limit=100&cursor=/);
  assert.match(source,/data-ai-failure-previous/);
  assert.match(source,/data-ai-failure-next/);
  assert.doesNotMatch(source,/导出本页错误/);
});

test('single-image retry closes its original modal before reopening the same polling owner', async () => {
  const start = source.indexOf('  window.retryAiFailureImage60=async(');
  const stop = source.indexOf('  window.showTaskProgress427=', start);
  assert.ok(start > 0 && stop > start);
  const calls = [];
  let currentLayer = {id:'original-modal'};
  const window = {
    ModalContentRuntime: {captureOwner: () => ({layer:currentLayer, isCurrent:() => true}), activeLayer:() => currentLayer},
    closeModalLayer424: layer => {assert.equal(layer,currentLayer);calls.push('close');currentLayer=null;},
    showAiTask60: async id => {assert.equal(currentLayer,null);calls.push('show:'+id);},
  };
  const api = async (url, options) => {
    calls.push('post:'+url);
    assert.deepEqual(JSON.parse(options.body).image_ids,['image/id']);
  };
  new Function('window','api','taskApi','toast','decodeURIComponent',source.slice(start,stop))(
    window,api,id=>'/tasks/'+id,message=>calls.push('toast:'+message),decodeURIComponent);
  await window.retryAiFailureImage60('task-1',encodeURIComponent('image/id'));
  assert.deepEqual(calls,['post:/tasks/task-1/retry','toast:已提交此图重试','close','show:task-1']);
});

test('WeVisOne create confirmation presents native detection, not the unused JSON prompt', () => {
  const start = source.indexOf('  function renderAiCreateConfirmation429(');
  const stop = source.indexOf('  function newAiCreateRequestId429(', start);
  assert.ok(start > 0 && stop > start);
  const root = {innerHTML: '', hidden: true, scrollIntoView() {}, insertAdjacentHTML() {}};
  const document = {getElementById: id => id === 'ai429Confirmation' ? root : null};
  const state = {modelConfigs: [{id: 'we-2b', name: '2B', model_name: 'wevisone-vl-2b',
    provider_adapter: 'wevisone_vl', coordinate_space: 'pixel', coordinate_order: 'xyxy',
    coordinate_origin: 'top_left', coordinate_image_space: 'original_input',
    wevisone_label_queries: {person: 'A standing person', tangzhe: 'A lying person'}}],
    promptTemplates: [], labels: [], ai429Create: {selectionSummary: {count: 2}}};
  const window = {PlatformCore: {materials: {labelDisplay: code => code}}};
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const render = new Function('document','state','window','esc',source.slice(start,stop) + '\nreturn renderAiCreateConfirmation429;')(
    document,state,window,esc);
  const body = {model_config_id:'we-2b',labels_text:'person、tangzhe',image_ids:['1','2'],
    task_name:'native task',threshold:0.45,overwrite:false,reference_image_ids:[],
    prompt_override:'YOU MUST RETURN JSON',business_instruction:'SECRET GENERIC PROMPT'};
  render(body);
  assert.match(root.innerHTML,/本次实际推理配置/);
  assert.match(root.innerHTML,/detection · 逐标签请求/);
  assert.match(root.innerHTML,/A standing person/);
  assert.match(root.innerHTML,/A lying person/);
  assert.match(root.innerHTML,/original_input/);
  assert.doesNotMatch(root.innerHTML,/YOU MUST RETURN JSON/);
  assert.doesNotMatch(root.innerHTML,/data:image\/jpeg;base64/);
  state.modelConfigs[0].provider_adapter = 'local_openai';
  render(body);
  assert.match(root.innerHTML,/查看本次完整提示词配置/);
  assert.match(root.innerHTML,/YOU MUST RETURN JSON/);
});

test('task detail displays only the server-frozen native configuration', () => {
  const start=source.indexOf('  function aiNativeConfigDetail60(');
  const stop=source.indexOf('  function renderProgress(',start);
  assert.ok(start>0&&stop>start);
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const render = new Function('esc',source.slice(start,stop)+'\nreturn aiNativeConfigDetail60;')(esc);
  const native={adapter:'wevisone_vl',model:'wevisone-vl-2b',task:'detection',request_mode:'per_label',
    endpoint:'/v1/vision/detect',query_type:'list[str]',label_queries:{person:'A standing person',tangzhe:'A lying human'},
    coordinate_space:'pixel',coordinate_order:'xyxy',coordinate_origin:'top_left',coordinate_image_space:'original_input'};
  assert.match(render(native),/任务冻结/);
  assert.match(render(native),/A lying human/);
  assert.match(render(native),/逐标签请求/);
  assert.doesNotMatch(render(native),/base64,/);
  assert.equal(render(null),'');
  assert.equal(render({...native,adapter:'local_openai'}),'');
});
