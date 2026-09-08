import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  buildMaterialQuery,
  requiresFullMaterialPool,
} from '../../static/modules/material-pagination-runtime.js';


test('material paging query keeps filters on the server', () => {
  const params = buildMaterialQuery({
    limit: 48,
    cursor: 'next-token',
    query: 'fire',
    sourceId: 'oss-a',
    processingStatus: 'processed',
    labels: ['fire', 'smoke'],
    annotated: 'marked',
  });
  assert.equal(params.get('limit'), '48');
  assert.equal(params.get('cursor'), 'next-token');
  assert.equal(params.get('query'), 'fire');
  assert.deepEqual(params.getAll('storage_source_id'), ['oss-a']);
  assert.equal(params.get('processing_status'), 'processed');
  assert.deepEqual(params.getAll('label'), ['fire', 'smoke']);
  assert.equal(params.get('annotated'), 'true');
});


test('training and AI workflows explicitly request the full material pool', () => {
  assert.equal(requiresFullMaterialPool('数据集'), false);
  assert.equal(requiresFullMaterialPool('算法列表'), false);
  assert.equal(requiresFullMaterialPool('训练任务'), true);
  assert.equal(requiresFullMaterialPool('自动标注及清洗'), true);
  assert.equal(requiresFullMaterialPool('质量中心'), true);
});


test('pagination bootstrap is loaded before the legacy app bundle', () => {
  const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const bootstrap = html.indexOf('material-pagination-bootstrap.js');
  const app = html.indexOf('/static/app.js');
  assert.ok(bootstrap >= 0);
  assert.ok(app > bootstrap);

  const bootstrapSource = fs.readFileSync(new URL('../../static/material-pagination-bootstrap.js', import.meta.url), 'utf8');
  assert.match(bootstrapSource, /\/api\/v61\/projects\/\$\{projectId\}\/materials/);
  assert.match(bootstrapSource, /state\.mode !== 'paged'/);
});


test('page renders cannot overwrite the current UI version with 42.22.0', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /badge\.textContent='v42\.22\.0'/);
  assert.doesNotMatch(source, /footer\.textContent='v42\.22\.0'/);
});


test('upload cleaning decisions retain the complete current upload batch', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /recentUploadedMaterials61=\[\.\.\.uploaded\]/);
  assert.doesNotMatch(source, /recentUploadedMaterials61=.*\.slice\(0,500\)/);
});
