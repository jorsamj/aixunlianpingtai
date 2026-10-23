import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const full = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const start = full.indexOf('/* v42.16 conversion resource readiness');
const end = full.indexOf('window.installUsability417?.();', start);
assert.ok(start > 0 && end > start, 'must execute the canonical conversion resource layer');
const runtimeSource = full.slice(start, end);

class Select {
  constructor() { this.options = []; this.value = ''; this.onchange = null; }
  set innerHTML(html) {
    this._html = html;
    this.options = [...String(html).matchAll(/<option value="([^"]*)"/g)]
      .map(item => ({value: item[1], disabled: false}));
    this.value = this.options[0]?.value ?? '';
  }
  get innerHTML() { return this._html || ''; }
  get selectedOptions() { return this.options.filter(item => item.value === this.value); }
}
function setup(getResource) {
  const select = new Select();
  const chip = new Select();
  const warning = {textContent: ''};
  const status = {innerHTML: ''};
  const submit = {disabled: false};
  const precision = new Select();
  precision.innerHTML = '<option value="fp16">FP16</option><option value="fp32">FP32</option><option value="int8">INT8</option>';
  const elems = {
    conv428Resource: select, conv428Chip: chip, conv428Warn: warning,
    conv428ResourceStatus: status, conv428ChipField: {querySelector: () => ({textContent: ''})},
    conv428Precision: precision, conv428Calibration: {hidden: false},
    conv428CalibrationDataset: new Select(), conv428Input: {value: '640'},
  };
  const radio = {value: 'rockchip',get dataset(){return {vendorId:['rockchip','sophon','ascend'].includes(this.value)?this.value:''}}};
  const catalog={vendors:[{id:'rockchip',name:'瑞芯微',template_id:'rknn'},{id:'sophon',name:'算能',template_id:'tpu-mlir'}],
    templates:[{id:'rknn',adapter:'rockchip'},{id:'tpu-mlir',adapter:'sophon'}],
    chips:['rk3568','rk3576'].map(id=>({id,vendor_id:'rockchip',name:id.toUpperCase()})).concat(['bm1684x','bm1688'].map(id=>({id,vendor_id:'sophon',name:id.toUpperCase()})))};
  const calls = [];
  let opened = false;
  let form = null;
  let modalMarkup = '';
  const actions = {
    loadVersionConversionResources428: async force => {calls.push(force); return getResource();},
    loadVersionConversionHistory428: async () => ({
      algorithm: {name:'A'}, version: {stored_path: '/tmp/model.pt',version_name:'v1'},
    }),
  };
  const state = {datasets: []};
  const doc = {
    getElementById: id => elems[id] || null,
    querySelector: key => key.includes('conv428Target') ? radio :
      key === '.convert428-create' ? form :
      key.includes('[data-convert-submit]') ? submit : null,
  };
  const storage = new Map();
  const ctx = {
    window: null, ...actions, document: doc, state, pid: () => 'project-a',
    api: async (url,options) => {
      if(url==='/api/v39/deploy/catalog')return catalog;
      if(!url.endsWith('/deploy/resolve'))throw new Error('unexpected legacy resource API');
      const body=JSON.parse(options.body),params=body.params,r=(state.conv428Resources||[]).find(r=>r.id===body.resource_id);
      const chips=catalog.chips.filter(c=>c.vendor_id===params.local_vendor_id);
      const found=chips.find(c=>c.id===params.local_chip_id),supported=(r?.supported_chips||[]).includes(found?.id);
      const allowed=body.target==='sophon'?['fp16']:['fp16'];
      return {ready:!!supported,status:supported?'convertible':'not_convertible',errors:supported?[]:['SDK未支持所选芯片'],
        allowed_precisions:allowed,parameter_sources:{precision:'SDK/芯片约束'},params:{...params,chip:found?.id,precision:'fp16',input_width:640,input_height:640},
        chip_options:chips.map(c=>({...c,status_label:(r?.supported_chips||[]).includes(c.id)?'可转换':'不可转换'}))};
    },
    toast: message => warning.textContent = message,
    esc: value => String(value ?? ''),
    modal: (_title, markup) => {opened = true;form={};modalMarkup = String(markup);},
    setTimeout: fn => fn(),
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
  };
  // In browsers, window properties are also global name bindings.
  ctx.window = ctx;
  vm.runInNewContext(runtimeSource, ctx, {filename: 'app.js:canonical-conversion'});
  return {win:ctx, state, elements:elems, select, chip, precision, warning, status, submit, radio, calls, storage,
    catalog,get modalMarkup(){return modalMarkup}};
}
const resource = (id, chips, state = 'ready', mode='local') => ({
  id, name: id, kind: 'rockchip', mode, status: state,
  targets: state === 'ready' ? ['rockchip'] : [], supported_chips: chips,
});
const ready = () => ({items: [resource('a800',['rk3568','rk3576'])]});

test('a vendor response cannot alter submission after switching to direct ONNX',async()=>{
  const h=setup(async()=>({items:[resource('rk',['rk3568']),{id:'onnx',kind:'ultralytics',status:'ready',name:'ONNX',targets:['onnx']}]}));
  await h.win.openNewConvertCore416('a','v');
  h.chip.value='rk3568';
  let deliver;h.win.api=()=>new Promise(resolve=>deliver=resolve);
  const pending=h.win.refreshConvertContract428();
  h.radio.value='onnx';h.win.refreshConvertResource428();
  assert.equal(h.submit.disabled,false);
  deliver({ready:false,errors:['old vendor failure'],allowed_precisions:[],params:{},chip_options:[]});
  await pending;
  assert.equal(h.submit.disabled,false);
  assert.notEqual(h.warning.textContent,'old vendor failure');
});


test('a late contract response cannot overwrite input dimensions while the user is editing',async()=>{
  const h=setup(async()=>({items:[{id:'s',kind:'sophon',name:'S',status:'ready',targets:['sophon'],supported_chips:['bm1688'],supported_precisions:['fp16']}]}));
  await h.win.openNewConvertCore416('a','v');
  h.radio.value='sophon';h.win.refreshConvertResource428();h.chip.value='bm1688';
  h.elements.conv428Width={value:'640'};h.elements.conv428Height={value:'800'};
  h.state.conv428ShapeEdited=true;
  let deliver;
  h.win.api=()=>new Promise(resolve=>deliver=resolve);
  const pending=h.win.refreshConvertContract428();
  h.elements.conv428Height.value='384';
  deliver({ready:true,allowed_precisions:['fp16'],params:{precision:'fp16',input_width:640,input_height:800},parameter_sources:{},chip_options:[]});
  await pending;
  assert.equal(h.elements.conv428Height.value,'384');
});


test('dictionary vendors alone drive vendor targets; new vendor does not require a frontend enum',async()=>{
  const h=setup(async()=>ready());
  h.catalog.vendors=[{id:'local-r',name:'设备厂商甲',template_id:'rknn'}];
  await h.win.openNewConvertCore416('a','v');
  assert.match(h.modalMarkup,/设备厂商甲/);
  assert.doesNotMatch(h.modalMarkup,/data-vendor-id="sophon"/);
  assert.match(h.modalMarkup,/data-vendor-id="local-r"/);
});

test('multiple local chips require an explicit choice before a successful backend contract',async()=>{
  const h=setup(async()=>ready());
  await h.win.openNewConvertCore416('a','v');
  assert.equal(h.chip.value,'');
  assert.equal(h.submit.disabled,true);
  h.chip.value='rk3576';await h.win.refreshConvertContract428();
  assert.equal(h.state.conv428Resolved.params.chip,'rk3576');
  assert.equal(h.submit.disabled,false);
});

test('unsupported chip remains visible and cannot submit even though another chip works',async()=>{
  const h=setup(async()=>({items:[resource('r',['rk3576'])]}));
  await h.win.openNewConvertCore416('a','v');
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
  h.chip.value='rk3568';await h.win.refreshConvertContract428();
  assert.equal(h.submit.disabled,true);
  assert.match(h.warning.textContent,/SDK/);
});


test('T01-T03: opening fetches authoritative RKNN chips despite an old cached snapshot', async () => {
  const h=setup(async () => ready());
  h.storage.set('cl_train_v428_deployresources_project-a_', JSON.stringify({
    items:[resource('a800',[])],
  }));
  await h.win.openNewConvertCore416('algo','v1');
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0],true);
  assert.equal(h.select.value,'a800');
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
  h.chip.value=h.radio.value==='sophon'?'bm1688':'rk3568';await h.win.refreshConvertContract428();
  assert.equal(h.submit.disabled,false);
});

test('T04-T05 and T08: switching local and Agent resources never reuses unsupported chips', async () => {
  const h=setup(async()=>({items:[
    resource('local',['rk3568','rk3576']),
    resource('agent',['rk3576'],'ready','agent'),
    resource('offline',['rk3568'],'missing')
  ]}));
  await h.win.openNewConvertCore416('algo','v1');
  h.chip.value='rk3568';
  h.select.value='agent'; h.select.onchange();
  assert.equal(h.select.value,'agent');
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
  assert.equal(h.chip.value,'rk3568');
  await h.win.refreshConvertContract428();assert.equal(h.submit.disabled,true);
  h.chip.value='rk3576';await h.win.refreshConvertContract428();assert.equal(h.submit.disabled,false);
  h.select.value='local'; h.select.onchange();
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
  assert.ok(h.select.options.every(o=>o.value!=='offline'));
});

test('T06-T07: SDK failure and resource offline disable conversion without stale chips', async () => {
  let response=ready();
  const h=setup(async()=>response);
  await h.win.openNewConvertCore416('algo','v1');
  response={items:[resource('a800',[], 'missing')]};
  await h.win.refreshVersionConversionResources428();
  assert.equal(h.select.value,'');
  assert.equal(h.submit.disabled,true);
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
});

test('T09: an older asynchronous response cannot overwrite the latest refresh', async () => {
  let deliverOld;
  const old=new Promise(resolve=>{deliverOld=resolve;});
  let count=0;
  const h=setup(async()=>++count===1?ready():count===2?old:({items:[resource('new',['rk3576'])]}));
  await h.win.openNewConvertCore416('algo','v1');
  const inFlight=h.win.refreshVersionConversionResources428();
  const latest=h.win.refreshVersionConversionResources428();
  await latest;
  deliverOld({items:[resource('old',['rk3568'])]});
  await inFlight;
  assert.equal(h.select.value,'new');
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
});

test('T02 and T14: repeated dialog opens query fresh state (no localStorage as authority)', async () => {
  let models=ready();
  const h=setup(async()=>models);
  await h.win.openNewConvertCore416('algo','v1');
  models={items:[resource('new',['rk3576'])]};
  await h.win.openNewConvertCore416('algo','v1');
  assert.equal(h.calls.length,2);
  assert.equal(h.select.value,'new');
});

test('T06: failed authoritative fetch disables submit, it never restores cached ready capability', async () => {
  let broken=false;
  const h=setup(async()=>{if(broken)throw new Error('API unreachable');return ready();});
  await h.win.openNewConvertCore416('algo','v1');
  broken=true;
  await h.win.refreshVersionConversionResources428();
  assert.equal(h.state.conv428ResourcesCurrent,false);
  assert.equal(h.submit.disabled,true);
  assert.deepEqual(h.chip.options.map(o=>o.value),['','rk3568','rk3576']);
});

test('T10 and T13: RKNN FP16 remains eligible, unsupported FP32 is not selectable', async () => {
  const h=setup(async()=>ready());
  await h.win.openNewConvertCore416('algo','v1');
  h.chip.value='rk3568';await h.win.refreshConvertContract428();
  assert.equal(h.precision.value,'fp16');
  assert.equal(h.precision.options.find(option=>option.value==='fp32').disabled,true);
  h.chip.value=h.radio.value==='sophon'?'bm1688':'rk3568';await h.win.refreshConvertContract428();
  assert.equal(h.submit.disabled,false);
});

test('new conversion UI inherits PT actual precision and size, but RKNN uses only supported output precision',async()=>{
  const h=setup(async()=>ready());
  h.win.loadVersionConversionHistory428=async()=>({
    algorithm:{name:'A'},version:{stored_path:'/tmp/best.pt',version_name:'v2',
      conversion_defaults:{input_size:800,training_precision:'fp32',precision_source:'训练任务实际运行精度'}}
  });
  await h.win.openNewConvertCore416('algo','v2');
  assert.match(h.modalMarkup,/id="conv428Input"[^>]*value="800"/);
  assert.match(h.modalMarkup,/源模型训练：FP32 · 800 px/);
  // This mock resource supports RKNN FP16, not FP32.
  h.chip.value='rk3568';await h.win.refreshConvertContract428();
  assert.equal(h.precision.value,'fp16');
  assert.equal(h.precision.options.find(option=>option.value==='fp32').disabled,true);
  h.radio.value='onnx';
  h.win.refreshConvertResource428();
  assert.equal(h.precision.value,'fp32');
  assert.equal(h.state.conv428ModelDefaults.input_size,800);
});


test('Sophon keeps business chips visible and uses backend-confirmed precision', async () => {
  const h=setup(async()=>({items:[{id:'sophon',name:'TPU-MLIR',kind:'sophon',mode:'remote',status:'ready',
    targets:['sophon'],supported_chips:['bm1688','cv186x'],supported_precisions:['fp16']}]}));
  await h.win.openNewConvertCore416('algo','v1');
  h.radio.value='sophon';h.win.refreshConvertResource428();await h.win.refreshConvertContract428();
  assert.deepEqual(h.chip.options.map(o=>o.value),['','bm1684x','bm1688']);
  assert.equal(h.precision.options.find(o=>o.value==='int8').disabled,true);
  assert.equal(h.precision.options.find(o=>o.value==='fp32').disabled,true);
  assert.match(h.modalMarkup,/conv428Width/);
  assert.match(h.modalMarkup,/conv428Preprocess/);
});

test('Sophon cannot submit when a nominally ready resource omits actual chips', async () => {
  const h=setup(async()=>({items:[{id:'sophon',name:'broken tools',kind:'sophon',mode:'remote',status:'ready',targets:['sophon']}]}));
  await h.win.openNewConvertCore416('algo','v1');
  h.radio.value='sophon';h.win.refreshConvertResource428();await h.win.refreshConvertContract428();
  assert.equal(h.chip.value,'');
  assert.equal(h.submit.disabled,true);
});


test('Sophon remote resource recovery preserves source and full SDK version in the conversion dialog', async () => {
  let mode='missing';
  const h=setup(async()=>({items:mode==='none'?[]:[{id:'remote-sophon',name:'独立算能资源',kind:'sophon',mode:'remote',
    status:mode,targets:mode==='ready'?['sophon']:[],supported_chips:mode==='ready'?['bm1684x','bm1688']:[],
    supported_precisions:mode==='ready'?['fp16']:[],version:mode==='ready'?'v1.30.2-20260831':'',
    message:mode==='missing'?'HTTP 401：远程资源不可用':'远程算能资源可用'}]}));
  await h.win.openNewConvertCore416('algo','v1');
  h.radio.value='sophon';h.win.refreshConvertResource428();await h.win.refreshConvertContract428();
  assert.equal(h.submit.disabled,true);
  assert.match(h.status.innerHTML,/401/);
  mode='ready';await h.win.refreshVersionConversionResources428();
  assert.equal(h.submit.disabled,true); // Two chips require explicit user selection.
  h.chip.value='bm1688';await h.win.refreshConvertContract428();assert.equal(h.submit.disabled,false);
  assert.match(h.status.innerHTML,/远程服务器/);
  assert.match(h.status.innerHTML,/v1\.30\.2-20260831/);
  assert.deepEqual(h.chip.options.map(o=>o.value),['','bm1684x','bm1688']);
  mode='missing';await h.win.refreshVersionConversionResources428();
  assert.equal(h.submit.disabled,true);
  mode='none';await h.win.refreshVersionConversionResources428();
  assert.match(h.status.innerHTML,/尚未配置/);
  assert.equal(h.submit.disabled,true);
});


test('an older dialog response cannot replace a newly opened source catalog or defaults',async()=>{
  const h=setup(async()=>ready());
  let deliver;let count=0;
  h.win.loadVersionConversionHistory428=()=>++count===1?new Promise(r=>deliver=r):Promise.resolve({algorithm:{},version:{version_name:'new',conversion_defaults:{input_width:384,input_height:640}}});
  const old=h.win.openNewConvertCore416('a','old');
  await h.win.openNewConvertCore416('a','new');
  deliver({algorithm:{},version:{version_name:'old',conversion_defaults:{input_width:800,input_height:800}}});
  await old;
  assert.equal(h.state.conv428SourceId,'version::a::new');
});


test('selected resource detection uses one existing detect call and restores the chosen chip',async()=>{
  const h=setup(async()=>ready());await h.win.openNewConvertCore416('a','v');
  h.chip.value='rk3568';await h.win.refreshConvertContract428();
  const api=h.win.api,posts=[];let finish;
  h.win.api=(url,options)=>{if(url.endsWith('/detect')){posts.push(url);return new Promise(r=>finish=r)}return api(url,options)};
  const pending=h.win.refreshVersionConversionResources428(true);
  await h.win.refreshVersionConversionResources428(true);
  assert.equal(posts.length,1);assert.equal(posts[0],'/api/v39/deploy/resources/a800/detect');
  finish({...resource('a800',['rk3568']),version:'2.3.2'});await pending;
  assert.equal(h.select.value,'a800');assert.equal(h.chip.value,'rk3568');
  assert.equal(h.state.conv428Resources[0].version,'2.3.2');
});


test('selected SDK response cannot restore a chip changed while detection is pending',async()=>{
  const h=setup(async()=>ready());await h.win.openNewConvertCore416('a','v');
  h.chip.value='rk3568';await h.win.refreshConvertContract428();
  const api=h.win.api;let finish;
  h.win.api=(url,options)=>url.endsWith('/detect')?new Promise(r=>finish=r):api(url,options);
  const pending=h.win.refreshVersionConversionResources428(true);
  h.chip.value='rk3576';
  finish(resource('a800',['rk3568','rk3576']));await pending;
  assert.equal(h.chip.value,'rk3576');
});


test('failed SDK contract shows a terminal diagnostic instead of a stuck detecting chip',async()=>{
  const h=setup(async()=>ready());await h.win.openNewConvertCore416('a','v');
  h.chip.value='rk3568';h.win.api=async()=>{throw new Error('SDK authentication failed')};
  await h.win.refreshConvertContract428();
  assert.equal(h.submit.disabled,true);assert.match(h.warning.textContent,/authentication failed/);
  assert.match(h.chip.options.find(o=>o.value==='rk3568').textContent,/检测失败/);
});


test('failed older dialog load cannot invalidate a newer ready source',async()=>{
  const h=setup(async()=>ready());let fail;let calls=0;
  h.win.loadVersionConversionHistory428=()=>++calls===1?new Promise((_,reject)=>fail=reject):Promise.resolve({version:{stored_path:'/tmp/new.pt'},algorithm:{}});
  const pending=h.win.openNewConvertCore416('a','old');await h.win.openNewConvertCore416('a','new');
  fail(new Error('old history failed'));await pending;
  assert.equal(h.state.conv428ResourcesCurrent,true);assert.equal(h.state.conv428SourceId,'version::a::new');
  assert.doesNotMatch(h.warning.textContent,/old history failed/);
});

test('failed selected detection cannot erase a different ready resource',async()=>{
  const h=setup(async()=>({items:[resource('a',['rk3568']),resource('b',['rk3576'])]}));
  await h.win.openNewConvertCore416('a','v');let fail;const api=h.win.api;
  h.win.api=(url,options)=>url.endsWith('/detect')?new Promise((_,reject)=>fail=reject):api(url,options);
  const pending=h.win.refreshVersionConversionResources428(true);h.select.value='b';h.chip.value='rk3576';
  fail(new Error('resource a unauthorized'));await pending;
  assert.equal(h.select.value,'b');assert.equal(h.state.conv428ResourcesCurrent,true);
  assert.equal(h.state.conv428Resources.find(r=>r.id==='b').status,'ready');
});
