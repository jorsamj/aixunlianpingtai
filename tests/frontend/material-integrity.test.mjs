import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('material integrity stays inside material management and uses durable batch deletion', () => {
  assert.match(app, /重复与异常素材/);
  assert.match(app, /AUDIT_MATERIAL_INTEGRITY/);
  assert.match(app, /DUPLICATE_ANNOTATION_CONFLICT:'同图不同标注'/);
  assert.match(app, /同一图片存在不同 Ground Truth/);
  assert.match(app, /系统不会自动保留第一条/);
  assert.match(app, /runMaterialBatch62\?\.\('DELETE_INDEX'/);
  assert.match(app, /共享物理对象不会被删除/);
});

test('material integrity provides overlay evidence and explicit human actions', () => {
  assert.match(app, /materialIntegrityOverlay47/);
  assert.match(app, /进入标注/);
  assert.match(app, /保留这条/);
  assert.match(app, /批量删除/);
  assert.match(app, /openAnnotation/);
});
