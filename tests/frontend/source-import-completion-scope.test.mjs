import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function owner(marker, endMarker) {
  const start = app.indexOf(marker);
  assert.ok(start >= 0, `owner not found: ${marker}`);
  const end = app.indexOf(endMarker, start + marker.length);
  assert.ok(end > start, `owner end not found: ${endMarker}`);
  return app.slice(start, end);
}

test('source-import terminal completion refreshes only labels and current paged materials', () => {
  const endMarker = '// Keep the existing dataset page clean;';
  const pollingOwner = owner("const SOURCE_IMPORT_POLL_KEY_V36='source-import-v36';", endMarker);
  const body = owner('window.refreshSourceImportTasksV36=async function(){', endMarker);
  assert.match(pollingOwner, /PollRegistryRuntime\?\.startTimeout\?\.\(/, 'active polling must stay owned by PollRegistry');
  assert.match(pollingOwner, /SOURCE_IMPORT_POLL_KEY_V36[\s\S]*'数据集'[\s\S]*1800/);
  assert.doesNotMatch(pollingOwner, /setTimeout\s*\(/, 'source import must not restore a raw timer owner');
  assert.match(body, /\['queued','running'\][\s\S]*scheduleSourceImportRefreshV36\(\)/, 'queued and running tasks must schedule the next managed poll');
  assert.match(body, /else\{\s*window\.PollRegistryRuntime\?\.clear\?\.\(SOURCE_IMPORT_POLL_KEY_V36\)/, 'terminal tasks must clear managed polling');
  assert.doesNotMatch(body, /await loadRelated\(\)/, 'terminal source-import completion must not broad-refresh project state');
  assert.match(body, /await window\.refreshLabels414\?\.\(false\)/, 'terminal source-import completion must refresh label schema');
  assert.match(body, /if\(state\.page==='数据集'\)await window\.reloadMaterialPage61\?\.\(\)/, 'terminal source-import completion must refresh only the visible paged material domain');
});
