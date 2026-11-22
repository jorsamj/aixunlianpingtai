import {test, expect} from '@playwright/test';
import {spawn, execFileSync} from 'node:child_process';
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
function zipBuffer() {
  return execFileSync('python', ['-c', `
import base64, io, sys, zipfile
jpeg = base64.b64decode('''${JPEG.toString('base64')}''')
z = io.BytesIO()
with zipfile.ZipFile(z, 'w', compression=zipfile.ZIP_STORED) as archive:
    archive.writestr('images/one.jpg', jpeg)
    archive.writestr('images/two.jpg', jpeg)
sys.stdout.buffer.write(z.getvalue())
`], {maxBuffer: 4 * 1024 * 1024});
}

test('native upload task center keeps image receipts, ZIP jobs and project identity separate', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-tasks-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '统一上传任务', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const other = await (await request.post(origin + '/api/projects', {
      data: {name: '另一个项目', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();

    const requestId = 'e2e-image-batch-0001';
    const uploaded = await request.post(`${origin}/api/projects/${project.id}/images`, {
      multipart: {
        files: {name: 'task-1.jpg', mimeType: 'image/jpeg', buffer: JPEG},
        dataset_id: 'default', upload_request_id: requestId,
      },
    });
    expect(uploaded.ok()).toBeTruthy();
    expect((await uploaded.json()).batch_id).toBe(requestId);

    const archive = zipBuffer();
    const session = await request.post(
      `${origin}/api/v19/projects/${project.id}/datasets/default/import/uploads`,
      {data: {file_name: 'raw-e2e.zip', file_size: archive.length, fingerprint: 'e2e-zip-fingerprint'}});
    expect(session.ok()).toBeTruthy();
    const uploadId = (await session.json()).upload_id;
    const part = await request.put(
      `${origin}/api/v19/projects/${project.id}/import/uploads/${uploadId}/parts/0`,
      {data: archive, headers: {'Content-Type': 'application/octet-stream'}});
    expect(part.ok(), `${part.status()} ${await part.text()}`).toBeTruthy();
    expect((await request.post(
      `${origin}/api/v19/projects/${project.id}/import/uploads/${uploadId}/complete`)).status()).toBe(202);
    await expect.poll(async () => (await (await request.get(
      `${origin}/api/v19/projects/${project.id}/import/jobs/${uploadId}`)).json()).status,
    {timeout: 30000}).toBe('selecting');

    await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [
      `material-upload-session:${project.id}`,
      JSON.stringify({projectId: project.id, totalFiles: 1, requestIds: [requestId],
        batchIds: [requestId], status: 'SUCCEEDED', failed: 0}),
    ]);
    await page.goto(`${origin}/app/#/projects/${project.id}/materials/tasks`);
    await expect(page.getByRole('heading', {name: '上传任务', level: 2})).toBeVisible({timeout: 30000});
    const imageRow = page.getByRole('row').filter({hasText: '图片上传批次'});
    await expect(imageRow).toContainText('服务器已入库');
    await expect(imageRow).toContainText('已确认 1 张成功');
    await expect(imageRow).toContainText(requestId);
    const zipRow = page.getByRole('row').filter({hasText: 'raw-e2e.zip'});
    await expect(zipRow).toContainText('等待标签确认');
    await expect(zipRow).toContainText(`import_job_id ${uploadId}`);
    await expect(zipRow).toContainText('查看 / 标签确认');

    await zipRow.getByRole('button', {name: '查看 / 标签确认'}).click();
    await expect(page).toHaveURL(new RegExp(`/materials/zip\\?job=${uploadId}`));
    await expect(page.locator('#native-zip-modal-root .modal')).toBeVisible({timeout: 45000});
    await expect(page.locator('#native-zip-modal-root')).toContainText('raw-e2e.zip');

    await page.goto(`${origin}/app/?p=${other.id}#/projects/${other.id}/materials/tasks`);
    await expect(page.getByRole('heading', {name: '上传任务', level: 2})).toBeVisible();
    await expect(page.getByText('当前项目没有可核验的上传批次')).toBeVisible({timeout: 30000});
    await expect(page.getByText('raw-e2e.zip')).toHaveCount(0);
    await expect(page.getByText(requestId)).toHaveCount(0);
  } finally { child.kill(); }
});
