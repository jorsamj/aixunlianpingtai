import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/zip-import-bootstrap.mjs', import.meta.url), 'utf8');

test('legacy import task modal reuses durable runtime snapshot before explicit refresh', () => {
  assert.match(source, /runtime\.snapshot\?\.\(\)/);
  assert.match(source, /state\.importJobs\s*=\s*Array\.isArray\(snapshot\.jobs\)/);
  assert.match(source, /reuseRuntimeSnapshot\s*=\s*true/);
  assert.match(source, /window\.loadImportJobs\s*=\s*bridgedLoadImportJobs/);
  assert.match(source, /window\.openImportDock\s*=\s*bridgedOpenImportDock/);
  assert.match(source, /return originalLoadImportJobs\.apply\(this, args\)/);
});
