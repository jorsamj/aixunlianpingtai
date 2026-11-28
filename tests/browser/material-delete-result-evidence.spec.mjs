import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q==', 'base64');

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
async function upload(request, origin, projectId, name) {
  const response = await request.post(`${origin}/api/projects/${encodeURIComponent(projectId)}/images`, {
    multipart: {files: {name, mimeType: 'image/jpeg', buffer: JPEG}, dataset_id: 'default'},
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).uploaded[0];
}
async function projectWith(request, origin, name, count) {
  const project = await (await request.post(origin + '/api/projects', {
    data: {name, labels: [{code: 'fire', display_name: '明火'}]},
  })).json();
  const rows = [];
  for (let index = 0; index < count; index += 1)
    rows.push(await upload(request, origin, project.id, `${name}-${index}.jpg`));
  return {project, rows};
}
const hasRecord = page => page.evaluate(() => Object.keys(localStorage)
  .some(key => key.startsWith('ai-material-delete:v1:')));
async function waitBackendTerminal(request, origin, projectId, taskId) {
  await expect.poll(async () => (await (await request.get(
    `${origin}/api/v62/projects/${projectId}/material-batches/${taskId}`)).json()).status,
  {timeout: 120000}).toBe('SUCCEEDED');
}
async function startDelete(page, name) {
  const estimatePromise = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/material-batches/estimate'));
  await page.getByRole('button', {name, exact: true}).click();
  const estimate = await (await estimatePromise).json();
  return estimate.deletion_preview.plan_id;
}

test('delete results separate pending, running, failed and partial success instead of marking them failed', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-delete-states-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  let worker;
  try {
    const {project, rows} = await projectWith(request, origin, '删除状态分离', 3);
    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '240'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    for (const row of rows)
      await expect(page.locator('.material-card').filter({hasText: row.filename})).toBeVisible({timeout: 45000});
    await page.getByRole('button', {name: '选择本页', exact: true}).click();
    await expect(page.getByText(/已选 3 张/)).toBeVisible();

    let mode = 'states', planId = '';
    await page.route('**/api/v62/projects/*/material-batches/*', async route => {
      const url = new URL(route.request().url());
      if (route.request().method() !== 'GET' || !planId
          || !url.pathname.endsWith(`/material-batches/${planId}`)) return route.continue();
      const real = await (await route.fetch()).json();
      return route.fulfill({json: {...real, status: 'PARTIAL_SUCCESS', succeeded: 1, failed: 2}});
    });
    await page.route('**/api/v62/projects/*/material-batches/*/results*', async route => {
      const url = new URL(route.request().url());
      if (!mode || !planId || !url.pathname.includes(`/material-batches/${planId}/results`))
        return route.continue();
      const [a, b, c] = rows.map(row => row.id);
      const items = mode === 'states'
        ? [{image_id: a, item_state: 'succeeded'}, {image_id: b, item_state: 'failed'},
          {image_id: c, item_state: 'pending'}, {image_id: a, item_state: 'succeeded'}]
        : mode === 'running'
          ? [{image_id: a, item_state: 'succeeded'}, {image_id: b, item_state: 'failed'},
            {image_id: c, item_state: 'running'}, {image_id: a, item_state: 'succeeded'}]
          : [{image_id: a, item_state: 'succeeded'}, {image_id: b, item_state: 'failed'},
            {image_id: c, item_state: 'failed'}, {image_id: a, item_state: 'succeeded'}];
      return route.fulfill({json: {items, succeeded_image_ids: [a, a], next_cursor: null}});
    });

    planId = await startDelete(page, '删除所选 3 张');
    await page.locator('.el-dialog').getByRole('button', {name: '确认删除'}).click();
    await expect(page.locator('.el-dialog')).toContainText('成功 1 · 失败 1 · 未处理 1', {timeout: 60000});
    await expect(page.locator('.el-dialog')).toContainText('已读 3 / 应有 3');
    await expect(page.locator('.el-dialog')).toContainText('不能当作已删除或失败');
    expect(await hasRecord(page)).toBe(true);
    await expect(page.getByText(/已选 2 张/)).toBeVisible();
    expect(await page.getByText(/失败 2/).count()).toBe(0);

    mode = 'running';
    await page.locator('.el-dialog').getByRole('button', {name: '核验删除结果'}).click();
    await expect(page.locator('.el-dialog')).toContainText('处理中 1', {timeout: 30000});
    await expect(page.locator('.el-dialog')).toContainText('不能当作已删除或失败');
    expect(await hasRecord(page)).toBe(true);
    await expect(page.getByText(/已选 2 张/)).toBeVisible();

    mode = 'partial';
    await page.locator('.el-dialog').getByRole('button', {name: '核验删除结果'}).click();
    await expect(page.locator('.el-dialog')).toContainText('部分成功：已删除 1 张，失败 2 张', {timeout: 30000});
    await expect(page.locator('.el-dialog')).toContainText('只有成功项从选择中移除');
    await expect(page.locator('.el-dialog')).toContainText('成功 1 · 失败 2 · 未处理 0');
    expect(await hasRecord(page)).toBe(false);
    await expect(page.getByText(/已选 2 张/)).toBeVisible();
  } finally {
    worker?.kill();
    child.kill();
  }
});

test('repeated result cursors never prove deletion and keep the plan for verification', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-delete-cursor-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  let worker;
  try {
    const {project, rows} = await projectWith(request, origin, '删除游标循环', 2);
    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '240'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    for (const row of rows)
      await expect(page.locator('.material-card').filter({hasText: row.filename})).toBeVisible({timeout: 45000});
    await page.getByRole('button', {name: '选择本页', exact: true}).click();
    const cursors = [];
    let loop = true, planId = '';
    await page.route('**/api/v62/projects/*/material-batches/*/results*', async route => {
      const url = new URL(route.request().url());
      if (!loop || !planId || !url.pathname.includes(`/material-batches/${planId}/results`))
        return route.continue();
      cursors.push(url.searchParams.get('cursor') || '');
      const items = url.searchParams.get('cursor')
        ? [] : [{image_id: rows[0].id, item_state: 'succeeded'}];
      return route.fulfill({json: {items, succeeded_image_ids: [], next_cursor: 'same-cursor'}});
    });
    let creates = 0;
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() === 'POST' && url.pathname.endsWith('/material-batches')) creates += 1;
    });

    planId = await startDelete(page, '删除所选 2 张');
    await page.locator('.el-dialog').getByRole('button', {name: '确认删除'}).click();
    await expect(page.locator('.el-dialog')).toContainText('尚未完整覆盖本次范围', {timeout: 90000});
    await expect(page.locator('.el-dialog')).toContainText('已读 1 / 应有 2');
    expect(cursors).toContain('');
    expect(cursors).toContain('same-cursor');
    expect(await hasRecord(page)).toBe(true);
    await expect(page.getByText(/已选 2 张/)).toBeVisible();

    await page.locator('.el-dialog').getByRole('button', {name: '核验删除结果'}).click();
    await expect(page.locator('.el-dialog')).toContainText('尚未完整覆盖本次范围');
    expect(creates).toBe(1);
    expect(await hasRecord(page)).toBe(true);

    await page.unroute('**/api/v62/projects/*/material-batches/*/results*');
    await waitBackendTerminal(request, origin, project.id, planId);
    await page.locator('.el-dialog').getByRole('button', {name: '核验删除结果'}).click();
    await expect(page.getByText(/已选 0 张/)).toBeVisible({timeout: 30000});
    expect(await hasRecord(page)).toBe(false);
    expect(creates).toBe(1);
  } finally {
    worker?.kill();
    child.kill();
  }
});

test('result rows outside the frozen scope are an identity error and never clean local state', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-delete-foreign-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  let worker;
  try {
    const {project, rows} = await projectWith(request, origin, '删除范围身份', 1);
    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '240'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    await expect(page.locator('.material-card').filter({hasText: rows[0].filename}))
      .toBeVisible({timeout: 45000});
    await page.getByRole('button', {name: '选择本页', exact: true}).click();
    let foreign = true, planId = '';
    await page.route('**/api/v62/projects/*/material-batches/*/results*', async route => {
      const url = new URL(route.request().url());
      if (!foreign || !planId || !url.pathname.includes(`/material-batches/${planId}/results`))
        return route.continue();
      return route.fulfill({json: {items: [
        {image_id: rows[0].id, item_state: 'succeeded'},
        {image_id: 'foreign-image-id', item_state: 'succeeded'},
      ], succeeded_image_ids: [rows[0].id, 'foreign-image-id'], next_cursor: null}});
    });
    planId = await startDelete(page, '删除所选 1 张');
    await page.locator('.el-dialog').getByRole('button', {name: '确认删除'}).click();
    await expect(page.locator('.el-dialog')).toContainText('身份异常', {timeout: 90000});
    expect(await hasRecord(page)).toBe(true);
    await expect(page.getByText(/已选 1 张/)).toBeVisible();

    foreign = false;
    await page.unroute('**/api/v62/projects/*/material-batches/*/results*');
    await waitBackendTerminal(request, origin, project.id, planId);
    await page.locator('.el-dialog').getByRole('button', {name: '核验删除结果'}).click();
    await expect(page.getByText(/已选 0 张/)).toBeVisible({timeout: 30000});
    expect(await hasRecord(page)).toBe(false);
  } finally {
    worker?.kill();
    child.kill();
  }
});
