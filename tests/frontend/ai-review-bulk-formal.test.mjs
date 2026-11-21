import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = relative => readFileSync(resolve(root, relative), 'utf8');

const api = read('frontend/src/api/ai-review.ts');
const store = read('frontend/src/stores/ai-review.ts');
const page = read('frontend/src/app/AiReview.vue');

test('bulk formal API client uses the existing C2-B routes and no client-side GT write', () => {
  for (const name of ['sealBulkFormalIntent', 'getBulkFormalIntent', 'startBulkFormalExecution',
    'getBulkFormalExecution', 'cancelBulkFormalExecution', 'recoverBulkFormalExecution']) {
    assert.match(api, new RegExp(`export function ${name}\\(`), name);
  }
  assert.match(api, /bulk-formal\/intents/);
  assert.match(api, /\/execution\/cancel/);
  assert.match(api, /\/execution\/recover/);
  // The browser only sends an immutable server snapshot reference plus exclusions.
  assert.match(api, /selection_id:string;review_revision:number;excluded_image_ids:string\[\]/);
  assert.doesNotMatch(api.slice(api.indexOf('BulkFormalSeal')), /[^_]image_ids:string\[\]/);
});

test('store seals the frozen selection once and never expands IDs', () => {
  assert.match(store, /sealBulkFormalIntent\(address,body/);
  assert.match(store, /excluded_image_ids:\[\.\.\.excludedIds\.value\]\.sort\(\)/);
  assert.match(store, /bulkRequestId\.value\|\|newBulkRequestId\(\)/);
  assert.match(store, /Math\.random\(\)\*16/);
  assert.match(store, /startBulkFormalExecution\(address,bulkRequestId\.value/);
  assert.match(store, /view\.operation_id!==bulkIntent\.value\?\.operation_id/);
  // No expanded id list can reach the bulk payload.
  const seal = store.slice(store.indexOf('async function preflightBulkFormal'), store.indexOf('async function confirmBulkFormal'));
  assert.doesNotMatch(seal, /[^_]image_ids\s*:/);
  const writeAt=store.indexOf('writeBulkRecord(address,body);');
  const sealAt=store.indexOf('sealBulkFormalIntent(address,body');
  assert.ok(writeAt>0&&sealAt>writeAt,'request identity is persisted before the seal request');
  assert.match(store, /bulkPendingUnknown/);
  assert.match(store, /function abandonBulkFormal\(/);
});

test('store keeps honest progress and recovery semantics', () => {
  assert.match(store, /view\.blocked&&view\.manual_review_required/);
  assert.match(store, /stopBulkPoll\(\)/);
  assert.match(store, /recoverBulkFormalExecution\(address,bulkRequestId\.value/);
  assert.match(store, /cancelBulkFormalExecution\(address,bulkRequestId\.value/);
});

test('native page distinguishes preflight, execution, proven GT and manual review', () => {
  assert.match(page, /预检并封存/);
  assert.match(page, /确认创建后台任务/);
  assert.match(page, /已证明提交 GT/);
  assert.match(page, /未证明/);
  assert.match(page, /需要人工核验后恢复/);
  assert.match(page, /取消后台任务/);
  // Original explicit <=100 flow and single-image review remain wired.
  assert.match(page, /review\.prepareFormal\(\)/);
  assert.match(page, /review\.confirmFormal\(\)/);
  assert.match(page, /采用候选/);
  assert.match(page, /拒绝候选/);
  assert.match(page, /编辑候选/);
});

test('bulk execution disables selection drift while a task is running', () => {
  assert.match(store, /formalLocked=computed\(\(\)=>.*bulkRunning\.value/);
});
