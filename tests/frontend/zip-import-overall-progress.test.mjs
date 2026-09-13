import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function extractProgressMapper() {
  const match = source.match(/function mapImportProcessingProgress411\(progress\)\{([^}]*)\}/);
  assert.ok(match, 'ZIP import must define a processing-to-overall progress mapper');
  return new Function('progress', match[1]);
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
  assert.match(source, /progress:e\.loaded\/e\.total\*35/);
  assert.match(source, /progress:38,uploadSeconds:job\.upload_seconds/);
  assert.match(source, /stage:'导入完成'.*progress:100/);
});
