import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const taskCenter = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');

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


test('upload task center opens above ZIP modal but yields to unrelated dialogs', () => {
  const dock = taskCenter.match(/\.utc-root\{[^}]*z-index:(\d+)/);
  const modal = css.match(/\.modal\{[^}]*z-index:(\d+)/);
  const otherDialogGuard = taskCenter.match(/body:has\(\.modal:not\(\.hidden\):not\(\.import350-modal\)\) \.utc-root\{z-index:(\d+)\}/);
  assert.ok(dock, 'upload task center z-index must be explicit');
  assert.ok(modal, 'modal z-index must be explicit');
  assert.ok(otherDialogGuard, 'unrelated dialogs must take precedence over the ZIP upload dock');
  assert.ok(Number(dock[1]) > Number(modal[1]), 'upload task center must remain clickable while ZIP modal is open');
  assert.ok(Number(otherDialogGuard[1]) < Number(modal[1]), 'unrelated dialogs must stay above the upload task center');
};

test('import modal remains mounted while minimized without creating a second uploader',()=>{
 const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const css=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
 assert.match(app,/decorateImportModal424/);
 assert.match(app,/data-import-minimize/);
 assert.match(css,/\.modal\.import350-minimized/);
 assert.match(css,/\.modal\.import350-minimized \.modal-body\{display:none/);
});
