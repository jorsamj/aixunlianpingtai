import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('the final AI annotation override uses the persistent v60 task API', () => {
  const marker = source.lastIndexOf('Persistent v60 AI annotation UI');
  assert.ok(marker > 0);
  const finalLayer = source.slice(marker);
  assert.match(finalLayer, /\/api\/v60\/projects\/\$\{pid\(\)\}\/annotation-tasks/);
  assert.doesNotMatch(finalLayer, /\/api\/v47\/projects\/.*ai-label-tasks/);
  assert.match(finalLayer, /createTaskPoller/);
  assert.match(finalLayer, /completeAiReview60/);
  assert.match(finalLayer, /editAiCandidate60/);
});

test('the stable annotation layer is after all legacy renderer overrides', () => {
  assert.ok(source.lastIndexOf('Stable single-instance manual/batch annotation workbench') > source.lastIndexOf('renderAnnotator=function'));
  assert.ok(source.lastIndexOf('/api/v60/projects/${pid()}/annotation-tasks') > source.lastIndexOf('/api/v47/projects/${pid()}/ai-label-tasks'));
});
