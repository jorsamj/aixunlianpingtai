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
  zipPhaseDetail,
  zipLabelChoice,
  zipStartDisposition,
  isZipBootstrapReconcile,
  zipView,
} from '../../static/modules/zip-import-runtime.js';

const running={id:'job-a',status:'running',created_at:'2026-09-16T10:00:00Z',stage:'正在解压数据集',progress:54.28,message:'解压 3140/10000',zip_display_progress:{phase:'EXTRACT',phase_label:'解压导入范围',phase_progress:31.4,overall_progress:54.28,completed:3140,total:10000,unit:'files',eta_seconds:18}};
const selecting={id:'job-b',status:'selecting',created_at:'2026-09-16T10:05:00Z',progress:48,message:'上传与ZIP校验完成，等待开始后台导入',zip_display_progress:{phase:'READY',phase_label:'等待启动后台导入',phase_progress:100,overall_progress:48,completed:1,total:1,unit:'step',eta_seconds:null}};

test('refresh restoration picks server running job',()=>assert.equal(pickZipJob([selecting,running]).id,'job-a'));
test('second ZIP exposes explicit queue wait',()=>{const v=zipView(selecting,[selecting,running]);assert.equal(v.stage,'等待前序 ZIP 导入任务');assert.equal(v.queue.position,2);assert.match(v.message,/前面还有 1 个导入任务/)});
test('only queue head selecting job can start',()=>{const a={...selecting,id:'a',created_at:'2026-09-16T10:00:00Z'},b={...selecting,id:'b'};assert.equal(zipQueueInfo(a,[b,a]).canStart,true);assert.equal(zipQueueInfo(b,[b,a]).canStart,false)});
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
  assert.match(source,/英文编码一致时自动关联已有平台标签/);
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

test('ZIP exact label reuse and explicit source-code creation preserve manual confirmation',()=>{
 const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
 assert.match(source,/applyExactLabelCodeMatches\(review,labelItems\(\)\)/);
 assert.match(source,/async function useSourceLabel/);
 assert.match(source,/buildManualLabelMapping\(review\)/);
});

test('ZIP browser bootstrap loads the refreshed exact-code and side-evidence module',()=>{
 const boot=readFileSync(new URL('../../static/zip-import-bootstrap.mjs',import.meta.url),'utf8');
 assert.match(boot,/zip-import-runtime\.js\?v=4226353/);
});
