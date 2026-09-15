import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('algorithm list renders the durable current version instead of assuming versions[0]', () => {
  const start = app.lastIndexOf('function verRow412(a,v)');
  const end = app.indexOf('window.renderAlgorithms423=function()', start);
  assert.ok(start >= 0 && end > start);
  const source = app.slice(start, end);
  assert.match(source, /current_version_id/);
  assert.match(source, /当前版本/);
  assert.match(source, /回退到此版本/);
  assert.equal(source.includes('latest=vs[0]'), false);
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
