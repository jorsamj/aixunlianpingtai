import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function liveStorageUploaderRegion() {
  const captureMarker = 'window.__storageDoUploadImages61=window.doUploadImages426;';
  const captureIndex = appSource.indexOf(captureMarker);
  assert.ok(captureIndex > 0, 'storage61 must capture the live image-upload owner');

  const assignment = 'window.doUploadImages426=';
  const start = appSource.lastIndexOf(assignment, captureIndex);
  assert.ok(start >= 0, 'live storage61 image uploader must be defined before capture');
  return appSource.slice(start, captureIndex);
}

function browserByteProgress(region, loaded, total) {
  const match = region.match(/const percent=([^,;]+),bar=document\.getElementById\('up411Bar'\)/);
  assert.ok(match, 'live image uploader must expose one explicit browser-byte progress expression');
  return new Function('event', `return (${match[1]});`)({loaded, total});
}

test('plain-image byte upload reaching 100% must not present the whole task as 100% before server commit', () => {
  const region = liveStorageUploaderRegion();
  const shown = browserByteProgress(region, 1024, 1024);

  assert.ok(Number.isFinite(shown), 'browser-byte progress must remain numeric');
  assert.ok(shown < 100, `browser byte completion must stay below terminal 100%, got ${shown}%`);
  assert.match(region, /正在服务器入库/, 'byte-transfer completion must explicitly expose the server-side commit stage');
});

test('plain-image terminal 100% is owned by successful HTTP completion, not xhr.upload', () => {
  const region = liveStorageUploaderRegion();
  const uploadHandlerEnd = region.indexOf('};xhr.onerror=');
  const onloadStart = region.indexOf('xhr.onload=async()=>');
  assert.ok(uploadHandlerEnd > 0 && onloadStart > uploadHandlerEnd, 'live uploader handlers must remain ordered upload -> error -> load');

  const uploadHandler = region.slice(0, uploadHandlerEnd);
  const onloadHandler = region.slice(onloadStart);
  assert.doesNotMatch(uploadHandler, /(?:width|textContent)=['"`]100%['"`]/, 'xhr.upload must never own terminal 100%');
  assert.match(onloadHandler, /width=['"`]100%['"`]/, 'successful HTTP completion must set the progress bar to terminal 100%');
  assert.match(onloadHandler, /textContent=['"`]100%['"`]/, 'successful HTTP completion must set the visible percentage to terminal 100%');
});
