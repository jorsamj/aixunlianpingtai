import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('conversion submit freezes an idempotency key before POST and persists uncertain results', () => {
  assert.match(source, /const request_id=newConversionRequestId428\(\)/);
  assert.match(source, /savePendingConversion428\(project,aid,vid,\{request_id,payload,createdAt:Date\.now\(\)\}\)/);
  assert.match(source, /body:JSON\.stringify\(payload\)/);
  assert.match(source, /label:'转换任务创建',mutation:true/);
  assert.match(source, /if\(uncertain\)conversionUnknown428\.add\(submissionKey\)/);
});

test('uncertain conversion is queried by request identity and retry reuses frozen payload', () => {
  assert.match(source, /if\(conversionUnknown428\.has\(submissionKey\)\|\|pendingConversion428\(project,aid,vid\)\)/);
  assert.match(source, /\/deploy\/jobs\/by-request\/\$\{encodeURIComponent\(pending\.request_id\)\}/);
  assert.match(source, /window\.retryPendingConversion428=async function/);
  assert.match(source, /body:JSON\.stringify\(pending\.payload\)/);
  assert.match(source, /clearPendingConversion428\(project,aid,vid\)/);
});

// Exercise only the existing recovery functions with the original modal-owner contract.
import vm from 'node:vm';
function recoveryFixture(){
 const calls=[],warn={innerHTML:''},form={querySelector:()=>warn},layer={contains:node=>node===form,querySelector:()=>null},pending={request_id:'conv_original',payload:{request_id:'conv_original',source_id:'version::a::v',params:{precision:'fp32'}}};let active=layer,project='p',reply={found:true,job:{id:'job'}},resolve;
 const window={ModalContentRuntime:{captureOwner:()=>({layer:active,isCurrent:()=>active===layer}),activeLayer:()=>active},closeModalLayer424:closed=>{assert.equal(closed,layer);calls.push('close');active=null},openVersionConvert428:()=>calls.push('history'),PlatformCore:{withRequestDeadline:fn=>fn(new AbortController().signal)}};
 const context={window,state:{conv428SourceId:'version::a::v'},document:{querySelector:()=>form},pid:()=>project,pendingConversion428:()=>pending,clearPendingConversion428:()=>calls.push('clear'),conversionPending428:new Set(),esc:String,modal:()=>calls.push('modal'),toast:()=>{},api:async(_url,options)=>{calls.push(options?.method||'GET');return reply==='wait'?await new Promise(done=>resolve=done):reply}};
 vm.runInNewContext(source.slice(source.indexOf('  function conversionRecoveryOwner428'),source.indexOf('  window.submitConvert428=async function')),context);
 return {window,calls,warn,pending,setReply:value=>reply=value,replace:()=>active={},finish:value=>resolve(value)};
}
test('found conversion recovery releases its owned editor before history; notfound stays inline',async()=>{
 const h=recoveryFixture();h.setReply({found:false});await h.window.verifyPendingConversion428('a','v');assert.deepEqual(h.calls,['GET']);assert.match(h.warn.innerHTML,/retryPendingConversion428/);assert.match(h.warn.innerHTML,/再次核验/);
 h.setReply({found:true,job:{id:'job'}});await h.window.verifyPendingConversion428('a','v');assert.deepEqual(h.calls,['GET','GET','close','clear','history']);
});
test('a late recovery cannot close a newer modal and retry retains the frozen request',async()=>{
 const h=recoveryFixture();h.setReply('wait');const reading=h.window.verifyPendingConversion428('a','v');h.replace();h.finish({found:true,job:{id:'job'}});await reading;assert.deepEqual(h.calls,['GET']);
 const retry=recoveryFixture();await retry.window.retryPendingConversion428('a','v');assert.deepEqual(retry.calls,['POST','close','clear','history']);assert.equal(retry.pending.payload.request_id,'conv_original');
});
