import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('shadowed AI review wrapper is physically retired before v60 owner', () => {
  assert.equal(app.includes('const oldReviewAi429=window.reviewAiLabel427;'), false);
  const final = app.lastIndexOf('window.reviewAiLabel427=async function(id)');
  const marker = app.lastIndexOf('Persistent v60 AI annotation UI');
  assert.ok(final > marker);
});

test('classic app no longer chains historical image-upload owners', () => {
  assert.equal(app.includes('const oldImageUpload412=window.doUploadImages426;'), false);
  assert.equal(app.includes('const upload414=window.doUploadImages426;'), false);
  assert.equal(app.includes('review412-image'), false);
  assert.match(app, /if\(window\.__storageDoUploadImages61\)window\.doUploadImages426=window\.__storageDoUploadImages61/);
});
