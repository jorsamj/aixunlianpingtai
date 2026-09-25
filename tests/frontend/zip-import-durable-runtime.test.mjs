import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  ACTIVE_ZIP_STATUSES,
  LEGACY_START_GRACE_MS,
  activeZipJobs,
  backendZipProgress,
  overallZipProgress,
  pickZipJob,
  zipQueueInfo,
  zipNeedsLabelConfirmation,
  zipLabelChoice,
  zipStartDisposition,
  isZipBootstrapReconcile,
  zipView,
} from '../../static/modules/zip-import-runtime.js';

const running={id:'job-a',status:'running',created_at:'2026-09-16T10:00:00Z',stage:'正在解压数据集',progress:31.4,message:'解压 3140/10000'};
const selecting={id:'job-b',status:'selecting',created_at:'2026-09-16T10:05:00Z',progress:0,message:'上传与ZIP校验完成，等待开始后台导入'};

test('refresh restoration picks server running job',()=>assert.equal(pickZipJob([selecting,running]).id,'job-a'));
test('second ZIP exposes explicit queue wait',()=>{const v=zipView(selecting,[selecting,running]);assert.equal(v.stage,'等待前序 ZIP 导入任务');assert.equal(v.queue.position,2);assert.match(v.message,/前面还有 1 个导入任务/)});
test('only queue head selecting job can start',()=>{const a={...selecting,id:'a',created_at:'2026-09-16T10:00:00Z'},b={...selecting,id:'b'};assert.equal(zipQueueInfo(a,[b,a]).canStart,true);assert.equal(zipQueueInfo(b,[b,a]).canStart,false)});
test('backend phase percent remains available but UI uses monotonic whole-pipeline percent',()=>{
  assert.equal(backendZipProgress(running),31.4);
  assert.equal(overallZipProgress({status:'uploading',upload_progress:50}),17.5);
  assert.equal(overallZipProgress({status:'merging'}),36);
  assert.equal(overallZipProgress({status:'validating'}),37);
  assert.equal(overallZipProgress(selecting),38);
  assert.equal(overallZipProgress(running),57.2);
  assert.equal(zipView(running,[running]).progress,57.2);
  assert.equal(overallZipProgress({status:'done',progress:100}),100);
});
test('new deferred upload waits behind running job then becomes startable',()=>{assert.equal(zipStartDisposition(selecting,[running,selecting],{intent:'deferred'}),'wait');assert.equal(zipStartDisposition(selecting,[selecting],{intent:'deferred'}),'start')});
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
  assert.match(source,/window\.doUploadZip426=input=>upload\(input\)/);
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
  assert.match(source,/if\(!isZipBootstrapReconcile\(reason\)\)server=await listZipJobs/);
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
  assert.match(source,/不自动选择、推荐或新增平台标签/);
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
