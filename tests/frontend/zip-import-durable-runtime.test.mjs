import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installZipImportRuntime} from '../../static/modules/zip-import-runtime.js';

test('destroy during pending ZIP reconciliation prevents late task-center and dock effects',async()=>{
  const previous={window:globalThis.window,document:globalThis.document};
  let respond,upserts=0,dockCreates=0,completionEffects=0;
  const state={project:{id:'p1'},page:'数据集'};
  globalThis.document={getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[],createElement:()=>{dockCreates++;return {style:{},dataset:{},classList:{add(){}},appendChild(){}}},body:{appendChild(){}}};
  globalThis.window={UploadTaskCenterRuntime:{upsert(){upserts++}},PollRegistryRuntime:{clear(){},startTimeout(){}},completeZipImportReview412(){completionEffects++}};
  try{
    const runtime=installZipImportRuntime({getState:()=>state,projectId:()=> 'p1',fetchImpl:async()=>new Promise(resolve=>{respond=resolve})});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(typeof respond,'function');
    runtime.destroy();
    respond(Response.json({items:[{id:'late-job',status:'running',progress:23,file_name:'late.zip'}]}));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(upserts,0);assert.equal(dockCreates,0);assert.equal(completionEffects,0);
    assert.equal(state.import411,undefined);assert.deepEqual(runtime.snapshot().jobs,[]);
  }finally{Object.assign(globalThis,previous)}
});
import {
  ACTIVE_ZIP_STATUSES,
  LEGACY_START_GRACE_MS,
  activeZipJobs,
  mapZipUploadsConcurrent,
  createZipTransferLimiter,
  backendZipProgress,
  overallZipProgress,
  pickZipJob,
  zipQueueInfo,
  zipNeedsLabelConfirmation,
  zipPhaseDetail,
  zipLabelChoice,
  zipStartDisposition,
  isZipBootstrapReconcile,
  zipView,
} from '../../static/modules/zip-import-runtime.js';

const running={id:'job-a',status:'running',created_at:'2026-09-16T10:00:00Z',stage:'正在解压数据集',progress:54.28,message:'解压 3140/10000',zip_display_progress:{phase:'EXTRACT',phase_label:'解压导入范围',phase_progress:31.4,overall_progress:54.28,completed:3140,total:10000,unit:'files',eta_seconds:18}};
const selecting={id:'job-b',status:'selecting',created_at:'2026-09-16T10:05:00Z',progress:48,message:'上传与ZIP校验完成，等待开始后台导入',zip_display_progress:{phase:'READY',phase_label:'等待启动后台导入',phase_progress:100,overall_progress:48,completed:1,total:1,unit:'step',eta_seconds:null}};

test('refresh restoration picks server running job',()=>assert.equal(pickZipJob([selecting,running]).id,'job-a'));
test('server-accepted ZIP exposes server-owned FIFO position',()=>{const second={...running,phase:'QUEUE',queue_position:2};const v=zipView(second,[selecting,second]);assert.equal(v.stage,'等待项目正式导入队列');assert.equal(v.queue.position,2);assert.match(v.message,/前面还有 1 个任务/)});
test('unconfirmed ZIP does not block later ready ZIP',()=>{const blocked={...selecting,label_confirmation_required:true,external_classes:[{class_id:'0',name:'class_0'}]},ready={...selecting,id:'ready'};assert.equal(zipQueueInfo(blocked,[blocked,ready]).canStart,false);assert.equal(zipQueueInfo(ready,[blocked,ready]).canStart,true);assert.equal(zipQueueInfo(ready,[blocked,ready]).position,null)});
test('server projection owns ZIP phase and overall progress',()=>{
  assert.equal(backendZipProgress(running),54.28);
  assert.equal(overallZipProgress(selecting),48);
  assert.equal(overallZipProgress(running),54.28);
  const view=zipView(running,[running]);
  assert.equal(view.progress,54.28);
  assert.equal(view.stage,'解压导入范围');
  assert.equal(zipPhaseDetail(running).phaseProgress,31.4);
  assert.equal(zipPhaseDetail(selecting).etaSeconds,null);
  assert.equal(overallZipProgress({status:'done',progress:100}),100);
});
test('two ready uploads can both enter authoritative backend FIFO',()=>{assert.equal(zipStartDisposition(selecting,[running,selecting],{intent:'deferred'}),'start');assert.equal(zipStartDisposition(selecting,[selecting],{intent:'deferred'}),'start')});
test('legacy selecting job gets grace window before recovery start',()=>{assert.equal(zipStartDisposition(selecting,[selecting],{eligibleForMs:LEGACY_START_GRACE_MS-1}),'confirm');assert.equal(zipStartDisposition(selecting,[selecting],{eligibleForMs:LEGACY_START_GRACE_MS}),'start-legacy-recovery')});
test('submitted start is observed rather than posted twice',()=>assert.equal(zipStartDisposition(selecting,[selecting],{intent:'submitted',eligibleForMs:99999}),'observe'));
test('terminal jobs are not active',()=>{const done={id:'d',status:'done'};assert.deepEqual(activeZipJobs([done]),[]);assert.equal(ACTIVE_ZIP_STATUSES.has('done'),false)});

test('annotated ZIP blocks auto-start until label mapping is explicitly confirmed',()=>{
  const job={...selecting,label_confirmation_required:true,external_classes:[
    {class_id:'0',name:'toukui1',box_count:12,image_count:8},
    {class_id:'1',name:'toukui2',box_count:9,image_count:6},
  ]};
  assert.equal(zipNeedsLabelConfirmation(job),true);
  assert.equal(zipStartDisposition(job,[job],{intent:'deferred'}),'confirm-labels');
  const view=zipView(job,[job]);
  assert.equal(view.stage,'等待确认标注');
  assert.match(view.message,/2 个外部标签/);
});

test('all browser ZIP entry points are owned by the durable v19 runtime',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const appSource=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const bootstrap=readFileSync(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8');
  assert.match(source,/window\.doUploadZip426=input=>uploadBatch\(input\)/);
  assert.match(source,/window\.doImportData=\(\)=>/);
  assert.equal(source.includes('classicImportData'),false);
  assert.doesNotMatch(source,/window\.importData\s*=/);
  assert.match(source,/window\.doImportData=\(\)=>/);
  assert.match(appSource,/window\.importData=function\(\)/);
  assert.match(appSource,/导入素材 \/ 标注/);
  assert.match(source,/function forgetTerminal\(\)/);
  assert.match(source,/knownJobs\.delete\(id\)/);
  assert.match(source,/请统一到平台标签后再入库/);
  assert.doesNotMatch(source,/\/api\/v18\/projects/);
  assert.match(appSource,/onclick="doImportUploadV19\(\)">开始导入/);
  assert.match(bootstrap,/const durableUploadFromImportModal = \(\) =>/);
  assert.match(bootstrap,/window\.doImportUploadV19 = durableUploadFromImportModal/);
  assert.doesNotMatch(appSource,/\/api\/v18\/projects/);
});

test('ZIP review allows explicit canonical label creation without implicit create_labels payload',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const appSource=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  assert.doesNotMatch(source,/data-zip-create/);
  assert.doesNotMatch(source,/create_labels/);
  assert.match(source,/选择平台标签/);
  assert.match(source,/openInlineLabelCreate414\?\.\('zip'/);
  assert.match(appSource,/window\.openInlineLabelCreate414=function/);
  assert.match(appSource,/window\.submitInlineLabelCreate414=async function/);
  assert.match(appSource,/\/api\/projects\/\$\{pid\(\)\}\/labels/);
  assert.doesNotMatch(appSource,/body\.create_labels/);
});



test('ZIP progress bars use transform updates instead of layout-driving width updates',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const styles=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
  assert.match(source,/function setZipProgressBar\(node,value\)/);
  assert.match(source,/node\.style\.transform=/);
  assert.match(source,/data-progress=/);
  assert.doesNotMatch(source,/bar\.style\.width=/);
  assert.doesNotMatch(source,/zipDurableBar" style="width:/);
  assert.match(styles,/\.up411-bar>i,\.zip411-progress>i>em\{width:100%;transform-origin:left center/);
});


test('ZIP bootstrap-ready is the same single-read bootstrap phase',()=>{
  assert.equal(isZipBootstrapReconcile('bootstrap'),true);
  assert.equal(isZipBootstrapReconcile('bootstrap-ready'),true);
  assert.equal(isZipBootstrapReconcile('poll'),false);
  assert.equal(isZipBootstrapReconcile('manual'),false);
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/if\(!isZipBootstrapReconcile\(reason\)&&startedNow\)\{server=await listZipJobs/);
  assert.doesNotMatch(source,/if\(reason!=='bootstrap'\)server=await listZipJobs/);
});

test('ZIP bootstrap recovery follows canonical startup readiness instead of a fixed delay',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/const initialProject=pid\(\)/);
  assert.match(source,/if\(!initialProject&&window\.__v53InitPromise\)/);
  assert.match(source,/Promise\.resolve\(window\.__v53InitPromise\)\.then\(\(\)=>reconcile\('bootstrap-ready'\)\)/);
  assert.doesNotMatch(source,/setTimeout\(\(\)=>reconcile\('bootstrap-retry'/);
});


test('ZIP label confirmation never preselects, recommends, or implicitly creates labels',()=>{
  const labels=[
    {code:'helmet',display_name:'安全帽',status:'active'},
    {code:'person',display_name:'人员',status:'active'},
  ];
  assert.deepEqual(zipLabelChoice({class_id:'0',name:'helmet'},labels),{mode:'unresolved',code:'',source:'helmet'});
  assert.deepEqual(zipLabelChoice({class_id:'1',name:'smoke'},labels),{mode:'unresolved',code:'',source:'smoke'});
  assert.deepEqual(zipLabelChoice({class_id:'2',name:'安全帽'},labels),{mode:'unresolved',code:'',source:'安全帽'});
  assert.deepEqual(zipLabelChoice({class_id:'3',name:'old_helmet',target_label_code:'helmet'},labels),{mode:'unresolved',code:'',source:'old_helmet'});
});

test('ZIP runtime exposes recoverable reopen and visible confirmation state',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/一键使用原始标签/);
  assert.match(source,/applyExactLabelCodeMatches\(review,labelItems\(\)\)/);
  assert.match(source,/buildManualLabelMapping\(review\)/);
  assert.doesNotMatch(source,/自动匹配/);
  assert.doesNotMatch(source,/__create__/);
  assert.match(source,/data-zip-confirm-button/);
  assert.match(source,/button\.textContent='正在确认…'/);
  assert.match(source,/async function openTask\(taskId\)/);
  assert.match(source,/openTask,confirmLabels/);
  assert.match(source,/labelMappingReviewPage/);
  assert.match(source,/buildManualLabelMapping/);
  assert.match(source,/bulkMapLabels/);
  assert.doesNotMatch(source,/create_labels/);
});

test('canonical ZIP projection owns stage message percent and ETA for new jobs',()=>{
  const job={
    id:'canonical',
    status:'running',
    stage:'legacy stage',
    message:'legacy message',
    progress:7,
    zip_display_progress:{
      phase:'ANNOTATION_PARSE',
      phase_label:'解析图片与标注',
      phase_progress:40,
      overall_progress:79.2,
      completed:400,
      total:1000,
      unit:'images',
      eta_seconds:21,
      message:'正在解析 400/1000',
    },
  };
  const view=zipView(job,[job]);
  assert.equal(view.progress,79.2);
  assert.equal(view.stage,'解析图片与标注');
  assert.equal(view.message,'正在解析 400/1000');
  assert.equal(zipPhaseDetail(job).text,'阶段 40% · 400 / 1000 图片 · 预计剩余 21 秒');
});

test('ZIP runtime renders server phase counter and ETA instead of inventing another phase percent',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/zip_display_progress/);
  assert.match(source,/zipDurablePhaseMeta/);
  assert.match(source,/zipPhaseDetail\(job\)/);
  assert.match(source,/overall_progress/);
});

test('ZIP class mapping review uses the single shared numeric pagination presentation',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/data-zip-label-pagination/);
  assert.match(source,/pagination\?\.mountPagination\?\./);
  assert.match(source,/onPageChange:nextPage=>setReviewPage/);
  assert.match(source,/onPageSizeChange:size=>/);
  assert.doesNotMatch(source,/class="row between label-mapping-review-pager"><button/);
  assert.match(source,/mountLabelReviewPagination\(current\.id\)/);
});


test('restored ZIP completion cannot auto-open stale import-cleaning decision',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/if\(!foregroundImports\.has\(id\)\|\|completionEffects\.has\(id\)\)return/);
  assert.match(source,/foregroundImports\.add\(String\(provisional\.id\)\)/);
  assert.match(source,/foregroundImports\.add\(id\);started\.add\(id\)/);
});

test('ZIP source label selection only stages an explicit mapping until final confirmation',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/applyExactLabelCodeMatches\(review,labelItems\(\)\)/);
  const start=source.indexOf('function useSourceLabel(jobId,classId)');
  const end=source.indexOf('function previewOriginalLabels(jobId)',start);
  assert.ok(start>=0 && end>start,'source label handler exists');
  const selection=source.slice(start,end);
  assert.match(selection,/setLabelMapping\(review,classId,existing\?\.code\|\|source\)/);
  assert.match(selection,/review\.pendingCreate\[String\(classId\)\]=source/);
  assert.doesNotMatch(selection,/createPlatformLabel\(/,'selection cannot persist new labels');
  assert.doesNotMatch(selection,/startZipJob\(/,'selection cannot start import');

  const confirmStart=source.indexOf('async function confirmLabels(jobId)');
  const confirmEnd=source.indexOf('async function maybeStart(project)',confirmStart);
  assert.ok(confirmStart>=0 && confirmEnd>confirmStart,'canonical import confirmation exists');
  const confirmation=source.slice(confirmStart,confirmEnd);
  assert.match(confirmation,/buildManualLabelMapping\(review\)/);
  const create=confirmation.indexOf('await createPlatformLabel(project,code,name)');
  const verify=confirmation.indexOf('verified.has(String(code))');
  const submit=confirmation.indexOf('await startZipJob(project,id,{fetchImpl,confirmation:{label_mapping}})');
  assert.ok(create>=0 && create<verify && verify<submit,'new labels must be created and verified before import admission');
});

test('ZIP browser bootstrap loads the refreshed exact-code and side-evidence module',()=>{
 const boot=readFileSync(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8');
 assert.match(boot,/zip-import-runtime\.js\?v=4226366/);
});


test('ZIP original label callbacks escape archive-supplied names as JS arguments and reject placeholder labels',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(source,/const jsArg = value => esc\(JSON\.stringify\(/);
  assert.match(source,/showLabelSamples\(\$\{jsArg\(id\)\},\$\{jsArg\(row\.classId\)\},\$\{jsArg\(encodeURIComponent\(source\)\)\}\)/);
  assert.match(source,/\^\(\?:class\|label\)/);
  assert.doesNotMatch(source,/button\.textContent='确认标签并开始导入'/);
});

test('ZIP multi-file transfer overlaps and does not cancel independent files on failure',async()=>{
  let active=0,peak=0;
  const waiting=[];
  const task=mapZipUploadsConcurrent(['a','b','c'],async name=>{
    active++;peak=Math.max(peak,active);
    await new Promise(resolve=>waiting.push({name,resolve}));
    active--;
    if(name==='b')throw Error('network b');
    return name;
  },2);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(waiting.map(x=>x.name),['a','b']);
  waiting.find(x=>x.name==='b').resolve();
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(waiting.some(x=>x.name==='c'));
  waiting.find(x=>x.name==='a').resolve();
  await new Promise(resolve=>setImmediate(resolve));
  waiting.find(x=>x.name==='c').resolve();
  const outcomes=await task;
  assert.equal(peak,2);
  assert.deepEqual(outcomes.map(x=>x.status),['fulfilled','rejected','fulfilled']);
  assert.equal(outcomes[2].value,'c');
});

test('ZIP modal shows selected task only and batch upload uses independent controls',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.doesNotMatch(source,/zipBatchQueueList/);
  assert.doesNotMatch(source,/function queueRowsMarkup/);
  assert.match(source,/batchTransfers\.set\(id,control\)/);
  assert.match(source,/await mapZipUploadsConcurrent\(validEntries/);
  assert.match(source,/const session=await createZipUploadSession\(project,file/);
  assert.match(source,/let selectionMounted=false/);
  assert.match(source,/releaseSlot\(\)/);
  assert.match(source,/zipNeedsLabelConfirmation\(row\)/);
});

test('ZIP batch intake registers every selected file before hashing or transfer slots',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const uploadBatch=source.slice(source.indexOf('async function uploadBatch('),source.indexOf('function forgetTerminal('));
  const register=uploadBatch.indexOf('registerQueuedUpload');
  const fingerprints=uploadBatch.indexOf('fingerprintPromises');
  const transfer=uploadBatch.indexOf('withBatchSlot');
  assert.ok(register>=0&&register<fingerprints&&fingerprints<transfer);
  assert.match(source,/status:'WAITING_UPLOAD'/);
  assert.match(source,/localOnly:true/);
  assert.match(source,/function refreshQueuedUploadPositions/);
  assert.match(source,/function cancelQueuedUpload/);
});

test('ZIP public upload entry points do not silently swallow intake failures',()=>{
  const runtime=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const bootstrap=readFileSync(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8');
  const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  assert.doesNotMatch(runtime,/uploadBatch\(input\)\.catch\(\(\)=>/);
  assert.doesNotMatch(bootstrap,/runtime\.uploadBatch\(input\)\.catch\(\(\) => null\)/);
  assert.doesNotMatch(app,/ZipImportRuntime\.uploadBatch\(input\)\.catch\(\(\)=>null\)/);
});

test('ZIP chooser accepts multiple files and invalid selections stay per-file visible',()=>{
  const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const runtime=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  assert.match(app,/id="importFile"[^>]*accept="\.zip"[^>]*multiple/);
  assert.match(runtime,/failLocalUpload\(entry,'仅支持 ZIP 压缩包'\)/);
  assert.doesNotMatch(runtime,/files\.some\(file=>!\/\\\.zip/);
});

test('network upload slot is released before scan or label confirmation finishes',async()=>{
  const withSlot=createZipTransferLimiter(2);
  let finishScan;
  const waitingForLabel=new Promise(resolve=>{finishScan=resolve});
  const events=[];
  const tasks=['dog','cat','helmet'].map(name=>withSlot(async releaseNetworkSlot=>{
    events.push(name+':upload');
    releaseNetworkSlot();
    await waitingForLabel;
    events.push(name+':review-finished');
  }));
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(events,['dog:upload','cat:upload','helmet:upload']);
  finishScan();
  await Promise.all(tasks);
  assert.equal(events.filter(x=>x.endsWith(':review-finished')).length,3);
});

test('an individual session failure releases a slot without aborting sibling ZIPs',async()=>{
  const withSlot=createZipTransferLimiter(1);
  const result=await Promise.allSettled([
    withSlot(async()=>{throw new Error('first session denied')}),
    withSlot(async()=> 'second ZIP accepted'),
  ]);
  assert.deepEqual(result.map(x=>x.status),['rejected','fulfilled']);
  assert.equal(result[1].value,'second ZIP accepted');
});

test('ZIP label mapping is editable immediately and creates labels only upon final import confirmation',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const css=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
  assert.match(source,/review\.pendingCreate=Object\.fromEntries/);
  assert.match(source,/for\(const item of \[\.\.\.plan\.reuse,\.\.\.plan\.create\]\)setLabelMapping/);
  assert.match(source,/for\(const \[code,name\] of toCreate\)\{[\s\S]*?await createPlatformLabel\(project,code,name\)/);
  assert.match(source,/await startZipJob\(project,id,\{fetchImpl,confirmation:\{label_mapping\}\}\)/);
  assert.match(source,/submittingLabelJobs\.has\(id\)/);
  assert.doesNotMatch(source,/if\(codes\.length&&!window\.confirm/);
  assert.match(css,/\.zip-label-confirm \.zip-label-target-select\{display:block/);
  assert.match(source,/restoreImportModal\(\)/);
  assert.match(source,/UploadTaskCenterRuntime\?\.rekey\?\./);
});
