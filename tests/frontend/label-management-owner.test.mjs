import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('label management has one canonical browser owner', () => {
  assert.match(
    app,
    /window\.manageLabels=\(\)=>\{closeModal\(\);setPage\('标签管理'\)\};/,
  );
  assert.ok(
    !app.includes("window.manageLabels=()=>{modal('标签管理'"),
    'legacy label-management modal must not be restored',
  );
  assert.ok(
    app.includes(
      "if(state.page==='标签管理'){renderNav();renderTop();renderSummary();renderLabelManagement414();return}",
    ),
    'configuration page must remain owned by renderLabelManagement414',
  );
  assert.ok(app.includes('id="label414Aliases"'));
  assert.ok(app.includes('自动预选后仍需人工确认才会正式入库'));
  assert.match(app, /window\.openInlineLabelCreate414=function/);
  assert.match(app, /window\.submitInlineLabelCreate414=async function/);
  assert.match(app, /平台标签已创建并选中；仍需确认后才会正式入库/);
  assert.match(app, /\/api\/projects\/\$\{pid\(\)\}\/labels/);
});
