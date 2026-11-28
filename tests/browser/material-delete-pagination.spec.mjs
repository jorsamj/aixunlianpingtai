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

test('101 selected materials survive three pages and read every result cursor page', async ({page, request}) => {
  test.setTimeout(360_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-material-delete-pages-'));
  const env = {
    ...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics'),
  };
  const {origin, child} = await startIsolated(env);
  let worker;
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '隔离跨页删除', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const rows = [];
    for (let index = 0; index < 101; index += 1)
      rows.push(await upload(request, origin, project.id, `page-item-${String(index).padStart(3, '0')}.jpg`));

    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '300'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });
    const resultRequests = [];
    page.on('request', req => {
      const url = new URL(req.url());
      if (url.pathname.endsWith('/results')) resultRequests.push(url);
    });
    let estimatePayload = null;
    await page.route('**/api/v62/projects/*/material-batches/estimate', async route => {
      const response = await route.fetch();
      estimatePayload = await response.json();
      return route.fulfill({response});
    });

    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    const cards = page.locator('.material-card');
    await expect(cards.first()).toBeVisible({timeout: 45000});
    await expect(page.getByText(/共 101 张素材/)).toBeVisible();

    for (let pageIndex = 1; pageIndex <= 3; pageIndex += 1) {
      await page.getByRole('button', {name: '选择本页', exact: true}).click();
      const expected = pageIndex === 3 ? 101 : pageIndex * 48;
      await expect(page.getByText(new RegExp(`已选 ${expected} 张`))).toBeVisible();
      if (pageIndex < 3) {
        await page.getByRole('button', {name: '下一页', exact: true}).click();
        await expect(page).toHaveURL(new RegExp(`page=${pageIndex + 1}`));
        await expect(cards.first()).toBeVisible();
      }
    }
    expect(rows.length).toBe(101);

    // Going back to the first page keeps every earlier selection.
    await page.getByRole('button', {name: '上一页', exact: true}).click();
    await page.getByRole('button', {name: '上一页', exact: true}).click();
    await expect(page).not.toHaveURL(/page=[23]/);
    await expect(cards.first().locator('.el-checkbox')).toHaveClass(/is-checked/);
    await expect(page.getByText(/已选 101 张/)).toBeVisible();

    // A reload restores the same selection set from the existing session memory.
    await page.reload();
    await expect(page.getByText(/已选 101 张/)).toBeVisible({timeout: 45000});

    await page.getByRole('button', {name: '删除所选 101 张', exact: true}).click();
    await expect(page.locator('.el-dialog')).toContainText('本次删除 101 张素材', {timeout: 30000});
    expect(estimatePayload.selection_spec.scope).toBe('SELECTED');
    expect(estimatePayload.selection_spec.image_ids).toHaveLength(101);
    expect(new Set(estimatePayload.selection_spec.image_ids).size).toBe(101);
    expect(estimatePayload.selection_spec.image_ids.sort()).toEqual(rows.map(row => row.id).sort());

    await page.locator('.el-dialog').getByRole('button', {name: '确认删除'}).click();
    await expect(page.getByText(/已选 0 张/)).toBeVisible({timeout: 180000});
    await expect(page.locator('.material-card')).toHaveCount(0);
    expect(await page.evaluate(() => Object.keys(localStorage)
      .some(key => key.startsWith('ai-material-delete:v1:')))).toBe(false);

    await expect.poll(() => resultRequests.filter(url =>
      url.pathname.includes('/results')).length, {timeout: 30000}).toBeGreaterThanOrEqual(2);
    const first = resultRequests.find(url => !url.searchParams.get('cursor'));
    const second = resultRequests.find(url => url.searchParams.get('cursor'));
    expect(first).toBeTruthy();
    expect(second).toBeTruthy();
    expect(second.searchParams.get('cursor')).toBeTruthy();
    expect(second.searchParams.get('cursor')).not.toBe(first.searchParams.get('cursor'));

    const pageOne = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(pageOne.total).toBe(0);
    const finished = await (await request.get(
      `${origin}/api/v62/projects/${project.id}/material-batches/${estimatePayload.deletion_preview.plan_id}`)).json();
    expect(finished.status).toBe('SUCCEEDED');
    expect(finished.succeeded).toBe(101);
  } finally {
    worker?.kill();
    child.kill();
  }
});
