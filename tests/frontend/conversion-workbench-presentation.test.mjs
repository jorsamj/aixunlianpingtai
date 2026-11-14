import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const ui=fs.readFileSync(new URL('../../static/modules/conversion-workbench-ui.js',import.meta.url),'utf8');
const css=fs.readFileSync(new URL('../../static/conversion-workbench.css',import.meta.url),'utf8');
const catalog=fs.readFileSync(new URL('../../static/modules/conversion-catalog-runtime.js',import.meta.url),'utf8');

test('conversion history is a compact list with same-layer details and a back action',()=>{
  assert.match(ui,/conversion-ui-detail-header/);
  assert.match(ui,/data-conversion-ui-open/);
  assert.match(ui,/data-conversion-ui-back/);
  assert.match(ui,/conversion-ui-inspecting/);
  assert.match(ui,/job\.querySelector\('\.convert428-job-details'\)/);
  assert.match(css,/\.conversion-ui-inspecting \.conversion560-job:not\(\.conversion-ui-inspected\)/);
  assert.doesNotMatch(ui.slice(ui.indexOf('const closeDetail ='),ui.indexOf('root.addEventListener(\'click\'')),/modal\(/);
});

test('conversion quick filters invoke the canonical server filter rather than filtering the current page',()=>{
  assert.match(ui,/form\.requestSubmit\(\)/);
  assert.match(ui,/select\.dispatchEvent\(new Event\('change'/);
  assert.doesNotMatch(ui,/rows\.filter\(row=>\['queued'/);
  assert.match(ui,/Backend counters are authoritative/);
  assert.match(ui,/\['全部',''\]/);
});

test('conversion record actions are still original buttons and secondary actions are discoverable',()=>{
  assert.match(ui,/secondary\.forEach\(node => panel\.append\(node\)\)/);
  assert.match(ui,/conversion-ui-more-list/);
  assert.match(ui,/conversion560-numeric-action/);
  assert.match(css,/conversion-ui-more summary:focus-visible/);
});

test('required target-specific settings remain in the primary form region',()=>{
  for(const id of ['conv428OnnxFields','conv428SophonFields','conv428TensorRtFields','conv428Calibration'])
    assert.ok(ui.includes("'#"+id+"'"));
  assert.match(ui,/if\(node\)sections\[3\]\.insertBefore\(node,advance\)/);
  assert.match(ui,/后续验证/);
  assert.match(css,/\.conversion560-create \.conversion560-aside/);
});

test('catalog keeps canonical action ownership while de-cluttering vendor and chip tables',()=>{
  for(const action of ['view','edit','delete','enable','disable','detect'])
    assert.ok(catalog.includes(action));
  assert.match(catalog,/data-catalog-action=/);
  assert.match(catalog,/catalog-more-menu/);
  assert.match(catalog,/const primary=entity==='chips'\?'detect':'view'/);
  assert.match(css,/#conversion-catalog-host>\.panel-body/);
});

test('conversion presentation observer is scoped to conversion-node changes',()=>{
  assert.match(ui,/const conversionRootSelector='\.convert428-v2,\.convert428-create'/);
  assert.match(ui,/if\(isConversionMutation\(records\)\)schedule\(\)/);
  assert.match(ui,/record\.addedNodes/);
  assert.match(ui,/target\.closest\(conversionRootSelector\)/);
  assert.doesNotMatch(ui,/new MutationObserver\(schedule\)/);
});
