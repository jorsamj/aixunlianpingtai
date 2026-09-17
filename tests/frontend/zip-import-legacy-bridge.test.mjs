import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/zip-import-bootstrap.mjs', import.meta.url), 'utf8');

test('legacy import modal consumes durable bootstrap snapshot only once', () => {
  assert.match(source, /runtime\.snapshot\?\.\(\)/);
  assert.match(source, /state\.importJobs\s*=\s*Array\.isArray\(snapshot\.jobs\)/);
  assert.match(source, /let reuseRuntimeSnapshot\s*=\s*true/);
  assert.match(source, /if \(reuseRuntimeSnapshot\)/);
  assert.match(source, /reuseRuntimeSnapshot\s*=\s*false/);
  assert.match(source, /return syncLegacyImportJobsFromRuntime\(\)/);
  assert.match(source, /return originalLoadImportJobs\.apply\(this, args\)/);
  assert.match(source, /window\.loadImportJobs\s*=\s*bridgedLoadImportJobs/);
  assert.doesNotMatch(source, /openingImportDock/);
  assert.doesNotMatch(source, /window\.openImportDock\s*=\s*bridgedOpenImportDock/);
});

test('durable ZIP runtime owns polling and completion side effects', () => {
  assert.match(source, /LEGACY_IMPORT_POLL_SENTINEL\s*=\s*-1/);
  assert.match(source, /claimLegacyImportPolling\(\)/);
  assert.match(source, /state\.importPollTimer\s*=\s*LEGACY_IMPORT_POLL_SENTINEL/);
  assert.match(source, /clearInterval\(existing\)/);
  assert.match(source, /runtime\.reconcile\?\.\('legacy-start'\)/);
  assert.match(source, /window\.startImportJobV19\s*=\s*bridgedStartImportJobV19/);
});
