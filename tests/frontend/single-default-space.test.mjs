import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function block(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from + start.length);
  assert.notEqual(from, -1, `missing start marker: ${start}`);
  assert.notEqual(to, -1, `missing end marker: ${end}`);
  return source.slice(from, to);
}

test('workspace loading is GET-only and never falls back to project creation', () => {
  const base = block('async function ensureWorkspace()', 'async function loadAll()');
  const owner = block('ensureWorkspace = async function()', 'function stepCard');

  for (const implementation of [base, owner]) {
    assert.match(implementation, /await api\('\/api\/projects'\)/);
    assert.doesNotMatch(implementation, /safe\(api\('\/api\/projects'/);
    assert.doesNotMatch(implementation, /method:\s*'POST'/);
  }
});

test('saved projectId and preferred_project_id cannot switch the server-owned space', () => {
  const owner = block('ensureWorkspace = async function()', 'function stepCard');
  const startup = block('/* v42.13 startup prepared snapshot */', '/* ============================================================');

  assert.doesNotMatch(owner, /lastState\.projectId|projects\.find/);
  assert.doesNotMatch(startup, /savedProject|preferred_project_id/);
  assert.match(startup, /api\('\/api\/v53\/bootstrap\/snapshot'\)/);
});

test('dataset, material and training requests derive from the selected server project', () => {
  const related = block('async function loadRelated()', 'function statusName');
  const core = block('window.loadCore412=async function', 'async function pollAnnotationIndex412');
  assert.match(related, /const pid=state\.project\.id/);
  assert.match(related, /`\/api\/projects\/\$\{pid\}\/datasets/);
  assert.match(related, /`\/api\/projects\/\$\{pid\}\/images/);
  assert.match(core, /const id=state\.project\.id/);
  assert.match(core, /state\.jobs=snapshot\.jobs/);
});
