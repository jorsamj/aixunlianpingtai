import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const page=await readFile(new URL('../../frontend/src/app/ZipImport.vue',import.meta.url),'utf8');
const runtime=await readFile(new URL('../../static/modules/zip-import-runtime.js',import.meta.url),'utf8');
const adapter=await readFile(new URL('../../static/modules/uppy-zip-adapter.js',import.meta.url),'utf8');

test('native ZIP page no longer runs a second list poller next to the durable runtime',()=>{
  assert.doesNotMatch(page,/\/import\/jobs/,'the Vue page must not GET the v19 job list itself');
  assert.doesNotMatch(page,/from '\.\/http'/,'the Vue page now reads runtime state instead of issuing its own API calls');
  assert.match(page,/const MIRROR_INTERVAL_MS=1000, MAX_JOBS=50;/);
  assert.equal((page.match(/setInterval\(/g)||[]).length,1,'exactly one in-memory snapshot mirror timer');
  assert.match(page,/mirrorTimer=window\.setInterval\(syncJobs,MIRROR_INTERVAL_MS\)/);
  assert.doesNotMatch(page,/setInterval\([^)]*loadJobs/,'the mirror timer must not fetch the job list');
  // The runtime stays the only network/durable status owner for that upload task.
  assert.equal((runtime.match(/listZipJobs\(project/g)||[]).length>=1,true);
  assert.match(runtime,/pollOwner:'zip-import-runtime'/);
});

test('native ZIP mirror reads the single owner snapshot and explicit reconcile only',()=>{
  assert.match(page,/const snapshot=runtime\?\.snapshot\?\.\(\);/);
  assert.match(page,/jobs\.value=Array\.isArray\(snapshot\?\.jobs\)\?snapshot\.jobs\.slice\(0,MAX_JOBS\):\[\];/);
  assert.match(page,/async function loadJobs\(reason='native-page-refresh'\)/);
  assert.match(page,/await runtime\?\.reconcile\?\.\(reason\)/);
  assert.match(page,/finally\{syncJobs\(\)\}/);
  // A successful upload must not trigger an extra list read from the page.
  assert.match(page,/if\(event\.type==='success'\)\{transfer\.jobId=String\(event\.jobId\|\|''\);transfer\.phase='服务器已受理导入任务';syncJobs\(\)\}/);
  assert.equal((page.match(/loadJobs\(/g)||[]).length,4,'definition, mount bootstrap, legacy shim and manual refresh only');
});

test('native ZIP page cancels its polling and destroys its runtime on unmount',()=>{
  const unmount=page.slice(page.indexOf('onBeforeUnmount('));
  assert.match(unmount,/controller\.abort\(\);if\(mirrorTimer!==undefined\)\{window\.clearInterval\(mirrorTimer\);mirrorTimer=undefined\}/);
  assert.match(unmount,/handle\?\.destroy\(\);handle=null;/);
  assert.match(unmount,/runtime\?\.destroy\?\.\(\);runtime=null;/);
  assert.match(unmount,/restoreShims\(\);/);
});

test('Uppy chunked upload, resume and pause owners remain intact on the native page',()=>{
  assert.match(page,/mountUppyZipAdapter\(\{target:target\.value,runtime:runtime!/);
  assert.match(page,/await runtime\.pauseUpload\?\.\(transfer\.uploadId\)/);
  assert.match(page,/await runtime\.resumeTransfer\?\.\(file,transfer\.uploadId\)/);
  assert.match(page,/resumeFromFile\?\.\(input,String\(job\.upload_id\|\|job\.id\)\)/);
  assert.match(page,/await runtime\.cancelJob\?\.\(job\.id\);syncJobs\(\)/);
  assert.match(page,/const legacy=legacyUrl\(projectId,'数据集','','','material-zip'\);/);
  assert.match(page,/原 ZIP 上传入口/);
  // The original runtime/adapter contracts stay untouched.
  assert.match(adapter,/export async function mountUppyZipAdapter/);
  assert.match(runtime,/export async function uploadZipMultipartJob/);
  assert.match(runtime,/function resumeFromFile/);
});

test('ZIP jobs list re-renders from runtime snapshot fields including unknown verification',()=>{
  const job=page.match(/interface ZipJob \{([^}]*?)report\?:/)?.[1]??'';
  for(const field of ['id:string;','batch_id?:string;','file_name?:string;','status?:string;'])
    assert.ok(job.includes(field),`missing ZIP job snapshot field: ${field}`);
  assert.match(page,/const STATUS:Record<string,string>=\{uploading:'正在上传'.*unknown:'状态待核验'\}/);
  assert.match(page,/unknown:'状态待核验'/);
});
