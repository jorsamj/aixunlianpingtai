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
  assert.match(app, /目标标签必须由你手工选择，系统不会自动推荐/);
  assert.match(app, /标签完整性/);
  assert.match(app, /AUDIT_LABEL_INTEGRITY/);
  assert.match(app, /labels\/integrity\/audits/);
  assert.match(app, /labels\/integrity\/audits\/\$\{taskId\}\/issues/);
  assert.match(app, /labels\/integrity\/audits\/\$\{auditTaskId\}\/samples/);
  assert.match(app, /labels\/integrity\/audits\/\$\{auditTaskId\}\/repairs/);
  assert.match(app, /PollRegistryRuntime\?\.startTimeout\('label-integrity-audit'/);
  assert.match(app, /由你选择当前 active 目标标签/);
  assert.match(app, /查看样例/);
  assert.match(app, /换一批/);
  assert.match(app, /历史 class_id 当前对应标签仅用于诊断身份错位，不代表旧标签真实语义/);
  assert.match(app, /请先查看样例确认该历史标签真实语义，再选择目标标签/);
  assert.doesNotMatch(app, /recommended_target|recommendTarget|自动推荐 target/);
  assert.doesNotMatch(app, /setTimeout\([^)]*pollLabelIntegrity/);
  const saveStart = app.indexOf('window.saveLabel414=async function(classId)');
  const saveEnd = app.indexOf('\n  window.deleteLabel414=', saveStart);
  assert.ok(saveStart >= 0 && saveEnd > saveStart);
  const save = app.slice(saveStart, saveEnd);
  const truthPatch = save.indexOf('applyLabelMutation414(result,classId)');
  const close = save.indexOf('closeModal()');
  const usageRefresh = save.indexOf('void refreshLabels414(true)');
  assert.ok(truthPatch >= 0 && truthPatch < close, 'successful mutation truth must be patched before modal close');
  assert.ok(close >= 0 && close < usageRefresh, 'usage statistics refresh must not block modal close');
  assert.doesNotMatch(save, /await refreshLabels414\(true\);closeModal\(\)/);
  assert.doesNotMatch(save, /refreshImages414|\/images/);
  assert.doesNotMatch(app, /refreshImages414/);
  assert.match(html, /\/static\/app\.js\?v=\d+(?:\.\d+)*/);
});
