import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/modules/material-pagination-runtime.js',import.meta.url),'utf8');
const start=source.indexOf('  async function loadMaterialPage61(');
const end=source.indexOf('  async function focusedRefresh61(',start);
assert.ok(start>=0&&end>start);
const load=source.slice(start,end);
test('page loading settles independently of revision-keyed status-count requests',()=>{
  assert.match(load,/const materialPage = await fetchMaterialPage61/);
  assert.match(load,/void totalsPromise\.then\(counts =>/);
  assert.doesNotMatch(load,/const counts = await totalsPromise/);
  assert.match(load,/controller\.signal\.aborted \|\| serial !== requestSerial/);
  assert.match(load,/countsScope !== JSON\.stringify/);
  assert.match(load,/info\.statusCountsScope = countsScope/);
  assert.match(load,/return \{stale: false, mode, items: state\.images, total: info\.total\};/);
});
