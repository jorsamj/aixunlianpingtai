import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function owner(marker, size = 5200) {
  const start = app.indexOf(marker);
  assert.ok(start >= 0, `owner not found: ${marker}`);
  return app.slice(start, start + size);
}

test('source-import terminal completion refreshes only labels and current paged materials', () => {
  const body = owner('window.refreshSourceImportTasksV36=async function(){');
  assert.match(body, /setTimeout\(refreshSourceImportTasksV36,1800\)/, 'active source-import polling cadence must stay owned by refreshSourceImportTasksV36');
  assert.doesNotMatch(body, /await loadRelated\(\)/, 'terminal source-import completion must not broad-refresh project state');
  assert.match(body, /await window\.refreshLabels414\?\.\(false\)/, 'terminal source-import completion must refresh label schema');
  assert.match(body, /if\(state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/, 'terminal source-import completion must refresh only the visible paged material domain');
});
