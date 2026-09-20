import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('material import dock uses the normal light UI surface', () => {
  const button = css.match(/\.import-dock-btn\{([^}]*)\}/);
  assert.ok(button, 'import dock button style must exist');
  assert.match(button[1], /background:#fff/);
  assert.match(button[1], /color:#0f172a/);
  assert.doesNotMatch(button[1], /background:#111827/);

  const secondary = css.match(/\.import-dock-btn small\{([^}]*)\}/);
  assert.ok(secondary, 'import dock secondary text style must exist');
  assert.match(secondary[1], /color:#64748b/);
});

test('material import dock exposes a safe clear-finished action', () => {
  assert.match(app, /onclick="clearFinishedImportJobs\(\)">清空已结束<\/button>/);
  assert.match(app, /window\.clearFinishedImportJobs=async\(\)=>/);
  assert.match(app, /api\(\`\/api\/v19\/projects\/\$\{pid\(\)\}\/import\/jobs\`,\{method:'DELETE'\}\)/);
  assert.match(app, /\['done','failed','cancelled','canceled'\]/);
  assert.match(app, /正在运行和待确认任务会保留/);
});

