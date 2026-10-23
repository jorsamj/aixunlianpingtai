import {withRequestDeadline} from './api.js?v=20261021s';

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const statusText = value => ({normal:'兼容，无需迁移',candidate:'缺失元数据，可预览',unsupported:'仅报告，需人工核验',conflict:'证据冲突，不自动修改'}[value] || '待核验');
const issueText = value => ({'missing content_sha256':'缺少内容 SHA256','missing size_bytes':'缺少文件大小',
  'existing metadata differs from actual source':'已有元数据与实际原图不一致',
  'original is missing':'原始图片缺失','shared object reference requires explicit identity review':'共享原图引用需人工核验',
  'indexed/material payload mismatch':'索引与素材元数据不一致',
  'JSON-only repair unsupported; original owner migration required':'旧 JSON 仅只读检查，不自动导入',
  'source marked unavailable':'来源标记不可用'}[value] || `需人工核验：${value}`);

// Temporary operator UI. Material/GT truth remains in the existing repositories.
export function renderLegacyMaterialCompatibility({projectId, notify, fetchImpl = window.nativeFetch || window.fetch.bind(window)} = {}) {
  const view = document.getElementById('view'), pid = String(projectId?.() || '');
  if (!view) return;
  view.innerHTML = `<section class="panel"><header class="panel-head"><div><h2>旧素材兼容迁移</h2><p>先只读检查。仅补缺失元数据，原图、图片身份及正式 GT 保持原样。</p></div></header><div class="panel-body"><div class="row"><button class="btn primary" data-compat-scan>只读检查本批</button><button class="btn" data-compat-next disabled>下一批</button><button class="btn" data-compat-preview disabled>预览必要修复</button><button class="btn" data-compat-apply disabled>确认迁移本批元数据</button></div><p role="status" data-compat-status>尚未扫描。每批最多 50 条，可随时离开，已提交批次可安全重试。</p><div data-compat-results></div><div data-compat-plan></div></div></section>`;
  const root = view.firstElementChild, status = root.querySelector('[data-compat-status]');
  const controls = Object.fromEntries(['scan','next','preview','apply'].map(name => [name,root.querySelector(`[data-compat-${name}]`)]));
  let busy = false, cursor = '', next = null, candidates = [], plan = null, taskId = null;
  const current = () => view.contains(root) && String(projectId?.() || '') === pid;
  function buttons() {
    for (const button of Object.values(controls)) {button.disabled = busy; button.setAttribute('aria-busy',String(busy));}
    controls.next.disabled = busy || !next;
    controls.preview.disabled = busy || !candidates.length;
    controls.apply.disabled = busy || !plan?.fingerprint || !candidates.length;
  }
  async function request(action, body) {
    return withRequestDeadline(async signal => {
    const response = await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/legacy-material-compatibility/${action}`, {
      method: body ? 'POST' : 'GET', signal,
      ...(body ? {headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message || '兼容检查失败，请重新读取本批');
    return data;
    }, {timeoutMs:30000, label:'兼容元数据操作'});
  }
  async function perform(label, action) {
    if (busy || !current()) return;
    busy = true; buttons(); status.innerHTML = `<span class="loading-spinner" aria-hidden="true"></span> ${esc(label)}`;
    try {await action();} catch (error) {if(current()) status.textContent = error.message || '操作未完成，可重新检查后安全重试';}
    finally {busy = false; if(current()) buttons();}
  }
  const scan = () => perform('正在只读检查素材索引及原始数据…', async () => {
    const data = await request(`scan?limit=50&cursor=${encodeURIComponent(cursor)}`);
    if (!current()) return;
    const rows = data.items || [];
    candidates = rows.filter(row => row.candidate).map(row => row.image_id);
    next = data.next_cursor || null; plan = null; taskId = null;
    status.textContent = candidates.length ? `本批 ${rows.length} 条，${candidates.length} 条需要预览缺失元数据修复。` : rows.every(row=>row.status==='normal') ? `本批 ${rows.length} 条，无需迁移。` : `本批 ${rows.length} 条，无可安全执行的迁移；请查看问题记录。`;
    root.querySelector('[data-compat-results]').innerHTML = `<table class="table"><thead><tr><th>图片身份</th><th>状态</th><th>检查结果</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.image_id)}</td><td>${esc(statusText(row.status))}</td><td>${esc((row.issues || []).map(issueText).join('；') || '兼容，无需迁移')}</td></tr>`).join('')}</tbody></table>`;
    root.querySelector('[data-compat-plan]').textContent = '';
  });
  controls.scan.onclick = scan;
  controls.next.onclick = () => {cursor = next || ''; return scan();};
  controls.preview.onclick = () => perform('正在核对迁移影响与当前版本…', async () => {
    const data = await request('preview',{image_ids:candidates});
    if (!current()) return;
    plan = data.preview || data; taskId = `legacy-metadata-${crypto.randomUUID()}`;
    root.querySelector('[data-compat-plan]').innerHTML = `<p>本批最多修复 ${candidates.length} 条缺失索引字段。执行前备份并重新核验；冲突数据不覆盖，原图及 GT 不修改。</p><table class="table"><thead><tr><th>图片身份</th><th>补齐大小（字节）</th><th>补齐内容 SHA256</th></tr></thead><tbody>${(plan.items || []).map(item=>`<tr><td>${esc(item.image_id)}</td><td>${esc(item.proposed?.size_bytes ?? '不修改')}</td><td><code>${esc(item.proposed?.content_sha256 || '不修改')}</code></td></tr>`).join('')}</tbody></table>`;
    status.textContent = plan.fingerprint ? '影响预览已就绪，请核对后明确确认。' : '当前没有可执行计划，请重新检查。';
  });
  controls.apply.onclick = () => {
    if (busy || !plan || !window.confirm('确认只补齐本批缺失元数据？原始图片及正式 GT 不会修改。')) return;
    return perform('正在备份并迁移本批元数据，请勿重复提交…', async () => {
      await request('apply',{image_ids:candidates,expected_fingerprint:plan.fingerprint,task_id:taskId,confirm:'migrate_legacy_material_metadata'});
      if (!current()) return;
      plan = null; candidates = []; status.textContent = '本批元数据处理完成。可重新只读检查或继续下一批。'; notify?.('本批兼容元数据处理完成');
    });
  };
  buttons();
}
