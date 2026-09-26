import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');

test('label management has one canonical browser owner', () => {
  assert.match(
    app,
    /window\.manageLabels=\(\)=>\{closeModal\(\);setPage\('标签管理'\)\};/,
  );
  assert.ok(
    !app.includes("window.manageLabels=()=>{modal('标签管理'"),
    'legacy label-management modal must not be restored',
  );
  assert.match(main, /\['标签管理', 'renderLabelManagement414'\]/);
  assert.match(main, /navigationStabilityRuntime\.registerPageOwner\(page/);
  assert.doesNotMatch(app, /state\.page==='标签管理'.*renderLabelManagement414/);
  assert.ok(app.includes('id="label414Aliases"'));
  assert.ok(app.includes('不会用于导入时自动选择或推荐平台标签'));
  assert.doesNotMatch(app, /target_label_code\|\|''\)\?'selected'/);
  assert.match(app, /window\.openInlineLabelCreate414=function/);
  assert.match(app, /window\.submitInlineLabelCreate414=async function/);
  assert.match(app, /平台标签已创建并选中；仍需确认后才会正式入库/);
  assert.match(app, /\/api\/projects\/\$\{pid\(\)\}\/labels/);
  assert.match(app, /openLabelUnify414/);
  assert.match(app, /openLabelBulkUnify414/);
  assert.match(app, /批量统一标签/);
  assert.match(app, /系统不会自动选择目标标签/);
  const saveStart = app.indexOf('window.saveLabel414=async function(classId)');
  const saveEnd = app.indexOf('\n  window.deleteLabel414=', saveStart);
  assert.ok(saveStart >= 0 && saveEnd > saveStart);
  const save = app.slice(saveStart, saveEnd);
  assert.match(save, /await refreshLabels414\(true\);closeModal\(\)/);
  assert.doesNotMatch(save, /refreshImages414|\/images/);
  assert.doesNotMatch(app, /refreshImages414/);
  assert.match(html, /\/static\/app\.js\?v=\d+(?:\.\d+)*/);
});
