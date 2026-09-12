import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));closeModal();const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('算法列表刷新模块未加载，请刷新页面后重试');return}await runtime.refresh({render:true});toast('已删除版本')};";

test('algorithm version deletion has one final owner', () => {
  assert.equal(app.split('window.delVersion=').length - 1, 1);
  assert.equal(app.includes(owner), true);
});

test('algorithm version deletion cannot return to global reload', () => {
  assert.equal(app.includes("closeModal();await reload();toast('已删除版本')"), false);
  assert.equal(app.includes("await runtime.refresh({render:true});toast('已删除版本')"), true);
});
