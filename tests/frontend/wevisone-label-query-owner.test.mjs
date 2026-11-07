import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const styles=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');

test('one existing model editor owns WeVisOne-specific code to query descriptors',()=>{
  const start=source.indexOf('M4: real vision providers, reviewable boxes, explicit targets');
  const end=source.indexOf('window.testModelConfigM4=async function',start);
  const owner=source.slice(start,end);
  assert.ok(start>=0&&end>start);
  assert.equal((source.match(/window\.saveVisionModelM4=async function/g)||[]).length,1);
  assert.match(owner,/wevisoneDormitoryQueries/);
  assert.match(owner,/wevisone_label_queries:dedicated\?labelQueries\.value:null/);
  assert.match(owner,/document\.getElementById\('mcWevisoneQueries'\)\?\.classList\.toggle\('hidden',!dedicated\)/);
  assert.match(owner,/readWevisoneQueriesM4\(\)/);
  assert.match(owner,/不接收通用聊天提示词/);
  assert.match(styles,/\.model-m4-query-editor\{/);
});

test('AI creation previews native per-label queries and keeps generic prompting for other providers',()=>{
  const start=source.indexOf('function aiCreateRenderModels429()');
  const end=source.indexOf('window.previewAiPrompt429=async function',start);
  const owner=source.slice(start,end);
  assert.ok(start>=0&&end>start);
  assert.match(owner,/aiCreateDedicatedModel429/);
  assert.match(owner,/cfg\.wevisone_label_queries\|\|\{\}/);
  assert.match(owner,/syncAiNativeQueries429\(\)/);
  assert.match(owner,/实际发送的标签查询/);
  assert.match(styles,/\.ai-create-native>\.form,\.ai-create-native>\.field/);
  assert.match(source,/if\(aiCreateDedicatedModel429\(\)\)\{syncAiNativeQueries429\(\);return\}/);
});
