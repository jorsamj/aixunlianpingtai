import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/modules/resource-discovery.js', import.meta.url), 'utf8');

test('full discovery actions remain explicit user actions handled by the API', () => {
  assert.match(source, /deepDetectResourceEnvironment\s*=\s*\(\)\s*=>\s*runtime\.detectEnvironment\(\{scope:\s*'full'\}\)/);
  assert.match(source, /scanAllModels\s*=\s*\(\)\s*=>\s*runtime\.scanModels\(\{scope:\s*'full'\}\)/);
});

test('task detail renders durable frozen discovery roots and scope', () => {
  assert.match(source, /task\.discovery_scope/);
  assert.match(source, /task\.scan_roots/);
  assert.match(source, /实际扫描根目录（任务创建时已冻结/);
  assert.match(source, /全机（仅本地文件系统）/);
});

test('failed cancelled and permission states use actionable frontend copy', () => {
  assert.match(source, /function discoveryFailureMessage\(task\)/);
  assert.match(source, /网络盘和虚拟文件系统不会自动纳入扫描/);
  assert.match(source, /部分目录因权限不足已跳过/);
  assert.match(source, /taskStatus === 'CANCELLED'/);
  assert.doesNotMatch(source, /notify\(task\.error\?\.message \|\| task\.error \|\| '资源检测失败'\)/);
});

test('successful discovery keeps automatic cache refresh', () => {
  assert.match(source, /if \(SUCCESS_TASK_STATUSES\.has\(canonicalTaskStatus\(task\)\)\) \{\s*await refreshCache\(true\)/);
});


test('resource discovery durable task polling uses shared canonical runtime truth', () => {
  assert.match(source, /from '.\/task-runtime-truth\.js'/);
  assert.match(source, /canonicalTaskStatus\(task\)/);
  assert.match(source, /canonicalTaskPhase\(task\)/);
  assert.match(source, /isCanonicalTaskActive\(task\)/);
  assert.doesNotMatch(source, /ACTIVE_TASK_STATUSES/);
  assert.doesNotMatch(source, /ACTIVE_TASK_STATUSES\.has\(status\(task\.status\)\)/);
});


test('resource discovery polling is PollRegistry-owned and patches the live progress shell', () => {
  assert.match(source, /dependencies\.pollRegistry \|\| window\.PollRegistryRuntime/);
  assert.match(source, /registry\.startTimeout\(pollKey, '训练资源', tick, 1100\)/);
  assert.match(source, /export function patchResourceDiscoveryProgress/);
  assert.match(source, /data-rd-field="current_item"/);
  assert.doesNotMatch(source, /setTimeout\(/);
  assert.doesNotMatch(source, /live\.outerHTML\s*=/);
  assert.doesNotMatch(source, /while \(!controller\.signal\.aborted/);
});


test('selecting a different Ultralytics environment invalidates persisted training device inventory', () => {
  const selectStart = source.indexOf('window.selectResourceEnvironment = async index =>');
  const selectEnd = source.indexOf('window.resourceModelsPage = async direction =>', selectStart);
  assert.ok(selectStart >= 0 && selectEnd > selectStart);
  const block = source.slice(selectStart, selectEnd);
  assert.match(block, /\/api\/ultralytics_env\/select/);
  assert.match(block, /window\.invalidateTrainingDeviceCacheV3\?\.\(\)/);
});
