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
  zipStartDisposition,
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
  assert.match(source,/window\.doUploadZip426=input=>upload\(input\)/);
  assert.match(source,/window\.doImportData=\(\)=>/);
  assert.match(source,/检测到外部标签后，必须先统一到平台标签再正式入库/);
  assert.doesNotMatch(source,/\/api\/v18\/projects/);
  assert.match(appSource,/window\.ZipImportRuntime\?\.upload/);
  assert.doesNotMatch(appSource,/\/api\/v18\/projects/);
});

test('import confirmation UI cannot create platform labels',()=>{
  const source=readFileSync(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
  const appSource=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  assert.doesNotMatch(source,/data-zip-create/);
  assert.doesNotMatch(source,/create_labels/);
  assert.match(source,/选择平台标签/);
  assert.doesNotMatch(appSource,/data-create-label/);
  assert.doesNotMatch(appSource,/body\.create_labels/);
});

