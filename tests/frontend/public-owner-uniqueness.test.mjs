import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('high-traffic public owners are unique in classic app', () => {
  for (const [name, pattern] of [
    ['openDataUpload426', /window\.openDataUpload426=/g],
    ['doUploadImages426', /window\.doUploadImages426=/g],
    ['reviewAiLabel427', /window\.reviewAiLabel427=/g],
    ['confirmAiLabel427', /window\.confirmAiLabel427=/g],
    ['renderDetectionResult', /window\.renderDetectionResult\s*=/g],
    ['__clInit', /window\.__clInit=/g],
  ]) assert.equal((app.match(pattern) || []).length, 1, name);
});

test('storage upload uses private owners until final activation', () => {
  assert.match(app, /window\.openDataUploadStorage61=async function\(\)/);
  assert.match(app, /window\.doUploadImagesStorage61=function\(input\)/);
  assert.match(app, /window\.__storageOpenUpload61=window\.openDataUploadStorage61/);
  assert.match(app, /window\.__storageDoUploadImages61=window\.doUploadImagesStorage61/);
});

test('AI review public owner is v60 only', () => {
  assert.equal(app.includes('window.reviewAiLabel427=window.__m4ReviewCandidates'), false);
  assert.match(app, /Persistent v60 AI annotation UI/);
  assert.match(app, /window\.reviewAiLabel427=async function\(id\)/);
  assert.match(app, /window\.confirmAiLabel427=id=>completeAiReview60\('partial'\)/);
});

test('v61 owns public detection rendering and v31 remains explicit core', () => {
  assert.match(app, /window\.renderDetectionResultCore31 = function renderDetectionResultCore31/);
  assert.match(app, /window\.renderDetectionResult=function renderDetectionResultCanonical61/);
});
