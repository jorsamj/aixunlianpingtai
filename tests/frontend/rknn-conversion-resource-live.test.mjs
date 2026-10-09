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
  precision.innerHTML = '<option value="fp16">FP16</option><option value="int8">INT8</option>';
  const elems = {
    conv428Resource: select, conv428Chip: chip, conv428Warn: warning,
    conv428ResourceStatus: status, conv428ChipField: {querySelector: () => ({textContent: ''})},
    conv428Precision: precision, conv428Calibration: {hidden: false},
    conv428CalibrationDataset: new Select(), conv428Input: {value: '640'},
  };
  const radio = {value: 'rockchip'};
  const calls = [];
  let opened = false;
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
      key === '.convert428-create' ? (opened ? {} : null) :
      key.includes('[data-convert-submit]') ? submit : null,
  };
  const storage = new Map();
  const ctx = {
    window: null, ...actions, document: doc, state, pid: () => 'project-a',
    api: async () => {throw new Error('unexpected legacy resource API');},
    toast: message => warning.textContent = message,
    esc: value => String(value ?? ''),
    modal: () => {opened = true;},
    setTimeout: fn => fn(),
    localStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    },
  };
  // In browsers, window properties are also global name bindings.
  ctx.window = ctx;
  vm.runInNewContext(runtimeSource, ctx, {filename: 'app.js:canonical-conversion'});
  return {win:ctx, state, select, chip, warning, status, submit, radio, calls, storage};
}
const resource = (id, chips, state = 'ready', mode='local') => ({
  id, name: id, kind: 'rockchip', mode, status: state,
  targets: state === 'ready' ? ['rockchip'] : [], supported_chips: chips,
});
const ready = () => ({items: [resource('a800',['rk3568','rk3576'])]});

test('T01-T03: opening fetches authoritative RKNN chips despite an old cached snapshot', async () => {
  const h=setup(async () => ready());
  h.storage.set('cl_train_v428_deployresources_project-a_', JSON.stringify({
    items:[resource('a800',[])],
  }));
  await h.win.openNewConvertCore416('algo','v1');
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0],true);
  assert.equal(h.select.value,'a800');
  assert.deepEqual(h.chip.options.map(o=>o.value),['rk3568','rk3576']);
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
  assert.deepEqual(h.chip.options.map(o=>o.value),['rk3576']);
  assert.equal(h.chip.value,'rk3576');
  h.select.value='local'; h.select.onchange();
  assert.deepEqual(h.chip.options.map(o=>o.value),['rk3568','rk3576']);
  assert.ok(h.select.options.every(o=>o.value!=='offline'));
});

test('T06-T07: SDK failure and resource offline disable conversion without stale chips', async () => {
  let response=ready();
  const h=setup(async()=>response);
  await h.win.openNewConvertCore416('algo','v1');
  response={items:[resource('a800',[], 'missing')]};
  await h.win.refreshVersionConversionResources428();
  assert.equal(h.chip.value,'');
  assert.equal(h.submit.disabled,true);
  assert.equal(h.select.value,'');
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
  assert.deepEqual(h.chip.options.map(o=>o.value),['rk3576']);
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
  assert.deepEqual(h.chip.options.map(o=>o.value),['']);
});
