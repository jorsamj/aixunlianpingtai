import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/zip-import-bootstrap.mjs', import.meta.url), 'utf8');
const appSource = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('legacy import modal stays server-backed instead of reusing durable bootstrap snapshot', () => {
  assert.doesNotMatch(source, /runtime\.snapshot\?\.\(\)/);
  assert.doesNotMatch(source, /syncLegacyImportJobsFromRuntime/);
  assert.doesNotMatch(source, /reuseRuntimeSnapshot/);
  assert.doesNotMatch(source, /window\.loadImportJobs\s*=/);
  assert.doesNotMatch(source, /window\.openImportDock\s*=/);
});

test('durable ZIP runtime owns polling and completion side effects', () => {
  assert.match(source, /LEGACY_IMPORT_POLL_SENTINEL\s*=\s*-1/);
  assert.match(source, /claimLegacyImportPolling\(\)/);
  assert.match(source, /state\.importPollTimer\s*=\s*LEGACY_IMPORT_POLL_SENTINEL/);
  assert.match(source, /clearInterval\(existing\)/);
  assert.match(source, /runtime\.reconcile\?\.\('legacy-start'\)/);
  assert.match(source, /window\.ZipImportRuntimeLegacyBridge\s*=\s*Object\.freeze/);
  assert.doesNotMatch(source, /originalStartImportJobV19|bridgedStartImportJobV19/);
  assert.doesNotMatch(source, /window\.startImportJobV19\s*=/);
  assert.match(appSource, /ZipImportRuntimeLegacyBridge\?\.beforeStart\?\.\(\)/);
  assert.match(appSource, /ZipImportRuntimeLegacyBridge\?\.afterStart\?\.\(\)/);
});
