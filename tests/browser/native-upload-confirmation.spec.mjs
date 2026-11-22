import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooAKKKKACiiigAooooA//2Q==', 'base64');

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
}
async function startIsolated(env) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('isolated server startup timeout')), 40000);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`isolated server exited ${code}`)); });
    const onData = chunk => { if (String(chunk).includes('Uvicorn running on')) { clearTimeout(timer); resolve(); } };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
  });
  return {origin, child};
}
async function projectWith(request, origin, name, labels = [{code: 'fire', display_name: '明火'}]) {
  return (await request.post(origin + '/api/projects', {data: {name, labels}})).json();
}
function files(count, prefix = 'confirm') {
  return Array.from({length: count}, (_, index) => ({
    name: `${prefix}-${String(index).padStart(3, '0')}.jpg`, mimeType: 'image/jpeg', buffer: JPEG,
  }));
}
async function openUpload(page, origin, projectId) {
  await page.goto(`${origin}/app/#/projects/${projectId}/materials/upload`);
  await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
}
async function upload(page, rows) {
  await page.locator('.uppy-Dashboard input[type=file]').first().setInputFiles(rows);
  const button = page.locator('.uppy-StatusBar-actionBtn--upload');
  await expect(button).toBeVisible({timeout: 15000});
  await button.click();
  await expect(page.getByText(new RegExp(`服务器已确认 ${rows.length} / ${rows.length} 张`)))
    .toBeVisible({timeout: 120000});
  await expect(page.locator('.upload-confirmation .uc-workspace')).toBeVisible({timeout: 30000});
  await expect(page.getByRole('link', {name: /AI 预标注/})).toHaveAttribute('href', /source_batch_id=/);
}
async function choosePositive(page) {
  await page.locator('[data-upload-action="all"]').check();
  await page.locator('input[name="uc-kind"][value="positive"]').check();
  await page.locator('[data-uc-label="fire"]').check();
}

test('native confirmation opens a real preview and submits a positive upload intent before annotation', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-confirm-ready-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '上传确认正样本');
    await openUpload(page, origin, project.id);
    await upload(page, files(5));

    await page.evaluate(() => window.scrollTo(0, 900));
    await page.waitForTimeout(500);
    await page.locator('[data-preview]').first().click();
    const dialog = page.locator('.el-dialog').filter({has: page.locator('img.preview-image')});
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('img.preview-image')).toBeVisible();
    await dialog.locator('.el-dialog__headerbtn').click();
    await expect(dialog).toHaveCount(0);

    await choosePositive(page);
    let decisionBody = null;
    await page.route('**/decisions', async route => {
      const response = await route.fetch();
      decisionBody = await response.json();
      return route.fulfill({response});
    });
    const intentPromise = page.waitForRequest(req => new URL(req.url()).pathname.endsWith('/negative-pool/upload-intent'));
    await page.locator('[data-upload-action="ready"]').click();
    const intent = (await intentPromise).postDataJSON();
    expect(intent.sample_type).toBe('positive');
    expect(intent.label_codes).toEqual(['fire']);
    expect(intent.image_ids).toHaveLength(5);
    await expect.poll(() => !!decisionBody).toBe(true);
    expect((decisionBody.items || []).every(item => item.decision === 'ready')).toBe(true);
    await page.waitForURL(/spa_handoff=1/);
    expect(decodeURIComponent(page.url())).toContain('material-annotate');
    expect(decodeURIComponent(page.url())).toMatch(/material_id=/);
  } finally { child.kill(); }
});

test('native confirmation submits a clean decision through the original batch owner', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-confirm-clean-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '上传确认清洗');
    await openUpload(page, origin, project.id);
    await upload(page, files(2, 'clean'));
    await choosePositive(page);
    const decisionPromise = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/decisions'));
    await page.locator('[data-upload-action="clean"]').click();
    const decision = await (await decisionPromise).json();
    expect((decision.clean_task_id || '')).toBeTruthy();
    expect((decision.items || []).every(item => item.decision === 'clean')).toBe(true);
    await expect(page.locator('[data-task]').first()).toBeVisible({timeout: 30000});
    let cleanNavigation = '';
    await page.route(/\/\?spa_handoff=/, route => {
      cleanNavigation = route.request().url();
      return route.fulfill({contentType: 'text/html', body: 'legacy-owner'});
    });
    await page.locator('[data-task]').first().click();
    await expect.poll(() => cleanNavigation).toContain('action=material-clean-task');
    expect(cleanNavigation).toContain(`task_id=${decision.clean_task_id}`);
    const auth = await (await request.get(origin + '/api/auth/session')).json();
    const actorKey = JSON.stringify([auth.provider || '', auth.user?.username || '']);
    const key = `material-upload-session:v2:${encodeURIComponent(actorKey)}:${encodeURIComponent(project.id)}`;
    const stored = await page.evaluate(storageKey => JSON.parse(localStorage.getItem(storageKey)), key);
    const receipt = await (await request.get(
      `${origin}/api/v55/projects/${project.id}/upload-batches/${stored.batchIds[0]}`)).json();
    expect(receipt.clean_task_id).toBe(decision.clean_task_id);
    expect(receipt.items.every(item => item.decision === 'clean')).toBe(true);
    await page.goto(`${origin}/app/?clean=1#/projects/${project.id}/materials/tasks`);
    const row = page.getByRole('row').filter({hasText: '图片上传批次'});
    await expect(row).toContainText('待确认 0', {timeout: 30000});
    await expect(row.getByText('待人工确认')).toHaveCount(0);
  } finally { child.kill(); }
});

test('smart quality audit opens the legacy owner with the selected material ids', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-confirm-smart-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '上传确认智能质检');
    await openUpload(page, origin, project.id);
    await upload(page, files(2, 'smart'));
    await page.locator('[data-upload-action="all"]').check();
    let navigation = '';
    await page.route(/\/\?spa_handoff=/, route => {
      navigation = route.request().url();
      return route.fulfill({contentType: 'text/html', body: 'legacy-owner'});
    });
    await page.locator('[data-upload-action="smart"]').click();
    await expect.poll(() => navigation).toContain('action=material-smart-audit');
    const target = new URL(navigation);
    expect(target.searchParams.get('page')).toBe('数据集');
    expect(target.searchParams.get('source')).toBe('upload');
    expect(target.searchParams.get('image_ids').split(',').filter(Boolean)).toHaveLength(2);
  } finally { child.kill(); }
});

test('smart audit over 500 materials is rejected instead of silently truncated', async ({page, request}) => {
  test.setTimeout(120_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-smart-limit-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '智能质检上限');
    await openUpload(page, origin, project.id);
    await expect.poll(() => page.evaluate(() => typeof window.openSmartMaterialAudit === 'function'))
      .toBe(true);
    let navigations = 0;
    page.on('request', request => {
      if (new URL(request.url()).pathname === '/') navigations += 1;
    });
    await page.evaluate(() => window.openSmartMaterialAudit({
      imageIds: Array.from({length: 501}, (_, index) => `image-${index}`), source: 'upload',
    }));
    await expect(page.getByText(/单次最多 500 张/)).toBeVisible({timeout: 10000});
    expect(navigations).toBe(0);
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/materials/upload`));
  } finally { child.kill(); }
});

test('smart quality audit opens the real legacy workbench with the selected project scope', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-smart-real-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '真实智能质检入口');
    await openUpload(page, origin, project.id);
    await upload(page, files(2, 'smart-real'));
    const materials = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    const ids = materials.items.map(row => row.id);
    expect(ids).toHaveLength(2);

    await page.goto(origin);
    await expect.poll(() => page.evaluate(() => typeof state !== 'undefined' && state?.uiReady === true),
      {timeout: 90000}).toBe(true);
    await page.evaluate(async projectId => {
      const detail = await (await fetch(`/api/projects/${projectId}`)).json();
      state.project = detail.project;
    }, project.id);
    await page.evaluate(({imageIds, projectId}) => window.openSmartMaterialAudit({
      imageIds, projectId, source: 'upload',
    }), {imageIds: ids, projectId: project.id});
    const panel = page.locator('.smart-material-audit').last();
    await expect(panel).toBeVisible({timeout: 60000});
    await expect(panel.locator('[data-scope]')).toHaveValue('SELECTED');
    expect(await page.evaluate(() => state.project?.id)).toBe(project.id);
  } finally { child.kill(); }
});

test('clean task progress opens the real legacy task modal for the created task', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-clean-real-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '真实清洗任务入口');
    await openUpload(page, origin, project.id);
    await upload(page, files(2, 'clean-real'));
    await choosePositive(page);
    await page.locator('[data-upload-action="clean"]').click();
    const taskButton = page.locator('[data-task]').first();
    await expect(taskButton).toBeVisible({timeout: 60000});
    const taskId = await taskButton.getAttribute('data-task');
    expect(taskId).toBeTruthy();
    await page.goto(origin);
    await expect.poll(() => page.evaluate(() => typeof state !== 'undefined' && state?.uiReady === true),
      {timeout: 90000}).toBe(true);
    await page.evaluate(async projectId => {
      const detail = await (await fetch(`/api/projects/${projectId}`)).json();
      state.project = detail.project;
    }, project.id);
    await page.evaluate(id => window.showTaskProgress427('clean', id), taskId);
    const modal = page.locator('.modal:not(.hidden)').last();
    await expect(modal).toContainText('自动清洗', {timeout: 60000});
    await expect(modal).toContainText('进度');
    expect(await page.evaluate(() => state.project?.id)).toBe(project.id);
  } finally { child.kill(); }
});

test('negative pool intent and later-deferred confirmation survive a page refresh', async ({page, request}) => {
  test.setTimeout(300_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-confirm-negative-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await projectWith(request, origin, '上传确认负样本');
    const categoryResponse = await request.post(
      `${origin}/api/v61/projects/${project.id}/negative-pool/categories`, {data: {name: '测试负样本分类'}});
    expect(categoryResponse.ok()).toBeTruthy();
    await openUpload(page, origin, project.id);
    await upload(page, files(2, 'negative'));
    await page.locator('[data-upload-action="all"]').check();
    await page.locator('input[name="uc-kind"][value="negative"]').check();
    const category = page.locator('[data-uc-category]').first();
    await expect(category).toBeVisible({timeout: 30000});
    await category.check();
    const intentPromise = page.waitForRequest(req => new URL(req.url()).pathname.endsWith('/negative-pool/upload-intent'));
    await page.locator('[data-upload-action="ready"]').click();
    const intent = (await intentPromise).postDataJSON();
    expect(intent.sample_type).toBe('negative');
    expect(intent.category_ids).toHaveLength(1);
    expect(intent.label_codes).toEqual([]);

    await page.getByRole('button', {name: '再选一批', exact: true}).click();
    await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});
    await upload(page, files(1, 'later'));
    await page.locator('[data-upload-action="later"]').click();
    const auth = await (await request.get(origin + '/api/auth/session')).json();
    const actorKey = JSON.stringify([auth.provider || '', auth.user?.username || '']);
    const key = `material-upload-session:v2:${encodeURIComponent(actorKey)}:${encodeURIComponent(project.id)}`;
    await expect.poll(async () => page.evaluate(storageKey =>
      JSON.parse(localStorage.getItem(storageKey) || 'null')?.deferred, key)).toBe(true);

    await page.reload();
    await expect(page.locator('.upload-confirmation')).toContainText('本次上传图片', {timeout: 45000});
    await expect(page.locator('.upload-confirmation')).toContainText('1 张待处理');
    await page.goto(`${origin}/app/#/projects/${project.id}/materials/tasks`);
    const row = page.getByRole('row').filter({hasText: '图片上传批次'}).filter({hasText: '待确认 1'});
    await expect(row).toBeVisible({timeout: 30000});
  } finally { child.kill(); }
});
