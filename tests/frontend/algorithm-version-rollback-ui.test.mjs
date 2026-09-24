import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const algorithmList = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');

test('algorithm list renders the durable current version instead of assuming versions[0]', () => {
  assert.match(algorithmList, /function currentVersion\(algorithm = \{\}\)/);
  assert.match(algorithmList, /versions\.find\(row => String\(row\.id \|\| ''\) === String\(algorithm\.current_version_id \|\| ''\)\) \|\| versions\[0\] \|\| null/);
  assert.match(algorithmList, /const current = String\(algorithm\.current_version_id \|\| ''\) === String\(version\.id \|\| ''\)/);
  assert.match(algorithmList, /当前版本/);
  assert.match(algorithmList, /openVersionRollback/);
  assert.equal(algorithmList.includes('latest=vs[0]'), false);
});

test('rollback confirmation uses the existing algorithm list owner and optimistic current pointer', () => {
  assert.match(app, /window\.openVersionRollback=/);
  assert.match(app, /window\.submitVersionRollback=/);
  assert.match(app, /versions\/\$\{targetVersionId\}\/rollback/);
  assert.match(app, /expected_current_version_id:currentVersionId/);
  assert.match(app, /delete_current_version:/);
  assert.match(app, /AlgorithmListRuntime/);
});

test('historical version delete reports physical cleanup truth', () => {
  const start = app.indexOf('window.delVersion=');
  const end = app.indexOf('window.openVersionRollback=', start);
  assert.ok(start >= 0 && end > start);
  const source = app.slice(start, end);
  assert.match(source, /cleanup_status==='cleanup_completed'/);
  assert.match(source, /部分物理产物清理失败/);
});
