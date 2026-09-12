import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const owner = "window.saveServer=async()=>{await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};";

test('training server save has one final scoped-refresh owner', () => {
  assert.equal(app.split('window.saveServer=').length - 1, 1);
  assert.equal(app.includes(owner), true);
});

test('training server save cannot return to global reload', () => {
  assert.equal(app.includes("closeModal();await reload();toast('已保存服务器')"), false);
  assert.equal(app.includes("const opts=await safe(api(`/api/training_options?project_id=${pid()}`))"), true);
  assert.equal(app.includes("if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')"), true);
});
