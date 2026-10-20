import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
function runtime(){
  const start=app.indexOf('let conversionCatalogSession428=');
  assert.ok(start>=0,'existing catalog Owner must support one list/form session');
  const end=app.indexOf('window.refreshConvertContract428=',start);
  const state={convCatalogEditor:{revision:7,vendors:[{id:'local-s',name:'算能',template_id:'tpu-mlir'},{id:'hidden',name:'隐藏厂商',template_id:'rknn'}],chips:[{id:'old',vendor_id:'hidden',name:'原始型号',code:'unchanged',sdk_code:'rk3568',constraint_id:'rknn-verified'}],chip_suggestions:[{template_id:'tpu-mlir',name:'BM1684X',sdk_code:'bm1684x',constraint_id:'sophon-fp16-verified'}]}};
  const ctx=vm.createContext({window:{},state,crypto:webcrypto});
  vm.runInContext(app.slice(start,end),ctx);return ctx;
}
test('automatic catalog IDs are legal unique identities rather than display-name slugs',()=>{
  const c=runtime();const ids=Array.from({length:60},()=>c.newConversionCatalogId428('chip'));
  assert.equal(new Set(ids).size,60);assert.ok(ids.every(id=>/^chip-[a-z0-9-]{36}$/.test(id)));
});
test('chip suggestions match only the backend template and verified model aliases',()=>{
  const c=runtime();assert.equal(c.conversionCatalogSuggestion428('tpu-mlir','bm-1684x').sdk_code,'bm1684x');
  assert.equal(c.conversionCatalogSuggestion428('rknn','BM1684X'),undefined);
  assert.equal(c.conversionCatalogSuggestion428('tpu-mlir','BM9999'),undefined);
  assert.equal(c.conversionCatalogSuggestion428('tpu-mlir','定制BM1684X'),undefined);
});
test('single record edits preserve all hidden vendor and chip identities and revision',()=>{
  const c=runtime(),before=JSON.stringify(c.state.convCatalogEditor);
  const candidate=c.conversionCatalogWithRecord428('vendors',{id:'local-s',name:'新显示名',template_id:'tpu-mlir'});
  assert.equal(candidate.revision,7);assert.equal(candidate.vendors.length,2);assert.equal(candidate.chips.length,1);
  assert.equal(candidate.chips[0].sdk_code,'rk3568');assert.equal(candidate.chips[0].id,'old');
  assert.equal(candidate.vendors[0].id,'local-s');assert.equal(candidate.vendors[1].id,'hidden');
  assert.equal(JSON.stringify(c.state.convCatalogEditor),before,'failed saves must not mutate authoritative editor data');
});

test('automatic IDs work on HTTP deployments without randomUUID support',()=>{
  const c=runtime();c.crypto={getRandomValues:array=>webcrypto.getRandomValues(array)};
  const id=c.newConversionCatalogId428('vendor');assert.match(id,/^vendor-[a-f0-9-]{36}$/);
});
