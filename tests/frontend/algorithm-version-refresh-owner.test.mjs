import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;const result=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));if(!result)return;closeModal();const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('版本状态已更新，请刷新页面查看');return}await runtime.refresh({render:true});toast(result.cleanup_status==='cleanup_completed'?'已删除版本及其专属产物':'版本记录已删除，部分物理产物清理失败，请查看操作记录')};";

test('algorithm version deletion has one final owner', () => {
  assert.equal(app.split('window.delVersion=').length - 1, 1);
  assert.equal(app.includes(owner), true);
});

test('algorithm version deletion cannot return to global reload', () => {
  assert.equal(app.includes("closeModal();await reload();toast('已删除版本')"), false);
  assert.equal(app.includes('await runtime.refresh({render:true});'), true);
  assert.equal(app.includes("const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('版本状态已更新，请刷新页面查看');return}"), true);
});

test('algorithm version deletion commits UI only after authoritative delete success and preserves cleanup truth', () => {
  assert.equal(app.includes("const result=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));if(!result)return;closeModal();"), true);
  assert.equal(app.includes("result.cleanup_status==='cleanup_completed'?'已删除版本及其专属产物':'版本记录已删除，部分物理产物清理失败，请查看操作记录'"), true);
});
