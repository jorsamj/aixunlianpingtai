import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.saveAssign=async name=>{const m=state.assigningModel||{},aid=$('#algoSel').value;const r=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value,job_id:m.job_id||''})}));if(!r?.version)return;const a=(state.algorithms||[]).find(x=>x.id===aid);if(a)a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)];state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key));state.assigningModel=null;closeModal();render();toast('已发布为算法版本')};";

test('final model publish owner uses authoritative mutation result', () => {
  assert.equal(app.includes(owner), true);
  assert.equal(app.includes("closeModal();await reload();toast('已发布为算法版本')"), false);
  assert.equal(app.includes("if(!r?.version)return"), true);
});

test('model publish updates algorithm versions and pending state locally', () => {
  assert.equal(app.includes("a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)]"), true);
  assert.equal(app.includes("state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key))"), true);
  assert.equal(app.includes("state.assigningModel=null;closeModal();render();toast('已发布为算法版本')"), true);
});
