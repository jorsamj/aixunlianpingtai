import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('deployment conversion UI keeps queued and waiting-resource tasks live and visible', () => {
  assert.match(source, /queued:'排队中'/);
  assert.match(source, /waiting_resource:'等待资源'/);
  assert.match(source, /\['queued','waiting_resource','running'\]\.includes\(j\.status\)/);
  assert.match(source, /\['queued','waiting_resource'\]\.includes\(j\.status\)/);
  assert.match(source, /资源队列第 \$\{Number\(j\.resource_queue_position\|\|0\)\|\|'-'\} 位/);
  assert.match(source, /j\.status==='waiting_resource'&&j\.resource_wait_reason/);
  assert.match(source, /j\.worker_id\?` · Worker/);
});


test('version conversion progress is keyed and patches live rows in place', () => {
  const start = source.indexOf('function historyHtml428(aid,vid,r)');
  const end = source.indexOf('\n  function scheduleVersionConversionPoll428', start);
  assert.ok(start >= 0 && end > start);
  const finalLayer = source.slice(start, end);
  assert.match(finalLayer, /data-conversion-job-id=/);
  assert.match(finalLayer, /data-conversion-progress data-progress=/);
  assert.match(finalLayer, /function patchVersionConversionLive428\(aid,vid,r\)/);
  assert.match(finalLayer, /card\.dataset\.conversionStatus=next/);
  assert.match(finalLayer, /bar\.dataset\.progress=progress\.toFixed\(2\)/);
  assert.doesNotMatch(finalLayer, /deployJobList/);
});


test('version conversion polling is PollRegistry-owned and scoped to the current page', () => {
  const start = source.indexOf('function scheduleVersionConversionPoll428(aid,vid,r)');
  const end = source.indexOf('\n  window.openVersionConvert428=', start);
  assert.ok(start >= 0 && end > start);
  const finalPoll = source.slice(start, end);
  assert.match(finalPoll, /const registry=window\.PollRegistryRuntime/);
  assert.match(finalPoll, /registry\.startTimeout\(key,String\(state\.page\|\|'算法列表'\)/);
  assert.match(finalPoll, /registry\?\.clear\?\.\(key\)/);
  assert.match(finalPoll, /versionConversionRoot428\(aid,vid\)/);
  assert.doesNotMatch(finalPoll, /setTimeout\(/);
});


test('version conversion keeps chip choice capability-owned and submit returns to the existing history dialog', () => {
  const createStart = source.indexOf('window.openNewConvertCore416=async function');
  const createEnd = source.indexOf('window.installUsability417?.();', createStart);
  assert.ok(createStart >= 0 && createEnd > createStart);
  const createLayer = source.slice(createStart, createEnd);
  assert.match(createLayer, /<select id="conv428Chip" class="select"><\/select>/);
  assert.match(source, /state\.conv428Catalog\?\.chips/);
  assert.match(source, /deploy\/resolve/);
  assert.doesNotMatch(source, /rockchipOrder428/);
  assert.doesNotMatch(source, /RK3578/i);
  assert.match(source, /平台不会让用户手工猜型号/);

  const submitStart = source.indexOf('window.submitConvert428=async function');
  const submitEnd = source.indexOf('// ---------------------- training creation from algorithm', submitStart);
  assert.ok(submitStart >= 0 && submitEnd > submitStart);
  const submitLayer = source.slice(submitStart, submitEnd);
  assert.match(submitLayer, /replaceVersionConversionBody428\(aid,vid,r\)/);
  assert.match(submitLayer, /if\(!replaceVersionConversionBody428\(aid,vid,r\)\)modal\('版本转换',historyHtml428\(aid,vid,r\),true\)/);
  assert.match(submitLayer, /正在创建转换任务/);
});


test('version conversion only offers delete for terminal records without deliverable artifacts', () => {
  const start = source.indexOf('function conversionActions428(job)');
  const end = source.indexOf('\n  function rememberVersionConversion428', start);
  assert.ok(start >= 0 && end > start);
  const actions = source.slice(start, end);
  assert.match(actions, /deletable=\['failed','stopped','cancelled','blocked_by_environment'\]\.includes\(status\)/);
  assert.match(actions, /deletable\?`<button class="btn mini danger" onclick="deleteDeployJob/);
  assert.doesNotMatch(actions, /!active\?`<button class="btn mini danger" onclick="deleteDeployJob/);
});


test('conversion submit freezes current fields before revalidation and ignores stale resolved values',async()=>{
  const start=source.indexOf('  const conversionUnknown428=');
  const end=source.indexOf('// ---------------------- training creation from algorithm',start);
  const fields={conv428Resource:{value:'r'},conv428Precision:{value:'fp32'},conv428Chip:{value:'bm1684x'},
    conv428Width:{value:'384'},conv428Height:{value:'640'},conv428InputColor:{value:'bgr'},
    conv428Mean:{value:'1,2,3'},conv428Scale:{value:'0.1,0.2,0.3'},conv428Letterbox:{checked:false}};
  const radio={value:'sophon',dataset:{vendorId:'sophon'}},form={dataset:{}},button={disabled:false,setAttribute(){},removeAttribute(){}};
  const state={conv428ResourcesCurrent:true,conv428Resolved:{ready:true,params:{precision:'fp16',input_width:800,input_height:800,preprocessing:{pixel_format:'rgb'}}},conv428AdvancedValues:{}};
  const writes=[];let revalidate;
  const ctx={state,document:{getElementById:id=>fields[id],querySelector:s=>s.includes('conv428Target')?radio:s==='.convert428-create'?form:button},
    pid:()=> 'p',toast:()=>{},deployResources428:()=>new Promise(r=>revalidate=r),
    api:async(u,o)=>writes.push(JSON.parse(o.body)),localStorage:{removeItem(){}},cacheKey428:()=>'',closeModal(){},
    rememberVersionConversion428:()=>({}),deploymentHistory428:async()=>({}),replaceVersionConversionBody428:()=>true,scheduleVersionConversionPoll428(){}};
  ctx.PlatformCore={withRequestDeadline:operation=>Promise.resolve().then(()=>operation(new AbortController().signal))};ctx.window=ctx;ctx.event={currentTarget:button};vm.runInNewContext(source.split('\n').find(line=>line.includes('window.conversionCscRequest428=function'))+'\n'+source.slice(start,end),ctx);
  const pending=ctx.submitConvert428('a','v');
  await ctx.submitConvert428('a','v');
  state.conv428Resolved={ready:true,params:{precision:'fp16',input_width:800,input_height:800}};
  await Promise.resolve();revalidate({items:[{id:'r',status:'ready',targets:['sophon']}]});await pending;
  assert.equal(writes.length,1);assert.equal(writes[0].params.precision,'fp32');
  assert.equal(writes[0].params.input_width,384);assert.equal(writes[0].params.input_height,640);
  assert.equal(writes[0].params.input_color_order,'bgr');assert.equal(writes[0].params.source_color_order,'rgb');
  assert.equal(writes[0].params.preprocessing.pixel_format,'bgr');assert.equal(writes[0].params.preprocessing.letterbox,false);
});


test('late conversion history cannot close or replace a newer dialog after successful creation',async()=>{
  const start=source.indexOf('  const conversionUnknown428='),end=source.indexOf('// ---------------------- training creation from algorithm',start);
  let form={dataset:{}},finish,historyRequested;
  const waiting=new Promise(r=>historyRequested=r),fields={conv428Resource:{value:'r'},conv428Chip:{value:''},conv428Precision:{value:'fp32'}};
  const radio={value:'onnx'},button={disabled:false,setAttribute(){},removeAttribute(){}},events=[];
  const ctx={state:{conv428ResourcesCurrent:true},document:{getElementById:id=>fields[id],querySelector:s=>s.includes('conv428Target')?radio:s==='.convert428-create'?form:button},pid:()=> 'p',
    deployResources428:async()=>({items:[{id:'r',status:'ready',targets:['onnx']}]}),api:async()=>{},
    deploymentHistory428:()=>{historyRequested();return new Promise(r=>finish=r)},
    closeModal:()=>events.push('close'),rememberVersionConversion428:()=>events.push('remember'),toast:()=>{},localStorage:{removeItem(){}},cacheKey428:()=>''};
  ctx.PlatformCore={withRequestDeadline:operation=>Promise.resolve().then(()=>operation(new AbortController().signal))};ctx.window=ctx;vm.runInNewContext(source.split('\n').find(line=>line.includes('window.conversionCscRequest428=function'))+'\n'+source.slice(start,end),ctx);
  const pending=ctx.submitConvert428('a','v');await waiting;
  form={dataset:{}};finish({items:[]});await pending;
  assert.deepEqual(events,[]);
});


test('history loader sends bounded server filters and separates query cache/inflight identity',async()=>{
 const start=source.indexOf('  async function deploymentHistory428('),end=source.indexOf('  async function deployResources428(',start),calls=[];
 const ctx={URLSearchParams,pid:()=> 'project-a',cacheKey428:(...args)=>args.join(':'),readCache428:()=>null,writeCache428:()=>{},conversionHistoryInflight428:new Map(),api:async(url)=>{calls.push(url);return {items:[],total:41,page:2,page_size:20}}};
 ctx.window={PlatformCore:{withRequestDeadline:fn=>fn(new AbortController().signal)}};
 vm.runInNewContext(source.slice(start,end)+'\nglobalThis.load=deploymentHistory428;',ctx);
 await ctx.load('a','v',true,{page:2,page_size:20,target:'sophon',chip:'bm1688',precision:'fp16',csc:'bt709_full',created_from:'2026-10-01'});
 const query=new URL(calls[0],'http://fixture').searchParams;assert.equal(query.get('page_size'),'20');assert.equal(query.get('page'),'2');assert.equal(query.get('force'),'true');assert.equal(query.get('target'),'sophon');assert.equal(query.get('csc'),'bt709_full');assert.equal(query.get('created_from'),'2026-10-01');
});
