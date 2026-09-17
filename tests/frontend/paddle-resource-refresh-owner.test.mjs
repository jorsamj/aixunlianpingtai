import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const manualStart = app.lastIndexOf("window.detectPaddle=async function(){");
const quickStart = app.lastIndexOf("window.quickPaddleDetect=async function(){");
assert.ok(manualStart >= 0 && quickStart > manualStart);
const manual = app.slice(manualStart, quickStart);
const quick = app.slice(quickStart, app.indexOf('\n  };', quickStart) + 5);

test('final paddle activation owners use scoped training-target refresh', () => {
  assert.equal(app.match(/async function refreshPaddleTrainingTargets20d\(\)/g)?.length, 1);
  assert.match(app, /refreshPaddleTrainingTargets20d[\s\S]*\/api\/training_options\?project_id=\$\{pid\(\)\}/);
  assert.match(manual, /await refreshPaddleTrainingTargets20d\(\)/);
  assert.match(quick, /await refreshPaddleTrainingTargets20d\(\)/);
});

test('final paddle activation owners do not invoke global loadAll refresh', () => {
  assert.equal(manual.includes('await loadAll()'), false);
  assert.equal(quick.includes('await loadAll()'), false);
  assert.equal(app.includes("const cur='训练资源'; await loadAll(); state.page=cur; render(); toast('飞桨环境已启用')"), false);
  assert.equal(app.includes("state.page='训练资源'; await loadAll(); render(); toast('已启用飞桨环境')"), false);
});
