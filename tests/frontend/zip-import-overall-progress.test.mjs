import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function extractProgressMapper() {
  const match = source.match(/function mapImportProcessingProgress411\(progress\)\{([^}]*)\}/);
  assert.ok(match, 'ZIP import must define a processing-to-overall progress mapper');
  return new Function('progress', match[1]);
}

function extractPollFailureAction() {
  const match = source.match(/function importPollFailureAction411\(failures,code\)\{([^}]*)\}/);
  assert.ok(match, 'ZIP import must define a bounded polling failure policy');
  return new Function('failures', 'code', match[1]);
}

test('ZIP processing progress is projected into the whole-task 38..99 range', () => {
  const mapProgress = extractProgressMapper();
  assert.equal(mapProgress(0), 38);
  assert.equal(mapProgress(8), 42.9);
  assert.equal(mapProgress(34), 58.7);
  assert.equal(mapProgress(45), 65.5);
  assert.equal(mapProgress(95), 96);
  assert.equal(mapProgress(100), 99);
  assert.equal(mapProgress(-10), 38);
  assert.equal(mapProgress(200), 99);
});

test('active ZIP polling uses whole-task progress instead of raw backend phase progress', () => {
  assert.match(source, /progress:mapImportProcessingProgress411\(j\.progress\)/);
  assert.doesNotMatch(source, /progress:Number\(j\.progress\|\|0\)/);
  assert.match(source, /const p=e\.loaded\/e\.total\*35/);
  assert.match(source, /progress:p,eta,uploadSeconds:elapsed/);
  assert.match(source, /progress:38,uploadSeconds:job\.upload_seconds/);
  assert.match(source, /stage:'导入完成'.*progress:100/);
});

test('ZIP polling is bounded and never spins forever when task status cannot be read', () => {
  const action = extractPollFailureAction();
  assert.equal(action(1, 'NETWORK_ERROR'), 'retry');
  assert.equal(action(11, 'HTTP_503'), 'retry');
  assert.equal(action(12, 'HTTP_503'), 'unavailable');
  assert.equal(action(1, 'HTTP_404'), 'missing');

  const pollMatch = source.match(/async function pollImport411\(jobId\)\{([\s\S]*?)\}\n  window\.doUploadZip426/);
  assert.ok(pollMatch, 'active ZIP polling implementation must be present');
  const pollBody = pollMatch[1];
  assert.match(pollBody, /consecutiveErrors/);
  assert.match(pollBody, /importPollFailureAction411\(consecutiveErrors,e\?\.code\)/);
  assert.doesNotMatch(pollBody, /catch\(e\)\{continue\}/);
  assert.match(source, /IMPORT_POLL_UNAVAILABLE/);
  assert.match(source, /stage:'进度读取中断'/);
  assert.match(source, /后台任务可能仍在执行/);
});
