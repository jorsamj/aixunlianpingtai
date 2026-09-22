import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const zipRuntime = readFileSync(new URL('../../static/modules/zip-import-runtime.js', import.meta.url), 'utf8');

function region(source,startToken,endToken) {
  const start=source.indexOf(startToken);
  const end=source.indexOf(endToken,start+startToken.length);
  assert.ok(start>=0&&end>start,`missing region ${startToken}`);
  return source.slice(start,end);
}

test('durable ZIP completion keeps review ownership and refreshes only label/material domains', () => {
  const owner=region(zipRuntime,'async function applyCompletion(job,reason)','function publishTaskCenterJob');
  assert.match(owner,/completeZipImportReview412\?\.\(id\)/);
  assert.match(owner,/refreshLabels414\?\.\(false\)/);
  assert.match(owner,/reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(owner,/loadRelated\s*\(/);
  assert.doesNotMatch(owner,/loadAll\s*\(/);
  assert.equal((zipRuntime.match(/window\.doUploadZip426=/g)||[]).length,1);
  assert.equal((app.match(/window\.doUploadZip426=/g)||[]).length,0);
});

test('server storage import confirmation stays mapping-only and never broad-loads', () => {
  const owner=region(app,'window.confirmStorageImport61=async function(taskId){','window.beforeCloseStorageImport61=function()');
  assert.match(owner,/serverApi\(\)\.buildImportConfirmation\(rows/);
  assert.doesNotMatch(owner,/refreshLabels414/);
  assert.match(owner,/state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/);
  assert.doesNotMatch(owner,/loadRelated\s*\(/);
  assert.doesNotMatch(owner,/loadAll\s*\(/);
});

test('v36 source import polling remains page-scoped through PollRegistry', () => {
  const owner=region(app,"const SOURCE_IMPORT_POLL_KEY_V36='source-import-v36';",'// Keep the existing dataset page clean;');
  assert.match(owner,/PollRegistryRuntime\?\.startTimeout\?\.\(/);
  assert.match(owner,/'数据集'/);
  assert.match(owner,/PollRegistryRuntime\?\.clear\?\.\(SOURCE_IMPORT_POLL_KEY_V36\)/);
  assert.doesNotMatch(owner,/__sourceImportTimerV36/);
});
