import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFile, execFileSync} from 'node:child_process';

import {test, expect} from '@playwright/test';

// Only the temporary repository created by tools/test_server.py is eligible.
function isolatedPython(projectId, source, asynchronous = false) {
  const roots = fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('xjalgo-browser-'))
    .map(name => path.join(os.tmpdir(), name))
    .filter(root => fs.existsSync(path.join(root, 'projects', projectId)));
  expect(roots).toHaveLength(1);
  const options={encoding: 'utf8', env: {
    ...process.env, MC_TRAIN_DATA_DIR: roots[0], MC_PLATFORM_VERSION: 'browser-test',
    INTEGRITY_TEST_PROJECT: projectId,
  }};
  if(asynchronous)return new Promise((resolve,reject)=>execFile('python',['-c',source],options,(error,stdout)=>error?reject(error):resolve(stdout.trim())));
  return execFileSync('python', ['-c', source], options).trim();
}

function runIsolatedWorker(projectId, taskId, asynchronous = false) {
  return isolatedPython(projectId, `import os,json,app
from contextlib import closing
from platform_core.task_runtime import Scheduler, TaskKind
from platform_core.material_batches import MaterialBatchHandler
r=app.shared_task_repository(); target=${JSON.stringify(taskId)}; capability='test.integrity.'+target
# Test-only routing: never claim another test/project's ordinary batch.
# Normal materials.batch admission is covered by the Python integration suite.
with closing(r._connect()) as database:
 database.execute('BEGIN IMMEDIATE')
 row=database.execute('SELECT project_id,status,required_capabilities FROM tasks WHERE task_id=?',(target,)).fetchone()
 assert row['project_id']==os.environ['INTEGRITY_TEST_PROJECT'] and row['status']=='QUEUED'
 assert json.loads(row['required_capabilities'])==['materials.batch']
 database.execute('UPDATE tasks SET required_capabilities=? WHERE task_id=?',(json.dumps([capability]),target)); database.commit()
s = Scheduler(r, app.shared_task_artifacts(), 'integrity-browser-worker', {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app.DATA_DIR)}, {capability}, lease_seconds=60)
assert s.run_once()
assert r.get(target).status.value=='SUCCEEDED' and r.get(target).attempt==1
`, asynchronous);
}

test('real frozen scope, >100 image pagination, failed submit, queued repeat and durable deletion', async ({page, request}) => {
  const otherProject=await createProject(request);
  const unrelatedAudit=await request.post(`/api/v62/projects/${otherProject.id}/material-integrity/audits`);
  const unrelatedId=(await unrelatedAudit.json()).task_id;
  const project = await createProject(request);
  const png = execFileSync('python', ['-c', "from PIL import Image; import io,sys; b=io.BytesIO(); Image.new('RGB',(160,90),'#9ec9e6').save(b,format='PNG'); sys.stdout.buffer.write(b.getvalue())"]);
  const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
    files: {name: 'wide-evidence.png', mimeType: 'image/png', buffer: png}, dataset_id: 'default',
  }});
  expect(upload.ok()).toBeTruthy();
  isolatedPython(project.id, `import os,app
from platform_core.annotation_repository import AnnotationRepository
p=os.environ['INTEGRITY_TEST_PROJECT']; m=app.material_store(p); first=m.list_page(limit=1).items[0]
a=AnnotationRepository(m.project_path)
for i in range(125):
 row={k:v for k,v in first.items() if not k.startswith('annotation_')}; row.update(id=f'browser-copy-{i:03}',filename=f'wide-{i:03}.png'); m.upsert(row)
for row in m.list_page(limit=200).items:
 a.upsert(row['id'],[{'label':'target','class_id':0,'x1':16,'y1':9,'x2':80,'y2':45}],annotation_state='annotated')
`);
  const audit = await request.post(`/api/v62/projects/${project.id}/material-integrity/audits`);
  expect(audit.status()).toBe(202);
  const auditId = (await audit.json()).task_id;
  runIsolatedWorker(project.id,auditId);
  expect((await (await request.get(`/api/v62/projects/${otherProject.id}/material-batches/${unrelatedId}`)).json()).persisted_status).toBe('QUEUED');
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());url.searchParams.set('preferred_project_id', project.id);
    await route.fallback({url: url.toString()});
  });
  await page.addInitScript(() => localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'})));
  await page.setViewportSize({width: 1366, height: 768});
  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: '重复与异常素材'}).click();
  await page.getByRole('button', {name: /查看证据/}).click();
  const cards = page.locator('#materialIntegrityItems47 > article');
  await expect(cards).toHaveCount(100);
  await page.getByRole('button', {name: '全选当前页', exact: true}).click();
  await expect(page.locator('#materialIntegritySelected47')).toContainText('已选 100');
  await page.getByRole('button', {name: '下一页图片'}).click();
  await expect(cards).toHaveCount(26);
  await expect(page.locator('#materialIntegritySelected47')).toContainText('已选 100');
  await cards.first().getByRole('checkbox').check();
  await expect(page.locator('#materialIntegritySelected47')).toContainText('已选 101');
  const image = cards.first().locator('img');
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate(el => el.complete && el.naturalWidth)).toBe(160);
  const geometry = await cards.first().evaluate(el => {
    const image=el.querySelector('img').getBoundingClientRect(),svg=el.querySelector('svg').getBoundingClientRect();
    return {iw:image.width,ih:image.height,sw:svg.width,sh:svg.height,hidden:el.querySelector('svg').hasAttribute('hidden')};
  });
  expect(geometry.hidden).toBe(false);
  expect(geometry.iw/geometry.ih).toBeCloseTo(16/9, 2);
  expect(geometry.iw).toBeCloseTo(geometry.sw, 2);expect(geometry.ih).toBeCloseTo(geometry.sh, 2);
  const dir = path.join(process.env.USERPROFILE, '.codex/visualizations/2026/10/17/material-integrity-p0');
  fs.mkdirSync(dir, {recursive: true});
  await page.screenshot({path:path.join(dir,'selection-desktop.png')});
  await page.getByRole('button', {name: '全选本组全部图片'}).click();
  await page.getByRole('button', {name: '批量删除 · 先预检查'}).click();
  await expect(page.getByRole('button', {name: '确认删除 125 条索引'})).toBeVisible();
  await page.screenshot({path:path.join(dir,'frozen-preview-desktop.png')});
  let calls = 0;
  await page.route('**/dedup-plans/*/execute', async route => {
    calls += 1;
    if(calls === 1)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'隔离测试：提交暂时不可用，请保留选择后重试'})});
    await route.fallback();
  });
  await page.getByRole('button', {name: '确认删除 125 条索引'}).click();
  await expect(page.locator('#materialIntegrityError47')).toContainText('请保留选择后重试');
  await page.screenshot({path:path.join(dir,'submit-failed-selection-preserved.png')});
  await page.getByRole('button', {name: '使用同一凭证重试 · 不会重复建任务'}).click();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('排队中');
  await expect(page.locator('#materialIntegrityTask47')).toContainText('成功 0');
  await page.screenshot({path:path.join(dir,'delete-queued.png')});
  await page.getByRole('button', {name: '返回审计与选择'}).click();
  await page.getByRole('button', {name: '批量去重 · 每组保留 1 张'}).click();
  await expect(page.getByRole('dialog', {name:'素材删除任务',exact:true})).toBeVisible();
  expect(calls).toBe(2);
  const deleteTaskId=(await page.locator('#materialIntegrityTask47 code').innerText()).replace('Task ID: ','');
  const worker=runIsolatedWorker(project.id,deleteTaskId,true);
  await expect(page.locator('#materialIntegrityTask47')).toContainText('删除中',{timeout:15000});
  await expect(page.locator('#materialIntegrityTask47')).toContainText('Worker: integrity-browser-worker');
  await page.screenshot({path:path.join(dir,'delete-running.png')});
  await worker;
  await expect(page.locator('#materialIntegrityTask47')).toContainText('已成功',{timeout:15000});
  await expect(page.locator('#materialIntegrityTask47')).toContainText('成功 125');
  await page.screenshot({path:path.join(dir,'delete-succeeded.png')});
  const groups = await request.get(`/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/groups`);
  expect((await groups.json()).stale).toBe(true);
  const remaining = isolatedPython(project.id,"import os,app; print(app.material_store(os.environ['INTEGRITY_TEST_PROJECT']).summary()['total'])");
  expect(remaining).toBe('1');
  const taskId=(await page.locator('#materialIntegrityTask47 code').innerText()).replace('Task ID: ','');
  const detail=await request.get(`/api/v62/projects/${project.id}/material-batches/${taskId}`);
  const log=await request.get(`/api/v62/projects/${project.id}/material-batches/${taskId}/log`);
  expect(detail.ok()).toBeTruthy();expect(log.ok()).toBeTruthy();
  fs.writeFileSync(path.join(dir,'isolated-delete-evidence.json'),JSON.stringify({project_id:project.id,audit_id:auditId,task:await detail.json(),remaining_count:Number(remaining),audit_stale:(await groups.json()).stale,submission_failure:'one injected HTTP 503; second request used the same frozen credential',worker_routing:'test-only unique capability after asserting original materials.batch; normal admission covered by Python',unrelated_audit_persisted_status:(await (await request.get(`/api/v62/projects/${otherProject.id}/material-batches/${unrelatedId}`)).json()).persisted_status},null,2));
  fs.writeFileSync(path.join(dir,'isolated-delete-task.log'),await log.text());
  await page.reload();
  await page.getByRole('button', {name:'重复与异常素材'}).click();
  await expect(page.getByText('审计快照已过期',{exact:true})).toBeVisible();
  await expect(page.locator('#materialIntegrityTask47')).toContainText('成功 125');
});


async function createProject(request) {
  const response = await request.post('/api/projects', {
    data: {
      name: `素材治理浏览器-${Date.now()}`,
      description: 'material integrity governance browser acceptance',
      labels: [{code: 'target', display_name: '目标', color: '#3b82f6'}],
    },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}


test('filtered anomaly selection, protected preview, aspect ratios and mobile recovery remain usable', async ({page, request}) => {
  const project = await createProject(request), auditId='isolated-anomaly-audit';
  const previews=[];
  for(const [width,height] of [[160,90],[90,160],[120,90]]){
    const buffer=execFileSync('python',['-c',`from PIL import Image; import io,sys; b=io.BytesIO(); Image.new('RGB',(${width},${height}),'#9ec9e6').save(b,format='PNG'); sys.stdout.buffer.write(b.getvalue())`]);
    const response=await request.post(`/api/projects/${project.id}/images`,{multipart:{files:{name:`evidence-${width}-${height}.png`,mimeType:'image/png',buffer},dataset_id:'default'}});
    const item=(await response.json()).uploaded[0];
    previews.push({image_id:item.id,filename:item.filename,width,height,content_url:`/api/v61/projects/${project.id}/materials/${item.id}/content`,boxes:[{label:'target',x1:10,y1:10,x2:40,y2:50}]});
  }
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.fallback({url:url.toString()})});
  await page.route(`**/api/v62/projects/${project.id}/material-batches?limit=50`,route=>route.fulfill({json:{items:[{task_id:auditId,operation:'AUDIT_MATERIAL_INTEGRITY',status:'SUCCEEDED',result:{scanned_images:10000,affected_images:10000,issue_groups:10000}}]}}));
  await page.route(`**/material-integrity/audits/${auditId}/groups?**`,route=>route.fulfill({json:{items:[{group_key:'INVALID_IMAGE:one',issue_type:'INVALID_IMAGE',image_count:1}],total_images:10000,next_cursor:null,stale:false}}));
  let payload;
  await page.route(`**/material-integrity/audits/${auditId}/dedup-plans`,route=>{payload=route.request().postDataJSON();return route.fulfill({status:201,json:{plan_id:'0123456789abcdef0123456789abcdef',confirmation_credential:'isolated-confirmation',selected_count:10000,delete_count:9990,annotation_count:30,protected_item_count:10,manual_required_count:0,unverifiable_count:0,preview_items:previews}})});
  await page.addInitScript(()=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:'数据集'})));
  await page.goto('/');await page.getByRole('button',{name:/数据集/}).click();await page.getByRole('button',{name:'重复与异常素材'}).click();
  await page.getByRole('button',{name:'全选当前页',exact:true}).click();
  await expect(page.locator('#materialIntegrityGroupSelected47')).toContainText('已选 1 组');
  await page.getByRole('button',{name:'取消全选'}).click();
  await expect(page.getByRole('checkbox')).not.toBeChecked();
  await page.locator('#materialIntegrityFilter47').selectOption('INVALID_IMAGE');
  await page.getByRole('button',{name:'全选当前筛选结果'}).click();
  await expect(page.locator('#materialIntegrityGroupSelected47')).toContainText('10000 张');
  const dir=path.join(process.env.USERPROFILE,'.codex/visualizations/2026/10/17/material-integrity-p0');
  fs.mkdirSync(dir,{recursive:true});
  for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]){
    await page.setViewportSize({width,height});
    await expect(page.getByRole('button',{name:'预览所选组'})).toBeVisible();
    const overflow=await page.evaluate(()=>({width:innerWidth,total:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('*')].filter(el=>el.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(el=>[el.tagName,el.className,el.parentElement?.className,el.parentElement?.parentElement?.className,el.getBoundingClientRect().width])}));
    expect(overflow.total,JSON.stringify(overflow)).toBeLessThanOrEqual(width);
    await page.screenshot({path:path.join(dir,`all-filtered-${width}.png`)});
  }
  await page.getByRole('button',{name:'预览所选组'}).click();
  expect(payload.scope).toBe('FILTERED');expect(payload.issue_type).toBe('INVALID_IMAGE');expect(payload.image_ids).toBeUndefined();
  await expect(page.getByRole('button',{name:'确认删除 9990 条索引'})).toBeVisible();
  for(const [index,item] of previews.entries()){
    const frame=page.locator('.material-integrity47-plan .material-integrity47-image').nth(index);
    await frame.scrollIntoViewIfNeeded();
    await expect.poll(()=>frame.locator('img').evaluate(el=>el.complete&&el.naturalWidth)).toBe(item.width);
    const sizes=await frame.evaluate(el=>{const image=el.querySelector('img').getBoundingClientRect(),svg=el.querySelector('svg').getBoundingClientRect();return [image.width,image.height,svg.width,svg.height]});
    expect(sizes[0]/sizes[1]).toBeCloseTo(item.width/item.height,2);expect(sizes[0]).toBeCloseTo(sizes[2],2);expect(sizes[1]).toBeCloseTo(sizes[3],2);
  }
  const first=page.locator('.material-integrity47-plan .material-integrity47-image').first();
  await first.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(dir,'frozen-preview-mobile.png')});
  const brokenPattern='**'+previews[0].content_url+'?isolated_failure=*';
  await page.route(brokenPattern,route=>route.fulfill({status:404,body:'isolated missing object'}));
  await first.getByRole('img').evaluate(el=>{el.src+='?isolated_failure=1'});
  await expect(first.locator('svg')).toBeHidden();await expect(first.getByRole('button',{name:'重新加载'})).toBeVisible();
  await page.unroute(brokenPattern);
  await first.getByRole('button',{name:'重新加载'}).click();await expect(first.locator('svg')).toBeVisible();
  await page.getByRole('button',{name:'返回选择 · 保留勾选'}).click();
  await expect(page.locator('#materialIntegrityFilter47')).toHaveValue('INVALID_IMAGE');
  await expect(page.locator('#materialIntegrityGroupSelected47')).toContainText('10000 张');
});

test('global duplicate governance previews, confirms, reports progress, and invalidates the audit', async ({page, request}) => {
  await page.setViewportSize({width: 1366, height: 768});
  const project = await createProject(request);
  const auditId = 'audit-browser-governance';
  const planId = '0123456789abcdef0123456789abcdef';
  const taskId = 'delete-browser-governance';
  let planPayload = null;
  let executionPayload = null;
  let polls = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', project.id);
    await route.fallback({url: url.toString()});
  });
  await page.route(`**/api/v62/projects/${project.id}/material-batches?limit=50`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [{
      task_id: auditId,
      operation: 'AUDIT_MATERIAL_INTEGRITY',
      status: 'SUCCEEDED',
      result: {scanned_images: 15, affected_images: 8, issue_groups: 3, scan_failures: 0},
    }]}),
  }));
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/groups?limit=100`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        group_key: `DUPLICATE_IDENTICAL:${'a'.repeat(64)}`,
        issue_type: 'DUPLICATE_IDENTICAL',
        content_sha256: 'a'.repeat(64),
        image_count: 5,
      }],
      next_cursor: null,
    }),
  }));
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/dedup-plans`, async route => {
    planPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        plan_id: planId,
        confirmation_credential: 'browser-confirmation-credential',
        operation: 'DELETE_INDEX',
        included_groups: 1,
        kept_count: 1,
        delete_count: 4,
        skipped_groups: 2,
        skipped_item_count: 3,
        manual_required_groups: 1,
        protected_groups: 1,
        skip_reasons: {MANUAL_DECISION_REQUIRED: 1, MULTIPLE_PROTECTED_REFERENCES: 1},
        preview_groups: [{
          group_key: `DUPLICATE_IDENTICAL:${'a'.repeat(64)}`,
          keeper_image_id: 'keeper-image-001',
          keeper_reason: 'VERIFIED_SOURCE_AND_ANNOTATION',
          delete_count: 4,
        }],
        preview_groups_truncated: false,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/dedup-plans/${planId}/execute`, async route => {
    executionPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: taskId,
        operation: 'DELETE_INDEX',
        status: 'QUEUED',
        total: 4,
        processed: 0,
        succeeded: 0,
        failed: 0,
        planned_groups: 1,
        completed_groups: 0,
        failed_groups: 0,
        kept_count: 1,
        skipped_groups: 2,
        material_integrity_audit_id: auditId,
        material_integrity_plan_id: planId,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${project.id}/material-batches/${taskId}`, route => {
    polls += 1;
    const finished = polls > 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: taskId,
        operation: 'DELETE_INDEX',
        status: finished ? 'SUCCEEDED' : 'RUNNING',
        total: 4,
        processed: finished ? 4 : 1,
        succeeded: finished ? 4 : 1,
        failed: 0,
        planned_groups: 1,
        completed_groups: finished ? 1 : 0,
        failed_groups: 0,
        kept_count: 1,
        skipped_groups: 2,
        material_integrity_audit_id: auditId,
        material_integrity_plan_id: planId,
      }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: '重复与异常素材'}).click();
  const auditDialog = page.getByRole('dialog', {name: '重复与异常素材', exact: true});
  await expect(auditDialog).toBeVisible();
  const globalPreview = auditDialog.getByRole('button', {name: '批量去重 · 每组保留 1 张'});
  await expect(globalPreview).toBeVisible();
  await globalPreview.click();

  const previewDialog = page.getByRole('dialog', {name: '重复素材治理预览', exact: true});
  await expect(previewDialog).toBeVisible();
  await expect(previewDialog.getByText('keeper-image-001')).toBeVisible();
  await expect(previewDialog.getByText('确认删除 4 条索引')).toBeVisible();
  expect(planPayload).toEqual({scope: 'SAFE_ALL', group_keys: []});
  expect(JSON.stringify(planPayload)).not.toContain('image_ids');
  const previewBox = await previewDialog.boundingBox();
  expect(previewBox.y + previewBox.height).toBeLessThanOrEqual(768);

  const screenshotDir = path.join(
    process.env.USERPROFILE || process.cwd(), '.codex', 'visualizations',
    '2026', '10', '15', 'material-integrity-governance',
  );
  fs.mkdirSync(screenshotDir, {recursive: true});
  await page.screenshot({
    path: path.join(screenshotDir, 'dedup-plan-1366x768.png'),
    fullPage: false,
  });

  await previewDialog.getByRole('button', {name: '确认删除 4 条索引'}).click();
  expect(executionPayload).toEqual({confirmation_credential: 'browser-confirmation-credential'});
  await expect(page.locator('#toast')).toContainText('批量去重：处理中');
  await expect(page.locator('#toast')).toContainText('完成组 0/1');
  await expect.poll(() => polls, {timeout: 5_000}).toBeGreaterThan(1);
  await expect(page.locator('#toast')).toContainText('旧审计已失效');
});
